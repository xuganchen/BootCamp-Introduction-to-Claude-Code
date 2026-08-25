"""
bdc_09_utils.py - Reusable utilities for SEC EDGAR BDC Data Pipeline.

This module provides common utilities for:
- SEC EDGAR HTTP client with compliant rate limiting and headers
- Robust numeric parsing (negative parentheses, footnotes, currency symbols, em-dashes)
- Date normalization and ISO formatting (YYYY-MM-DD)
- Interest rate terms parsing (reference rates, spreads, PIK flags, floor rates)
- Investment asset categorization
- Centralized structured logging
"""

import re
import logging
import datetime
from typing import Any, Optional, Dict, Tuple, Union

# ----------------------------------------------------------------------
# SEC EDGAR Constants & Defaults
# ----------------------------------------------------------------------
DEFAULT_USER_AGENT = "BDCResearcher research@example.com"
ARCC_CIK = "0001287750"
ARCC_TICKER = "ARCC"
ARCC_NAME = "Ares Capital Corporation"

SEC_SUBMISSIONS_URL_TEMPLATE = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVE_URL_TEMPLATE = "https://www.sec.gov/Archives/edgar/data/{cik_short}/{accession_nodash}/{filename}"

# Standard unit for cleaned datasets
STANDARD_UNIT = "USD_THOUSANDS"


