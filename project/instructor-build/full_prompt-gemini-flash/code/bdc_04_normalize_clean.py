"""
bdc_04_normalize_clean.py - Data Normalization, Unit Harmonization & Cleaning Engine.

Performs:
- Standardization of units to USD_THOUSANDS across fund and position panels.
- Text cleaning and footnote stripping on company/borrower names and industries.
- Granular parsing of interest rates (SOFR, spread bps, floors, PIK flags, non-accrual).
- Date normalization to standard ISO YYYY-MM-DD format.
- Investment asset categorization (First Lien, Second Lien, Subordinated, Preferred, Common).

Produces clean staging datasets:
- data/interim/bdc_fund_clean.csv
- data/interim/bdc_investment_clean.csv
"""

import os
import sys
import pandas as pd
from typing import Dict, Any, Optional

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bdc_09_utils import (
    setup_logger,
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
)

logger = setup_logger("bdc_04_normalize_clean")


def clean_fund_financials(
    interim_dir: str = "data/interim"
) -> pd.DataFrame:
    """
    Cleans and standardizes fund financials to USD_THOUSANDS.
    """
    raw_path = os.path.join(interim_dir, "fund_financials_raw.csv")
    if not os.path.exists(raw_path):
        raise FileNotFoundError(f"Raw fund financials not found at {raw_path}")

    df = pd.read_csv(raw_path)
    logger.info(f"Loaded raw fund financials: {len(df)} rows.")

    clean_rows = []
    for _, row in df.iterrows():
        # Raw units are in USD_MILLIONS, convert to USD_THOUSANDS (* 1000)
        multiplier = 1000.0 if row.get("unit") == "USD_MILLIONS" else 1.0

        total_inv_fv = float(row["total_investments_fair_value"]) * multiplier
        total_inv_cost = float(row["total_investments_amortized_cost"]) * multiplier if pd.notna(row.get("total_investments_amortized_cost")) else None
        cash = float(row["cash_and_cash_equivalents"]) * multiplier if pd.notna(row.get("cash_and_cash_equivalents")) else None
        total_assets = float(row["total_assets"]) * multiplier
        debt = float(row["debt_outstanding"]) * multiplier if pd.notna(row.get("debt_outstanding")) else None
        total_liabilities = float(row["total_liabilities"]) * multiplier
        net_assets = float(row["net_assets"]) * multiplier

        # Compute other_assets and other_liabilities
        other_assets = total_assets - total_inv_fv - (cash if cash is not None else 0.0)
        other_liabilities = total_liabilities - (debt if debt is not None else 0.0)

        # Shares outstanding in thousands of shares (* 1000 if reported in millions)
        shares_out = float(row["shares_outstanding"]) * 1000.0 if pd.notna(row.get("shares_outstanding")) else None
        nav_per_share = float(row["net_asset_value_per_share"]) if pd.notna(row.get("net_asset_value_per_share")) else None

        clean_row = {
            "bdc_name": clean_text(row.get("bdc_name", ARCC_NAME)),
            "bdc_ticker": clean_text(row.get("bdc_ticker", ARCC_TICKER)),
            "cik": format_cik(row.get("cik", ARCC_CIK)),
            "filing_type": clean_text(row.get("filing_type", "10-Q")),
            "fiscal_year": int(row.get("fiscal_year", 2026)),
            "fiscal_quarter": clean_text(row.get("fiscal_quarter", "Q2")),
            "period_end_date": normalize_date(row.get("period_end_date")),
            "filing_date": normalize_date(row.get("filing_date")),
            "unit": STANDARD_UNIT,
            "total_investments_fair_value": round(total_inv_fv, 2),
            "total_investments_amortized_cost": round(total_inv_cost, 2) if total_inv_cost is not None else None,
            "cash_and_cash_equivalents": round(cash, 2) if cash is not None else None,
            "other_assets": round(other_assets, 2),
            "total_assets": round(total_assets, 2),
            "debt_outstanding": round(debt, 2) if debt is not None else None,
            "other_liabilities": round(other_liabilities, 2),
            "total_liabilities": round(total_liabilities, 2),
            "net_assets": round(net_assets, 2),
            "shares_outstanding": round(shares_out, 2) if shares_out is not None else None,
            "net_asset_value_per_share": round(nav_per_share, 4) if nav_per_share is not None else None,
        }
        clean_rows.append(clean_row)

    df_clean = pd.DataFrame(clean_rows)
    out_path = os.path.join(interim_dir, "bdc_fund_clean.csv")
    df_clean.to_csv(out_path, index=False)
    logger.info(f"Saved clean fund panel to {out_path}")
    return df_clean


