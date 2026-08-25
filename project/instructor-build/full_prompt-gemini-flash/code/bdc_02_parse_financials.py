"""
bdc_02_parse_financials.py - Balance Sheet / Statement of Assets and Liabilities Parser.

Extracts fund-level financial statements from SEC EDGAR filings:
- Total Investments at Fair Value & Amortized Cost
- Cash and Cash Equivalents
- Other Assets
- Total Assets
- Debt Outstanding
- Other Liabilities
- Total Liabilities
- Net Assets / Total Stockholders' Equity
- Shares Outstanding & NAV Per Share

Saves raw fund financials into data/interim/fund_financials_raw.csv.
"""

import os
import sys
import json
import re
import pandas as pd
from bs4 import BeautifulSoup
from typing import Dict, Any, Optional

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bdc_09_utils import (
    setup_logger,
    clean_text,
    strip_footnotes,
    parse_number,
    normalize_date,
    ARCC_CIK,
    ARCC_TICKER,
    ARCC_NAME,
)

logger = setup_logger("bdc_02_parse_financials")


def parse_balance_sheet(
    raw_dir: str = "data/raw",
    interim_dir: str = "data/interim"
) -> pd.DataFrame:
    """
    Parses the Consolidated Balance Sheet for the period specified in manifest.json.
    """
    os.makedirs(interim_dir, exist_ok=True)
    manifest_path = os.path.join(raw_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"manifest.json not found in {raw_dir}. Run bdc_01_download_filing.py first.")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    bs_fname = manifest.get("balance_sheet_report", "R2.htm")
    bs_path = os.path.join(raw_dir, bs_fname)
    primary_path = os.path.join(raw_dir, manifest.get("primary_document", "arcc-20260331.htm"))

    html_content = ""
    source_file = ""

    if os.path.exists(bs_path) and os.path.getsize(bs_path) > 0:
        logger.info(f"Reading Balance Sheet from interactive report: {bs_path}")
        with open(bs_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        source_file = bs_fname
    elif os.path.exists(primary_path) and os.path.getsize(primary_path) > 0:
        logger.info(f"Reading Balance Sheet from primary document: {primary_path}")
        with open(primary_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        source_file = os.path.basename(primary_path)
    else:
        raise FileNotFoundError(f"Neither {bs_path} nor {primary_path} found in {raw_dir}")

    soup = BeautifulSoup(html_content, "html.parser")
    table = soup.find("table")
    if not table and source_file != bs_fname:
        bs_headers = soup.find_all(string=re.compile(r"CONSOLIDATED BALANCE SHEETS", re.IGNORECASE))
        for h in bs_headers:
            t = h.find_parent("table") or h.find_next("table")
            if t:
                table = t
                break

    if not table:
        raise ValueError("Could not locate Balance Sheet table in HTML content")

    rows_data = []
    for tr in table.find_all("tr"):
        cells = [clean_text(td.get_text(separator=" ", strip=True)) for td in tr.find_all(["td", "th"])]
        if cells and any(cells):
            rows_data.append(cells)

    logger.info(f"Parsed {len(rows_data)} rows from Balance Sheet table.")

    # Extract line items (label -> first numeric value)
    line_items = {}
    for row in rows_data:
        label = clean_text(row[0])
        nums = []
        for cell in row[1:]:
            val = parse_number(cell)
            if val is not None:
                nums.append(val)
        if label and nums:
            # Preserve first occurrence to capture grand totals rather than breakdown subtotals
            if label not in line_items:
                line_items[label] = nums[0]

    # Helper function to find by keywords
    def find_val(keywords, default=None):
        for k, v in line_items.items():
            k_clean = k.lower()
            if all(kw.lower() in k_clean for kw in keywords):
                return v
        return default

    # Check for amortized cost parenthetical
    amortized_cost = None
    for label, val in line_items.items():
        cost_match = re.search(r"amortized cost of \$?\s*([0-9,]+(?:\.[0-9]+)?)", label, re.IGNORECASE)
        if cost_match:
            amortized_cost = parse_number(cost_match.group(1))
            break

    # Look in primary document or SOI if amortized cost is not in balance sheet label
    if amortized_cost is None:
        soi_path = os.path.join(raw_dir, manifest.get("soi_report", "R9.htm"))
        if os.path.exists(soi_path):
            with open(soi_path, "r", encoding="utf-8") as f:
                soi_text = f.read()
            cost_m = re.search(r"Amortized Cost[\s\S]{1,100}\$?\s*([0-9,]+\.?[0-9]*)", soi_text, re.IGNORECASE)
            if cost_m:
                amortized_cost = parse_number(cost_m.group(1))

    total_investments_fair_value = (
        find_val(["Total investments at fair value"])
        or find_val(["Investments at fair value", "Fair Value"])
        or find_val(["Fair Value"])
    )
    cash_and_cash_equivalents = find_val(["Cash and cash equivalents"]) or 0.0
    total_assets = find_val(["Total assets"])
    debt_outstanding = find_val(["Debt"]) or find_val(["Total debt"]) or 0.0
    total_liabilities = find_val(["Total liabilities"])
    net_assets = (
        find_val(["Total stockholders’ equity"])
        or find_val(["Total stockholders' equity"])
        or find_val(["Total net assets"])
        or find_val(["Net assets"])
    )

    other_assets = round(total_assets - total_investments_fair_value - cash_and_cash_equivalents, 2)
    other_liabilities = round(total_liabilities - debt_outstanding, 2)
    nav_per_share = find_val(["NET ASSET VALUE PER SHARE"]) or find_val(["Net asset value per share"])
    shares_outstanding = find_val(["common shares issued and outstanding"]) or find_val(["shares issued and outstanding"])

    fund_data = {
        "bdc_name": manifest.get("bdc_name", ARCC_NAME),
        "bdc_ticker": manifest.get("bdc_ticker", ARCC_TICKER),
        "cik": manifest.get("cik", ARCC_CIK),
        "filing_type": manifest.get("filing_type", "10-Q"),
        "fiscal_year": manifest.get("fiscal_year", 2026),
        "fiscal_quarter": manifest.get("fiscal_quarter", "Q1"),
        "period_end_date": manifest.get("period_end_date", "2026-03-31"),
        "filing_date": manifest.get("filing_date", "2026-04-28"),
        "unit": "USD_MILLIONS",  # Raw reported unit
        "total_investments_fair_value": total_investments_fair_value,
        "total_investments_amortized_cost": amortized_cost,
        "cash_and_cash_equivalents": cash_and_cash_equivalents,
        "other_assets": other_assets,
        "total_assets": total_assets,
        "debt_outstanding": debt_outstanding,
        "other_liabilities": other_liabilities,
        "total_liabilities": total_liabilities,
        "net_assets": net_assets,
        "shares_outstanding": shares_outstanding,
        "net_asset_value_per_share": nav_per_share,
    }

    df = pd.DataFrame([fund_data])
    out_path = os.path.join(interim_dir, "fund_financials_raw.csv")
    df.to_csv(out_path, index=False)
    logger.info(f"Saved raw fund financials to {out_path}")
    logger.info(f"Summary: Total Assets={total_assets}, Total Liabilities={total_liabilities}, Net Assets={net_assets}")
    return df


if __name__ == "__main__":
    parse_balance_sheet()
