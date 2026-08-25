"""
bdc_01_download_filing.py - SEC EDGAR Filing Downloader for Ares Capital Corporation (ARCC).

Queries the SEC EDGAR Submissions API for ARCC, locates the most recent 10-Q (or 10-K) filing,
downloads the primary HTML document, XBRL interactive reports (Balance Sheet R2.htm, SOI R9.htm),
and saves everything into data/raw/ along with manifest.json.
"""

import os
import sys
import json
import time
import requests
from typing import Dict, Any, Optional

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bdc_09_utils import (
    setup_logger,
    get_sec_headers,
    format_cik,
    ARCC_CIK,
    ARCC_TICKER,
    ARCC_NAME,
    DEFAULT_USER_AGENT,
)

logger = setup_logger("bdc_01_download_filing")


import argparse

def download_filing_for_bdc(
    cik: str = ARCC_CIK,
    ticker: str = ARCC_TICKER,
    name: str = ARCC_NAME,
    target_period: Optional[str] = None,
    user_agent: str = DEFAULT_USER_AGENT,
    target_dir: str = "data/raw"
) -> Dict[str, Any]:
    """
    Downloads the 10-Q or 10-K filing for the given BDC and target period (or latest if None).
    """
    os.makedirs(target_dir, exist_ok=True)
    cik_10 = format_cik(cik)
    cik_short = str(int(cik_10))
    headers = get_sec_headers(user_agent)

    logger.info(f"Querying SEC EDGAR Submissions for {name} ({ticker}, CIK: {cik_10})...")
    submissions_url = f"https://data.sec.gov/submissions/CIK{cik_10}.json"

    # Fetch submissions JSON
    try:
        resp = requests.get(submissions_url, headers=headers, timeout=30)
        resp.raise_for_status()
        sub_data = resp.json()
    except Exception as e:
        logger.error(f"Failed to query SEC submissions at {submissions_url}: {e}")
        local_sub_path = os.path.join(target_dir, f"CIK{cik_10}.json")
        if os.path.exists(local_sub_path):
            logger.info(f"Loading local cached submissions file: {local_sub_path}")
            with open(local_sub_path, "r", encoding="utf-8") as f:
                sub_data = json.load(f)
        else:
            raise

    # Save submissions json
    sub_save_path = os.path.join(target_dir, f"CIK{cik_10}.json")
    with open(sub_save_path, "w", encoding="utf-8") as f:
        json.dump(sub_data, f, indent=2)

    recent = sub_data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])
    accession_numbers = recent.get("accessionNumber", [])
    primary_documents = recent.get("primaryDocument", [])

    # Find the target 10-Q or 10-K
    target_idx = None
    for i, form in enumerate(forms):
        if form in ("10-Q", "10-K"):
            if target_period:
                if report_dates[i] == target_period:
                    target_idx = i
                    break
            else:
                target_idx = i
                break

    if target_idx is None:
        raise RuntimeError(f"No matching 10-Q or 10-K filing found for CIK {cik_10} (target_period: {target_period})")

    form_type = forms[target_idx]
    filing_date = filing_dates[target_idx]
    report_date = report_dates[target_idx]
    accession_number = accession_numbers[target_idx]
    accession_nodash = accession_number.replace("-", "")
    primary_doc = primary_documents[target_idx]

    logger.info(
        f"Selected filing: Form {form_type}, Period End: {report_date}, "
        f"Filing Date: {filing_date}, Accession: {accession_number}, Primary Doc: {primary_doc}"
    )

    base_archive_url = f"https://www.sec.gov/Archives/edgar/data/{cik_short}/{accession_nodash}/"
    downloaded_files = {}

    # 1. Download primary document and FilingSummary.xml first
    initial_files = [primary_doc, "FilingSummary.xml"]
    for fname in initial_files:
        local_path = os.path.join(target_dir, fname)
        if not (os.path.exists(local_path) and os.path.getsize(local_path) > 0):
            file_url = base_archive_url + fname
            logger.info(f"Downloading {file_url} -> {local_path}...")
            time.sleep(0.1)
            fresp = requests.get(file_url, headers=headers, timeout=60)
            if fresp.status_code == 200:
                with open(local_path, "wb") as f:
                    f.write(fresp.content)
                logger.info(f"Saved {fname} ({len(fresp.content)} bytes)")
            else:
                logger.warning(f"File {fname} returned status code {fresp.status_code}")
        downloaded_files[fname] = local_path

    # 2. Parse FilingSummary.xml to discover Balance Sheet and SOI report files dynamically
    bs_report = "R2.htm"
    soi_report = "R9.htm"
    summary_path = os.path.join(target_dir, "FilingSummary.xml")
    if os.path.exists(summary_path):
        from bs4 import BeautifulSoup
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

    logger.info(f"Dynamic Report Mapping: Balance Sheet={bs_report}, SOI={soi_report}")

    for fname in [bs_report, soi_report]:
        local_path = os.path.join(target_dir, fname)
        if not (os.path.exists(local_path) and os.path.getsize(local_path) > 0):
            file_url = base_archive_url + fname
            logger.info(f"Downloading {file_url} -> {local_path}...")
            time.sleep(0.1)
            fresp = requests.get(file_url, headers=headers, timeout=60)
            if fresp.status_code == 200:
                with open(local_path, "wb") as f:
                    f.write(fresp.content)
                logger.info(f"Saved {fname} ({len(fresp.content)} bytes)")
        downloaded_files[fname] = local_path

    # Determine fiscal quarter from report_date
    month = int(report_date.split("-")[1])
    quarter_map = {3: "Q1", 6: "Q2", 9: "Q3", 12: "Q4"}
    fiscal_quarter = quarter_map.get(month, "Q1")
    fiscal_year = int(report_date.split("-")[0])

    manifest = {
        "bdc_name": name,
        "bdc_ticker": ticker,
        "cik": cik_10,
        "filing_type": form_type,
        "fiscal_year": fiscal_year,
        "fiscal_quarter": fiscal_quarter,
        "period_end_date": report_date,
        "filing_date": filing_date,
        "accession_number": accession_number,
        "primary_document": primary_doc,
        "balance_sheet_report": bs_report,
        "soi_report": soi_report,
        "downloaded_files": downloaded_files,
        "base_archive_url": base_archive_url,
    }

    manifest_path = os.path.join(target_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    logger.info(f"Saved manifest to {manifest_path}")

    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download SEC filings for BDC.")
    parser.add_argument("--period", type=str, default=None, help="Target reporting period end (YYYY-MM-DD), e.g. 2026-03-31")
    args = parser.parse_args()
    download_filing_for_bdc(target_period=args.period)
