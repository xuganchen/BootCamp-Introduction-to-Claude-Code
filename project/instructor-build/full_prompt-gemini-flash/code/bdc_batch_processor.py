"""
bdc_batch_processor.py - Sequential Batch Processor for Multiple Quarters.

Processes all 10-K and 10-Q filings for ARCC with period end on or after 2023-01-01,
working strictly oldest to newest.
"""

import os
import sys
import re
import json
import time
import requests
import pandas as pd
from datetime import datetime
from bs4 import BeautifulSoup
from typing import Dict, Any, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bdc_09_utils import (
    setup_logger,
    get_sec_headers,
    clean_text,
    strip_footnotes,
    parse_number,
    parse_percentage,
    normalize_date,
    parse_interest_rate_terms,
    classify_investment_category,
    STANDARD_UNIT,
    format_cik,
    ARCC_CIK,
    ARCC_TICKER,
    ARCC_NAME,
    DEFAULT_USER_AGENT,
)
from bdc_05_validate_reconcile import validate_datasets, ValidationMetrics

logger = setup_logger("bdc_batch_processor")


def get_target_filings(
    submissions_json_path: str = "data/raw/CIK0001287750.json",
    start_date: str = "2023-01-01"
) -> List[Dict[str, Any]]:
    """Loads all 10-Q and 10-K filings with reportDate >= start_date, sorted oldest to newest."""
    with open(submissions_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    recent = data["filings"]["recent"]
    filings = []
    for i in range(len(recent["form"])):
        form = recent["form"][i]
        rep_date = recent["reportDate"][i]
        fil_date = recent["filingDate"][i]
        acc = recent["accessionNumber"][i]
        doc = recent["primaryDocument"][i]

        if form in ("10-Q", "10-K") and rep_date >= start_date:
            filings.append({
                "form": form,
                "reportDate": rep_date,
                "filingDate": fil_date,
                "accessionNumber": acc,
                "primaryDocument": doc,
            })

    # Sort oldest to newest
    filings.sort(key=lambda x: (x["reportDate"], x["filingDate"]))
    return filings


def download_filing_bundle(
    filing: Dict[str, Any],
    raw_dir: str,
    headers: Dict[str, str]
) -> Dict[str, Any]:
    """Downloads necessary files for a single filing into its dedicated raw folder."""
    os.makedirs(raw_dir, exist_ok=True)
    cik_short = str(int(ARCC_CIK))
    acc_nodash = filing["accessionNumber"].replace("-", "")
    base_url = f"https://www.sec.gov/Archives/edgar/data/{cik_short}/{acc_nodash}/"

    primary_doc = filing["primaryDocument"]
    downloaded = {}

    # Download primary document & FilingSummary.xml
    for fname in [primary_doc, "FilingSummary.xml"]:
        local_path = os.path.join(raw_dir, fname)
        if not (os.path.exists(local_path) and os.path.getsize(local_path) > 0):
            time.sleep(0.12)
            resp = requests.get(base_url + fname, headers=headers, timeout=60)
            if resp.status_code == 200:
                with open(local_path, "wb") as f:
                    f.write(resp.content)
        downloaded[fname] = local_path

    # Discover reports from FilingSummary.xml
    bs_report = "R2.htm"
    soi_report = "R9.htm"
    summary_path = os.path.join(raw_dir, "FilingSummary.xml")
    if os.path.exists(summary_path):
        with open(summary_path, "r", encoding="utf-8") as f:
            xml_soup = BeautifulSoup(f.read(), "xml")
        for rep in xml_soup.find_all("Report"):
            sn = rep.find("ShortName")
            fn = rep.find("HtmlFileName")
            if sn and fn:
                sn_text = sn.text.upper()
                if "CONSOLIDATED BALANCE SHEETS" in sn_text and "PARENTHETICAL" not in sn_text:
                    bs_report = fn.text
                elif "CONSOLIDATED SCHEDULE OF INVESTMENTS" in sn_text and "PARENTHETICAL" not in sn_text:
                    soi_report = fn.text

    # Download discovered reports
    for fname in [bs_report, soi_report]:
        local_path = os.path.join(raw_dir, fname)
        if not (os.path.exists(local_path) and os.path.getsize(local_path) > 0):
            time.sleep(0.12)
            resp = requests.get(base_url + fname, headers=headers, timeout=60)
            if resp.status_code == 200:
                with open(local_path, "wb") as f:
                    f.write(resp.content)
        downloaded[fname] = local_path

    month = int(filing["reportDate"].split("-")[1])
    quarter_map = {3: "Q1", 6: "Q2", 9: "Q3", 12: "Q4"}
    fiscal_quarter = quarter_map.get(month, "Q1")
    fiscal_year = int(filing["reportDate"].split("-")[0])

    manifest = {
        "bdc_name": ARCC_NAME,
        "bdc_ticker": ARCC_TICKER,
        "cik": format_cik(ARCC_CIK),
        "filing_type": filing["form"],
        "fiscal_year": fiscal_year,
        "fiscal_quarter": fiscal_quarter,
        "period_end_date": filing["reportDate"],
        "filing_date": filing["filingDate"],
        "accession_number": filing["accessionNumber"],
        "primary_document": primary_doc,
        "balance_sheet_report": bs_report,
        "soi_report": soi_report,
        "downloaded_files": downloaded,
        "base_archive_url": base_url,
    }

    manifest_path = os.path.join(raw_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return manifest


def parse_balance_sheet_for_manifest(
    manifest: Dict[str, Any],
    raw_dir: str
) -> pd.DataFrame:
    """Parses fund balance sheet from filing artifacts."""
    bs_fname = manifest.get("balance_sheet_report", "R2.htm")
    bs_path = os.path.join(raw_dir, bs_fname)
    primary_path = os.path.join(raw_dir, manifest["primary_document"])

    if os.path.exists(bs_path) and os.path.getsize(bs_path) > 0:
        with open(bs_path, "r", encoding="utf-8") as f:
            html = f.read()
    else:
        with open(primary_path, "r", encoding="utf-8") as f:
            html = f.read()

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        bs_headers = soup.find_all(string=re.compile(r"CONSOLIDATED BALANCE SHEETS", re.IGNORECASE))
        for h in bs_headers:
            t = h.find_parent("table") or h.find_next("table")
            if t:
                table = t
                break

    rows_data = []
    for tr in table.find_all("tr"):
        cells = [clean_text(td.get_text(separator=" ", strip=True)) for td in tr.find_all(["td", "th"])]
        if cells and any(cells):
            rows_data.append(cells)

    line_items = {}
    for row in rows_data:
        label = clean_text(row[0])
        nums = []
        for cell in row[1:]:
            val = parse_number(cell)
            if val is not None:
                nums.append(val)
        if label and nums and label not in line_items:
            line_items[label] = nums[0]

    def find_val(keywords, default=None):
        for k, v in line_items.items():
            k_clean = k.lower()
            if all(kw.lower() in k_clean for kw in keywords):
                return v
        return default

    # Amortized cost
    amortized_cost = None
    for label, val in line_items.items():
        cost_match = re.search(r"amortized cost of \$?\s*([0-9,]+(?:\.[0-9]+)?)", label, re.IGNORECASE)
        if cost_match:
            amortized_cost = parse_number(cost_match.group(1))
            break

    total_inv_fv = (
        find_val(["Total investments at fair value"])
        or find_val(["Investments at fair value", "Fair Value"])
        or find_val(["Fair Value"])
    )
    cash = find_val(["Cash and cash equivalents"]) or 0.0
    total_assets = find_val(["Total assets"])
    debt = find_val(["Debt"]) or find_val(["Total debt"]) or 0.0
    total_liabilities = find_val(["Total liabilities"])
    net_assets = (
        find_val(["Total stockholders’ equity"])
        or find_val(["Total stockholders' equity"])
        or find_val(["Total net assets"])
        or find_val(["Net assets"])
    )
    nav_per_share = find_val(["NET ASSET VALUE PER SHARE"]) or find_val(["Net asset value per share"])
    shares_out = find_val(["common shares issued and outstanding"]) or find_val(["shares issued and outstanding"])

    # Standardize to USD_THOUSANDS (* 1000)
    total_inv_fv_th = round(float(total_inv_fv) * 1000.0, 2)
    total_inv_cost_th = round(float(amortized_cost) * 1000.0, 2) if amortized_cost is not None else None
    cash_th = round(float(cash) * 1000.0, 2)
    total_assets_th = round(float(total_assets) * 1000.0, 2)
    debt_th = round(float(debt) * 1000.0, 2)
    total_liab_th = round(float(total_liabilities) * 1000.0, 2)
    net_assets_th = round(float(net_assets) * 1000.0, 2)

    other_assets_th = round(total_assets_th - total_inv_fv_th - cash_th, 2)
    other_liab_th = round(total_liab_th - debt_th, 2)
    shares_out_th = round(float(shares_out) * 1000.0, 2) if shares_out is not None else None

    clean_fund = {
        "bdc_name": manifest["bdc_name"],
        "bdc_ticker": manifest["bdc_ticker"],
        "cik": manifest["cik"],
        "filing_type": manifest["filing_type"],
        "fiscal_year": manifest["fiscal_year"],
        "fiscal_quarter": manifest["fiscal_quarter"],
        "period_end_date": manifest["period_end_date"],
        "filing_date": manifest["filing_date"],
        "unit": STANDARD_UNIT,
        "total_investments_fair_value": total_inv_fv_th,
        "total_investments_amortized_cost": total_inv_cost_th,
        "cash_and_cash_equivalents": cash_th,
        "other_assets": other_assets_th,
        "total_assets": total_assets_th,
        "debt_outstanding": debt_th,
        "other_liabilities": other_liab_th,
        "total_liabilities": total_liab_th,
        "net_assets": net_assets_th,
        "shares_outstanding": shares_out_th,
        "net_asset_value_per_share": round(float(nav_per_share), 4) if nav_per_share is not None else None,
    }
    return pd.DataFrame([clean_fund])


def parse_soi_for_manifest(
    manifest: Dict[str, Any],
    raw_dir: str
) -> pd.DataFrame:
    """Parses SOI positions from filing artifacts."""
    primary_path = os.path.join(raw_dir, manifest["primary_document"])
    with open(primary_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Find SOI start: preceding <table before 'Company (1)' or 'Company'
    first_match = html.find("Company (1)")
    if first_match == -1:
        first_match = html.find("Company")
    soi_start = html.rfind("<table", 0, first_match)
    if soi_start == -1:
        soi_start = max(0, first_match - 2000)

    # Locate prior period boundary (e.g. As of December...)
    prior_match = html.find("As of December", first_match + 50000)
    if prior_match == -1:
        prior_match = html.find("December 31,", first_match + 50000)
    if prior_match == -1:
        prior_match = len(html)

    soi_html = html[soi_start:prior_match]
    soup = BeautifulSoup(soi_html, "html.parser")
    all_tables = soup.find_all("table")

    # Stop at Total Investments
    end_table_idx = len(all_tables)
    for t_idx, t in enumerate(all_tables):
        if "Total Investments" in t.get_text():
            end_table_idx = t_idx + 1
            break

    soi_tables = all_tables[0:end_table_idx]

    positions = []
    current_industry = ""
    current_company = ""
    current_desc = ""

    for t_idx, t in enumerate(soi_tables):
        trs = t.find_all("tr")
        for r_idx, tr in enumerate(trs):
            tds = tr.find_all(["td", "th"])
            cell_texts = [clean_text(td.get_text(separator=" ", strip=True)) for td in tds]
            non_empty = [(i, txt) for i, txt in enumerate(cell_texts) if txt and txt not in ("$", "%")]
            if not non_empty:
                continue

            row_str = " | ".join([txt for _, txt in non_empty])
            if "Company (1)" in row_str or "Business Description" in row_str or "Total Investments" in row_str:
                continue
            if len(non_empty) == 1 and not any(c.isdigit() for c in non_empty[0][1]) and "Total" not in non_empty[0][1]:
                current_industry = non_empty[0][1]
                continue
            if "Total" in row_str:
                continue
            if len(non_empty) <= 3 and all(parse_number(txt) is not None for _, txt in non_empty):
                continue

            if len(tds) > 0 and cell_texts[0]:
                current_company = cell_texts[0]
                if len(tds) > 2 and cell_texts[2]:
                    current_desc = cell_texts[2]

            inv_type = cell_texts[4] if len(tds) > 4 and cell_texts[4] else "Investment Position"
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

            if len(tds) >= 25 and cell_texts[15] == "$":
                principal_raw = cell_texts[16]
                cost_raw = cell_texts[20]
                fv_raw = cell_texts[24]
            elif len(tds) >= 22 and cell_texts[15] and (cell_texts[18] or cell_texts[21]):
                principal_raw = cell_texts[15]
                cost_raw = cell_texts[18]
                fv_raw = cell_texts[21]
            elif len(tds) >= 21 and (cell_texts[17] or cell_texts[20]):
                cost_raw = cell_texts[17]
                fv_raw = cell_texts[20]

            fv_num = parse_number(fv_raw)
            if fv_num is None:
                cost_num = parse_number(cost_raw)
                if cost_num is not None:
                    fv_raw = cost_raw
                    fv_num = cost_num

            if fv_num is not None:
                borrower_clean = strip_footnotes(current_company)
                if not borrower_clean:
                    continue

                category = classify_investment_category(inv_type)
                rate_info = parse_interest_rate_terms(
                    coupon_raw=coupon_raw,
                    reference_raw=ref_raw,
                    spread_raw=spread_raw,
                    investment_type_raw=inv_type,
                )

                pr_num = parse_number(principal_raw)
                cost_num = parse_number(cost_raw)
                pct_num = parse_percentage(pct_raw)

                clean_pos = {
                    "bdc_name": manifest["bdc_name"],
                    "bdc_ticker": manifest["bdc_ticker"],
                    "cik": manifest["cik"],
                    "period_end_date": manifest["period_end_date"],
                    "filing_date": manifest["filing_date"],
                    "borrower_name": borrower_clean,
                    "industry": current_industry if current_industry else None,
                    "investment_category": category,
                    "investment_type": inv_type,
                    "interest_rate_type": rate_info["interest_rate_type"],
                    "reference_rate": rate_info["reference_rate"],
                    "spread_bps": rate_info["spread_bps"],
                    "interest_floor_pct": rate_info["interest_floor_pct"],
                    "total_coupon_rate_pct": rate_info["total_coupon_rate_pct"],
                    "is_pik": rate_info["is_pik"],
                    "is_non_accrual": rate_info["is_non_accrual"],
                    "maturity_date": normalize_date(mat_raw),
                    "unit": STANDARD_UNIT,
                    "principal_amount": round(pr_num * 1000.0, 2) if pr_num is not None else None,
                    "amortized_cost": round(cost_num * 1000.0, 2) if cost_num is not None else None,
                    "fair_value": round(fv_num * 1000.0, 2),
                    "pct_of_net_assets": round(pct_num, 4) if pct_num is not None else None,
                }
                positions.append(clean_pos)

    return pd.DataFrame(positions)


def run_batch():
    headers = get_sec_headers(DEFAULT_USER_AGENT)
    filings = get_target_filings()
    logger.info(f"Loaded {len(filings)} filings for ARCC >= 2023-01-01. Processing oldest to newest...")

    results = []
    all_fund_dfs = []
    all_inv_dfs = []

    for idx, f in enumerate(filings, 1):
        period = f["reportDate"]
        form = f["form"]
        filing_date = f["filingDate"]
        logger.info(f"\n[{idx}/{len(filings)}] Processing {form} for Period: {period} (Filed: {filing_date})...")

        raw_dir = os.path.join("data", "raw", period)
        interim_dir = os.path.join("data", "interim", period)
        os.makedirs(raw_dir, exist_ok=True)
        os.makedirs(interim_dir, exist_ok=True)

        res_entry = {
            "index": idx,
            "period_end_date": period,
            "form": form,
            "filing_date": filing_date,
            "status": "FAIL",
            "fund_rows": 0,
            "investment_rows": 0,
            "unique_borrowers": 0,
            "fund_fv_thousands": 0.0,
            "soi_fv_thousands": 0.0,
            "diff_thousands": 0.0,
            "diff_pct": 0.0,
            "accounting_diff": 0.0,
            "errors": [],
        }

        try:
            # 1. Download
            manifest = download_filing_bundle(f, raw_dir, headers)

            # 2. Parse Fund Financials
            fund_df = parse_balance_sheet_for_manifest(manifest, raw_dir)
            fund_df.to_csv(os.path.join(interim_dir, "bdc_fund_clean.csv"), index=False)

            # 3. Parse SOI Positions
            inv_df = parse_soi_for_manifest(manifest, raw_dir)
            inv_df.to_csv(os.path.join(interim_dir, "bdc_investment_clean.csv"), index=False)

            # 4. Validate & Reconcile
            is_valid, metrics = validate_datasets(fund_df, inv_df)

            res_entry["fund_rows"] = len(fund_df)
            res_entry["investment_rows"] = len(inv_df)
            res_entry["unique_borrowers"] = metrics.unique_borrowers
            res_entry["fund_fv_thousands"] = metrics.fund_total_investments_fair_value
            res_entry["soi_fv_thousands"] = metrics.investment_sum_fair_value
            res_entry["diff_thousands"] = metrics.fair_value_abs_diff
            res_entry["diff_pct"] = metrics.fair_value_rel_diff_pct
            res_entry["accounting_diff"] = metrics.accounting_identity_diff
            res_entry["errors"] = metrics.errors

            if is_valid:
                res_entry["status"] = "PASS"
                all_fund_dfs.append(fund_df)
                all_inv_dfs.append(inv_df)
                logger.info(f"-> PASS: Diff = ${metrics.fair_value_abs_diff:,.2f} ({metrics.fair_value_rel_diff_pct:.4f}%), Positions = {len(inv_df)}, Borrowers = {metrics.unique_borrowers}")
            else:
                res_entry["status"] = "FAIL"
                logger.error(f"-> FAIL: Errors: {metrics.errors}")

        except Exception as e:
            res_entry["status"] = "ERROR"
            res_entry["errors"].append(str(e))
            logger.error(f"-> ERROR processing {period}: {e}")

        results.append(res_entry)

    # Save Batch Execution Summary to note/
    summary_path = os.path.join("note", "batch_processing_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    logger.info("\n" + "=" * 70)
    logger.info("BATCH PROCESSING COMPLETED")
    logger.info("=" * 70)

    return results, all_fund_dfs, all_inv_dfs


if __name__ == "__main__":
    run_batch()