def clean_soi_positions(
    interim_dir: str = "data/interim"
) -> pd.DataFrame:
    """
    Cleans and standardizes SOI position data to USD_THOUSANDS.
    """
    raw_path = os.path.join(interim_dir, "soi_positions_raw.csv")
    if not os.path.exists(raw_path):
        raise FileNotFoundError(f"Raw SOI positions not found at {raw_path}")

    df = pd.read_csv(raw_path)
    logger.info(f"Loaded raw SOI positions: {len(df)} rows.")

    clean_positions = []
    for _, row in df.iterrows():
        borrower_raw = str(row.get("borrower_name", ""))
        borrower_name = strip_footnotes(borrower_raw)
        if not borrower_name:
            continue

        industry = clean_text(row.get("industry", ""))
        inv_type = clean_text(row.get("investment_type", ""))
        if not inv_type:
            continue

        category = classify_investment_category(inv_type)

        # Parse interest rate terms
        rate_info = parse_interest_rate_terms(
            coupon_raw=row.get("coupon_raw", ""),
            reference_raw=row.get("reference_rate_raw", ""),
            spread_raw=row.get("spread_raw", ""),
            investment_type_raw=inv_type,
            footnote_raw=row.get("footnote_raw", ""),
        )

        maturity_date = normalize_date(row.get("maturity_date_raw"))

        # Amounts in raw SOI are reported in millions of dollars ($ in millions)
        # Convert to USD_THOUSANDS (* 1000)
        principal_raw = parse_number(row.get("principal_raw"))
        principal_amount = round(principal_raw * 1000.0, 2) if principal_raw is not None else None

        cost_raw = parse_number(row.get("amortized_cost_raw"))
        amortized_cost = round(cost_raw * 1000.0, 2) if cost_raw is not None else None

        fv_raw = parse_number(row.get("fair_value_raw"))
        if fv_raw is None:
            # Skip records without valid fair value
            continue
        fair_value = round(fv_raw * 1000.0, 2)

        pct_nav_raw = parse_percentage(row.get("pct_of_net_assets_raw"))
        pct_of_net_assets = round(pct_nav_raw, 4) if pct_nav_raw is not None else None

        clean_pos = {
            "bdc_name": clean_text(row.get("bdc_name", ARCC_NAME)),
            "bdc_ticker": clean_text(row.get("bdc_ticker", ARCC_TICKER)),
            "cik": format_cik(row.get("cik", ARCC_CIK)),
            "period_end_date": normalize_date(row.get("period_end_date")),
            "filing_date": normalize_date(row.get("filing_date")),
            "borrower_name": borrower_name,
            "industry": industry if industry else None,
            "investment_category": category,
            "investment_type": inv_type,
            "interest_rate_type": rate_info["interest_rate_type"],
            "reference_rate": rate_info["reference_rate"],
            "spread_bps": rate_info["spread_bps"],
            "interest_floor_pct": rate_info["interest_floor_pct"],
            "total_coupon_rate_pct": rate_info["total_coupon_rate_pct"],
            "is_pik": rate_info["is_pik"],
            "is_non_accrual": rate_info["is_non_accrual"],
            "maturity_date": maturity_date,
            "unit": STANDARD_UNIT,
            "principal_amount": principal_amount,
            "amortized_cost": amortized_cost,
            "fair_value": fair_value,
            "pct_of_net_assets": pct_of_net_assets,
        }
        clean_positions.append(clean_pos)

    df_clean = pd.DataFrame(clean_positions)
    logger.info(f"Cleaned {len(df_clean)} investment positions.")

    out_path = os.path.join(interim_dir, "bdc_investment_clean.csv")
    df_clean.to_csv(out_path, index=False)
    logger.info(f"Saved clean investment panel to {out_path}")
    return df_clean


def run_normalization():
    """Runs end-to-end normalization for fund and investment panels."""
    clean_fund_financials()
    clean_soi_positions()


if __name__ == "__main__":
    run_normalization()