# ----------------------------------------------------------------------
# Structured Logger Setup
# ----------------------------------------------------------------------
def setup_logger(name: str = "bdc_pipeline", level: int = logging.INFO) -> logging.Logger:
    """Configures and returns a structured logger."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(level)
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


logger = setup_logger("bdc_09_utils")


# ----------------------------------------------------------------------
# SEC Client Headers
# ----------------------------------------------------------------------
def get_sec_headers(user_agent: str = DEFAULT_USER_AGENT) -> Dict[str, str]:
    """Returns compliant SEC EDGAR request headers."""
    return {
        "User-Agent": user_agent,
        "Accept-Encoding": "gzip, deflate",
        "Accept": "application/json, text/html, application/xhtml+xml, */*"
    }


def format_cik(cik: Union[str, int]) -> str:
    """Zero-pads CIK to 10 digits."""
    clean_cik = str(cik).strip().lstrip("0")
    if not clean_cik:
        clean_cik = "0"
    return clean_cik.zfill(10)


# ----------------------------------------------------------------------
# Text & Footnote Cleaning Utilities
# ----------------------------------------------------------------------
def clean_text(val: Any) -> str:
    """Normalizes whitespace and removes special unicode spacing characters."""
    if val is None:
        return ""
    text = str(val)
    # Replace non-breaking spaces and other whitespace variants
    text = text.replace("\xa0", " ").replace("&nbsp;", " ").replace("&#160;", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def strip_footnotes(text: str) -> str:
    """
    Removes footnote references like (1), (2)(9), [1], (13)(14), (Note 7) from strings.
    Preserves valid corporate identifiers like (BVI), (UK), (Canada), (USD).
    """
    if not text:
        return ""
    # Strip bracketed numbers: [1], [2]
    cleaned = re.sub(r"\[\d+\]", "", text)
    # Strip footnote number patterns like (1), (2)(9), (13)(14), (1)(6)(9)
    cleaned = re.sub(r"\((?:\d+(?:,\s*|\s*|\)\())*\d+\)", "", cleaned)
    # Strip Note references: (Note 7), (Note 2)
    cleaned = re.sub(r"\(Note\s+\d+\)", "", cleaned, flags=re.IGNORECASE)
    return clean_text(cleaned)


# ----------------------------------------------------------------------
# Numeric Parsing Utilities
# ----------------------------------------------------------------------
def parse_number(val: Any, default: Optional[float] = None) -> Optional[float]:
    """
    Parses a string or numeric value into a float.
    Handles:
    - Currency signs: $
    - Commas: 1,234.56
    - Parentheses for negative numbers: (5.3) -> -5.3
    - Em-dashes / en-dashes / hyphens for 0 or null: '—', '-', '–' -> 0.0
    - Footnote markers: '(2)(9)', '[1]'
    - Percent signs: '8.65 %' -> 8.65
    """
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)

    text = clean_text(val)
    if not text:
        return default

    # Check for dash representations of 0 / nil
    if text in ("—", "–", "-", "--", "N/A", "n/a", "None", "null", "•"):
        return 0.0

    # Strip bracketed and parenthetical footnote tags if they are at the end
    text = re.sub(r"\[\d+\]", "", text)
    text = re.sub(r"\(\d+\)", "", text)
    text = text.replace("$", "").replace("%", "").replace(",", "").strip()

    # Check for negative numbers in parentheses: ( 5.3 ) -> -5.3
    neg_match = re.match(r"^\(\s*([0-9.]+)\s*\)$", text)
    if neg_match:
        try:
            return -float(neg_match.group(1))
        except ValueError:
            return default

    # Plain float parsing
    try:
        return float(text)
    except ValueError:
        match = re.search(r"[-+]?\d*\.?\d+", text)
        if match:
            try:
                num = float(match.group(0))
                if "(" in text and ")" in text and not text.startswith("-"):
                    num = -num
                return num
            except ValueError:
                return default
        return default


def parse_percentage(val: Any, default: Optional[float] = None) -> Optional[float]:
    """Parses a percentage string into a float representing percentage points (e.g. '8.65 %' -> 8.65)."""
    return parse_number(val, default=default)


# ----------------------------------------------------------------------
# Date Parsing & Normalization
# ----------------------------------------------------------------------
def normalize_date(val: Any) -> Optional[str]:
    """
    Normalizes various date formats into standard ISO string 'YYYY-MM-DD'.
    Handles:
    - 'June 30, 2026' -> '2026-06-30'
    - '2026-06-30'    -> '2026-06-30'
    - '06/30/2026'    -> '2026-06-30'
    - '06/2026'       -> '2026-06-01' (month-level dates default to 1st of month)
    - '11/2028'       -> '2028-11-01'
    """
    if val is None:
        return None
    text = clean_text(val)
    if not text or text in ("—", "–", "-", "N/A", "n/a"):
        return None

    # Strip footnotes from date text: '11/2028 (2)' -> '11/2028'
    text = strip_footnotes(text)

    # Format: YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return text

    # Format: Month DD, YYYY (e.g., June 30, 2026)
    try:
        dt = datetime.datetime.strptime(text, "%B %d, %Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass

    try:
        dt = datetime.datetime.strptime(text, "%b %d, %Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass

    # Format: MM/DD/YYYY
    try:
        dt = datetime.datetime.strptime(text, "%m/%d/%Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass

    # Format: MM/YYYY (common in Schedule of Investments) -> YYYY-MM-01
    try:
        dt = datetime.datetime.strptime(text, "%m/%Y")
        return dt.strftime("%Y-%m-01")
    except ValueError:
        pass

    # Format: Month YYYY (e.g. June 2026) -> YYYY-MM-01
    try:
        dt = datetime.datetime.strptime(text, "%B %Y")
        return dt.strftime("%Y-%m-01")
    except ValueError:
        pass

    return None


# ----------------------------------------------------------------------
# Interest Rate Term Parsing
# ----------------------------------------------------------------------
def parse_interest_rate_terms(
    coupon_raw: Any,
    reference_raw: Any = "",
    spread_raw: Any = "",
    investment_type_raw: Any = "",
    footnote_raw: Any = ""
) -> Dict[str, Any]:
    """
    Extracts structured interest rate terms from raw text fields:
    - total_coupon_rate_pct: float
    - reference_rate: str ('SOFR', 'SONIA', 'NIBOR', 'Base Rate', etc.)
    - spread_bps: float (e.g., 500.0 for 5.00%)
    - interest_floor_pct: float
    - is_pik: bool
    - is_non_accrual: bool
    - interest_rate_type: 'Floating', 'Fixed', or None
    """
    coupon_str = clean_text(coupon_raw)
    ref_str = clean_text(reference_raw)
    spread_str = clean_text(spread_raw)
    inv_type_str = clean_text(investment_type_raw)
    fn_str = clean_text(footnote_raw)

    combined_text = f"{coupon_str} {ref_str} {spread_str} {inv_type_str} {fn_str}".upper()

    # 1. PIK Toggle
    is_pik = "PIK" in combined_text

    # 2. Non-Accrual Status
    is_non_accrual = "NON-ACCRUAL" in combined_text or "NON ACCRUAL" in combined_text

    # 3. Reference Rate
    reference_rate = None
    if ref_str:
        ref_upper = ref_str.upper()
        if "SOFR" in ref_upper:
            reference_rate = "SOFR"
        elif "SONIA" in ref_upper:
            reference_rate = "SONIA"
        elif "EURIBOR" in ref_upper:
            reference_rate = "EURIBOR"
        elif "NIBOR" in ref_upper:
            reference_rate = "NIBOR"
        elif "BASE RATE" in ref_upper or "PRIME" in ref_upper:
            reference_rate = "Base Rate"
        elif "LIBOR" in ref_upper:
            reference_rate = "LIBOR"
        elif "STIBOR" in ref_upper:
            reference_rate = "STIBOR"
        elif "CDOR" in ref_upper:
            reference_rate = "CDOR"
        else:
            reference_rate = strip_footnotes(ref_str)

    # 4. Spread (in basis points)
    spread_bps = None
    if spread_str:
        spread_val = parse_number(spread_str)
        if spread_val is not None:
            if spread_val < 100:
                spread_bps = round(spread_val * 100.0, 2)
            else:
                spread_bps = round(spread_val, 2)

    # 5. Total Coupon Rate (%)
    total_coupon_rate_pct = None
    if coupon_str:
        coupon_match = re.search(r"(\d+\.?\d*)\s*%", coupon_str)
        if coupon_match:
            total_coupon_rate_pct = float(coupon_match.group(1))
        else:
            coupon_val = parse_number(coupon_str)
            if coupon_val is not None and coupon_val > 0:
                total_coupon_rate_pct = coupon_val

    # 6. Interest Floor (%)
    interest_floor_pct = None
    floor_match = re.search(r"FLOOR\s*(?:OF|:)?\s*(\d+\.?\d*)\s*%", combined_text)
    if floor_match:
        interest_floor_pct = float(floor_match.group(1))

    # 7. Interest Rate Type: Floating vs Fixed
    interest_rate_type = None
    if reference_rate or (spread_bps is not None and spread_bps > 0):
        interest_rate_type = "Floating"
    elif total_coupon_rate_pct is not None and total_coupon_rate_pct > 0:
        interest_rate_type = "Fixed"
    elif any(k in inv_type_str.lower() for k in ["loan", "note", "debt", "bond", "subordinated"]):
        if total_coupon_rate_pct is not None:
            interest_rate_type = "Fixed"

    return {
        "total_coupon_rate_pct": total_coupon_rate_pct,
        "reference_rate": reference_rate,
        "spread_bps": spread_bps,
        "interest_floor_pct": interest_floor_pct,
        "is_pik": is_pik,
        "is_non_accrual": is_non_accrual,
        "interest_rate_type": interest_rate_type,
    }


# ----------------------------------------------------------------------
# Investment Asset Categorization
# ----------------------------------------------------------------------
def classify_investment_category(investment_type: str) -> str:
    """
    Classifies investment description into standardized high-level asset category:
    - First Lien Senior Secured
    - Second Lien
    - Subordinated Debt
    - Preferred Equity
    - Common Equity
    - Warrants
    - Other
    """
    if not investment_type:
        return "Other"
    inv_lower = investment_type.lower()

    if "first lien" in inv_lower or "1st lien" in inv_lower or "senior secured loan" in inv_lower or "revolving loan" in inv_lower:
        return "First Lien Senior Secured"
    elif "second lien" in inv_lower or "2nd lien" in inv_lower:
        return "Second Lien"
    elif "subordinated" in inv_lower or "mezzanine" in inv_lower or "unsecured loan" in inv_lower or "unsecured note" in inv_lower:
        return "Subordinated Debt"
    elif "preferred" in inv_lower:
        return "Preferred Equity"
    elif "common" in inv_lower or "partnership interest" in inv_lower or "membership interest" in inv_lower or "llc interest" in inv_lower or "equity interest" in inv_lower:
        return "Common Equity"
    elif "warrant" in inv_lower or "option" in inv_lower:
        return "Warrants"
    elif "loan" in inv_lower or "note" in inv_lower:
        return "First Lien Senior Secured"
    else:
        return "Common Equity"
