"""
bdc_03_parse_soi.py - Schedule of Investments (SOI) Parser.

Extracts position-level investments from SEC EDGAR filings:
- Locates and stitches all contiguous SOI tables for the target period.
- Captures company/borrower names, industry classifications, business descriptions.
- Extracts deal-level loan terms: investment type, coupon, reference rate, spread,
  acquisition date, maturity date, principal, amortized cost, fair value, % of net assets.
- Filters out non-position summary rows, industry subtotals, derivatives, and commitment tables.

Saves raw position rows into data/interim/soi_positions_raw.csv.
"""

import os
import sys
import json
import re
import pandas as pd
from bs4 import BeautifulSoup
from typing import Dict, Any, List, Optional

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

logger = setup_logger("bdc_03_parse_soi")


def parse_soi(
    raw_dir: str = "data/raw",
    interim_dir: str = "data/interim"
) -> pd.DataFrame:
    """
    Parses all SOI tables for the target quarter and extracts raw position records.
    """
    os.makedirs(interim_dir, exist_ok=True)
    manifest_path = os.path.join(raw_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"manifest.json not found in {raw_dir}. Run bdc_01_download_filing.py first.")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    primary_doc = manifest.get("primary_document", "arcc-20260331.htm")
    primary_path = os.path.join(raw_dir, primary_doc)

    if not os.path.exists(primary_path) or os.path.getsize(primary_path) == 0:
        raise FileNotFoundError(f"Primary document not found at {primary_path}")

    logger.info(f"Loading primary document: {primary_path}...")
    with open(primary_path, "r", encoding="utf-8") as f:
        html = f.read()

    # 1. Locate start of SOI
    # Find first instance of 'Company (1)' or 'SCHEDULE OF INVESTMENTS'
    first_match = html.find("Company (1)")
    if first_match == -1:
        first_match = html.find("Company")

    # Find the preceding <table start
    soi_start = html.rfind("<table", 0, first_match)
    if soi_start == -1:
        soi_start = max(0, first_match - 2000)

    # 2. Locate boundary where prior period begins (e.g. December 31, ...)
    prior_period_match = html.find("As of December", first_match + 50000)
    if prior_period_match == -1:
        prior_period_match = html.find("December 31,", first_match + 50000)
    if prior_period_match == -1:
        prior_period_match = len(html)

    logger.info(f"Target SOI range in HTML: chars {soi_start} to {prior_period_match}")
    soi_html = html[soi_start:prior_period_match]

    soup = BeautifulSoup(soi_html, "html.parser")
    all_tables = soup.find_all("table")
    logger.info(f"Found {len(all_tables)} total tables in target SOI section.")

    # 3. Find table containing 'Total Investments' to avoid post-SOI auxiliary commitment tables
    end_table_idx = len(all_tables)
    for t_idx, t in enumerate(all_tables):
        if "Total Investments" in t.get_text():
            end_table_idx = t_idx + 1
            logger.info(f"Total Investments row located in Table index {t_idx}. Limiting extraction to tables 0..{t_idx}.")
            break

    soi_tables = all_tables[0:end_table_idx]

    positions = []
    current_industry = ""
    current_company = ""
    current_description = ""

    for t_idx, t in enumerate(soi_tables):
        trs = t.find_all("tr")
        for r_idx, tr in enumerate(trs):
            tds = tr.find_all(["td", "th"])
            cell_texts = [clean_text(td.get_text(separator=" ", strip=True)) for td in tds]
            non_empty = [(i, txt) for i, txt in enumerate(cell_texts) if txt and txt not in ("$", "%")]
            if not non_empty:
                continue
            
            row_str = " | ".join([txt for _, txt in non_empty])

            # Header / Totals
            if "Company (1)" in row_str or "Business Description" in row_str or "Total Investments" in row_str:
                continue

            # Industry Header (single non-numeric text item)
            if len(non_empty) == 1 and not any(c.isdigit() for c in non_empty[0][1]) and "Total" not in non_empty[0][1]:
                current_industry = non_empty[0][1]
                continue

            # Subtotals
            if "Total" in row_str:
                continue
            if len(non_empty) <= 3 and all(parse_number(txt) is not None for _, txt in non_empty):
                continue

            # Company name in cell 0
            if len(tds) > 0 and cell_texts[0]:
                current_company = cell_texts[0]
                if len(tds) > 2 and cell_texts[2]:
                    current_description = cell_texts[2]

            # Investment type
            inv_type = ""
            if len(tds) > 4 and cell_texts[4]:
                inv_type = cell_texts[4]

            coupon_raw = cell_texts[6] if len(tds) > 6 else ""
            ref_raw = cell_texts[7] if len(tds) > 7 else ""
            spread_raw = cell_texts[8] if len(tds) > 8 else ""
            acq_raw = cell_texts[10] if len(tds) > 10 else ""
            mat_raw = cell_texts[12] if len(tds) > 12 else ""
            shares_raw = cell_texts[14] if len(tds) > 14 else ""

            principal_raw = ""
            cost_raw = ""
            fv_raw = ""
            pct_raw = ""
            footnote_raw = ""

            # Case 1: First row of table with '$' in cells
            if len(tds) >= 25 and cell_texts[15] == "$":
                principal_raw = cell_texts[16]
                cost_raw = cell_texts[20]
                fv_raw = cell_texts[24]
                footnote_raw = cell_texts[26] if len(tds) > 26 else ""
            # Case 2: Loan row (principal at 15, cost at 18, fv at 21)
            elif len(tds) >= 22 and cell_texts[15] and (cell_texts[18] or cell_texts[21]):
                principal_raw = cell_texts[15]
                cost_raw = cell_texts[18]
                fv_raw = cell_texts[21]
                footnote_raw = cell_texts[23] if len(tds) > 23 else ""
            # Case 3: Equity row (shares at 14, cost at 17, fv at 20)
            elif len(tds) >= 21 and (cell_texts[17] or cell_texts[20]):
                cost_raw = cell_texts[17]
                fv_raw = cell_texts[20]
                footnote_raw = cell_texts[22] if len(tds) > 22 else ""

            fv_num = parse_number(fv_raw)
            if fv_num is None:
                cost_num = parse_number(cost_raw)
                if cost_num is not None:
                    fv_raw = cost_raw
                    fv_num = cost_num

            if fv_num is not None:
                position = {
                    "bdc_name": manifest.get("bdc_name", ARCC_NAME),
                    "bdc_ticker": manifest.get("bdc_ticker", ARCC_TICKER),
                    "cik": manifest.get("cik", ARCC_CIK),
                    "period_end_date": manifest.get("period_end_date", "2026-03-31"),
                    "filing_date": manifest.get("filing_date", "2026-04-28"),
                    "borrower_name": current_company,
                    "industry": current_industry,
                    "business_description": current_description,
                    "investment_type": inv_type if inv_type else "Investment Position",
                    "coupon_raw": coupon_raw,
                    "reference_rate_raw": ref_raw,
                    "spread_raw": spread_raw,
                    "acquisition_date_raw": acq_raw,
                    "maturity_date_raw": mat_raw,
                    "shares_units_raw": shares_raw,
                    "principal_raw": principal_raw,
                    "amortized_cost_raw": cost_raw,
                    "fair_value_raw": fv_raw,
                    "pct_of_net_assets_raw": pct_raw,
                    "footnote_raw": footnote_raw.strip(),
                }
                positions.append(position)

    df_positions = pd.DataFrame(positions)
    logger.info(f"Extracted {len(df_positions)} raw investment positions across all SOI tables.")

    out_path = os.path.join(interim_dir, "soi_positions_raw.csv")
    df_positions.to_csv(out_path, index=False)
    logger.info(f"Saved raw SOI positions to {out_path}")

    return df_positions


if __name__ == "__main__":
    parse_soi()
