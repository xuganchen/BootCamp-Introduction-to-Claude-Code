#!/usr/bin/env python3
"""
bdc_05_validate_reconcile.py
----------------------------
Acceptance criteria validation, accounting reconciliation, and atomic export engine
for BDC fund panel and investment panel datasets.

Specification: plan_v1.md & plan_v0.md
Enforces:
  1. Fund Panel Non-null fields & Accounting Identity (Liabilities + Net Assets == Total Assets).
  2. Investment Panel Non-null fields & Borrower Multiplicity (unique(borrower) < count(rows)).
  3. Cross-table consistency:
     - Date & Entity matching (bdc_name, cik, period_end_date)
     - Fair Value Reconciliation: |sum(fair_value) - total_investments_fair_value| / total_investments_fair_value <= 0.001 (0.1%)
  4. Unit consistency across tables.
  5. Strict Fail-Closed / Atomic Export:
     - On failure: log full error details, delete partial files in output/, exit(1).
     - On success: write output/{csv,parquet} and note/validation_report.md, exit(0).
"""

import sys
import os
import shutil
import tempfile
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

import pandas as pd
import numpy as np

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("BDC_Validator")

# Expected Schemas per plan_v1.md
FUND_PANEL_SCHEMA = {
    "required_columns": [
        "bdc_name", "bdc_ticker", "cik", "filing_type", "fiscal_year",
        "fiscal_quarter", "period_end_date", "filing_date", "unit",
        "total_investments_fair_value", "total_investments_amortized_cost",
        "cash_and_cash_equivalents", "other_assets", "total_assets",
        "debt_outstanding", "other_liabilities", "total_liabilities",
        "net_assets", "shares_outstanding", "net_asset_value_per_share"
    ],
    "mandatory_non_null": [
        "bdc_name", "bdc_ticker", "cik", "filing_type", "fiscal_year",
        "fiscal_quarter", "period_end_date", "filing_date", "unit",
        "total_investments_fair_value", "total_assets", "total_liabilities", "net_assets"
    ],
    "numeric_fields": [
        "total_investments_fair_value", "total_investments_amortized_cost",
        "cash_and_cash_equivalents", "other_assets", "total_assets",
        "debt_outstanding", "other_liabilities", "total_liabilities",
        "net_assets", "shares_outstanding", "net_asset_value_per_share"
    ]
}

INVESTMENT_PANEL_SCHEMA = {
    "required_columns": [
        "bdc_name", "bdc_ticker", "cik", "period_end_date", "filing_date",
        "borrower_name", "industry", "investment_category", "investment_type",
        "interest_rate_type", "reference_rate", "spread_bps", "interest_floor_pct",
        "total_coupon_rate_pct", "is_pik", "is_non_accrual", "maturity_date",
        "unit", "principal_amount", "amortized_cost", "fair_value", "pct_of_net_assets"
    ],
    "mandatory_non_null": [
        "bdc_name", "bdc_ticker", "cik", "period_end_date", "filing_date",
        "borrower_name", "investment_type", "fair_value", "unit"
    ],
    "numeric_fields": [
        "spread_bps", "interest_floor_pct", "total_coupon_rate_pct",
        "principal_amount", "amortized_cost", "fair_value", "pct_of_net_assets"
    ]
}


class ValidationError(Exception):
    """Custom exception raised when validation checks fail."""
    pass


@dataclass
class ValidationMetrics:
    fund_rows: int = 0
    investment_rows: int = 0
    unique_borrowers: int = 0
    borrower_multiplicity_ratio: float = 0.0
    fund_total_investments_fair_value: float = 0.0
    investment_sum_fair_value: float = 0.0
    fair_value_abs_diff: float = 0.0
    fair_value_rel_diff_pct: float = 0.0
    reconciliation_passed: bool = False
    fund_total_assets: float = 0.0
    fund_total_liabilities: float = 0.0
    fund_net_assets: float = 0.0
    accounting_identity_diff: float = 0.0
    accounting_identity_passed: bool = False
    unit_fund: str = ""
    unit_investment: str = ""
    unit_consistency_passed: bool = False
    entity_names: List[str] = field(default_factory=list)
    period_end_dates: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    check_results: Dict[str, bool] = field(default_factory=dict)


def validate_dates(df: pd.DataFrame, date_cols: List[str], table_name: str) -> List[str]:
    """Validate that date strings adhere to YYYY-MM-DD format."""
    errors = []
    for col in date_cols:
        if col not in df.columns:
            continue
        non_null_dates = df[col].dropna()
        for idx, val in non_null_dates.items():
            val_str = str(val).strip()
            if not val_str:
                continue
            try:
                dt = datetime.strptime(val_str, "%Y-%m-%d")
            except ValueError:
                errors.append(
                    f"[{table_name}] Invalid date format in column '{col}' at row {idx}: '{val}' (expected YYYY-MM-DD)"
                )
    return errors


def validate_fund_panel(fund_df: pd.DataFrame) -> Tuple[List[str], Dict[str, Any]]:
    """Validate Fund Panel rules per plan_v1.md."""
    errors = []
    details: Dict[str, Any] = {}

    if fund_df.empty:
        errors.append("[Fund Panel] Fund DataFrame is empty.")
        return errors, details

    # 1. Column presence
    missing_cols = [c for c in FUND_PANEL_SCHEMA["required_columns"] if c not in fund_df.columns]
    if missing_cols:
        errors.append(f"[Fund Panel] Missing required columns: {missing_cols}")

    # 2. Mandatory non-null checks
    for col in FUND_PANEL_SCHEMA["mandatory_non_null"]:
        if col in fund_df.columns:
            null_count = fund_df[col].isna().sum()
            # Also check for empty string if object type
            if fund_df[col].dtype == object:
                empty_count = (fund_df[col].astype(str).str.strip() == "").sum()
                null_count += empty_count
            if null_count > 0:
                errors.append(f"[Fund Panel] Mandatory field '{col}' contains {null_count} null or empty values.")

    # 3. Numeric conversion & Accounting Identity
    for col in FUND_PANEL_SCHEMA["numeric_fields"]:
        if col in fund_df.columns:
            fund_df[col] = pd.to_numeric(fund_df[col], errors="coerce")

    # Accounting Identity: |Total Liabilities + Net Assets - Total Assets| < 1.0 (adjusted for rounding/units)
    if all(c in fund_df.columns for c in ["total_assets", "total_liabilities", "net_assets"]):
        for idx, row in fund_df.iterrows():
            ta = row["total_assets"]
            tl = row["total_liabilities"]
            na = row["net_assets"]

            if pd.isna(ta) or pd.isna(tl) or pd.isna(na):
                errors.append(f"[Fund Panel] Accounting check skipped at row {idx} due to NaN in assets/liabilities/net_assets.")
                continue

            diff = abs((tl + na) - ta)
            details[f"row_{idx}_accounting_diff"] = diff
            if diff >= 1.0:
                errors.append(
                    f"[Fund Panel] Accounting identity violation at row {idx}: "
                    f"Total Liabilities ({tl}) + Net Assets ({na}) = {tl + na}, "
                    f"Total Assets = {ta}, Diff = {diff:.4f} (threshold: < 1.0)"
                )

    # 4. Date formatting
    date_errors = validate_dates(fund_df, ["period_end_date", "filing_date"], "Fund Panel")
    errors.extend(date_errors)

    return errors, details


def validate_investment_panel(investment_df: pd.DataFrame) -> Tuple[List[str], Dict[str, Any]]:
    """Validate Investment Panel rules per plan_v1.md."""
    errors = []
    details: Dict[str, Any] = {}

    if investment_df.empty:
        errors.append("[Investment Panel] Investment DataFrame is empty.")
        return errors, details

    # 1. Column presence
    missing_cols = [c for c in INVESTMENT_PANEL_SCHEMA["required_columns"] if c not in investment_df.columns]
    if missing_cols:
        errors.append(f"[Investment Panel] Missing required columns: {missing_cols}")

    # 2. Mandatory non-null checks
    for col in INVESTMENT_PANEL_SCHEMA["mandatory_non_null"]:
        if col in investment_df.columns:
            null_count = investment_df[col].isna().sum()
            if investment_df[col].dtype == object:
                empty_count = (investment_df[col].astype(str).str.strip() == "").sum()
                null_count += empty_count
            if null_count > 0:
                errors.append(f"[Investment Panel] Mandatory field '{col}' contains {null_count} null or empty values.")

    # 3. Numeric conversions
    for col in INVESTMENT_PANEL_SCHEMA["numeric_fields"]:
        if col in investment_df.columns:
            investment_df[col] = pd.to_numeric(investment_df[col], errors="coerce")

    # 4. Borrower multiplicity sanity: unique(borrower_name) < count(rows)
    if "borrower_name" in investment_df.columns:
        total_rows = len(investment_df)
        unique_borrowers = investment_df["borrower_name"].dropna().astype(str).str.strip().nunique()
        details["total_positions"] = total_rows
        details["unique_borrowers"] = unique_borrowers

        if total_rows > 1 and unique_borrowers >= total_rows:
            errors.append(
                f"[Investment Panel] Borrower multiplicity check failed: "
                f"Unique borrowers ({unique_borrowers}) >= Total positions ({total_rows}). "
                f"Expected unique(borrower_name) < count(rows) because BDCs hold multiple loans per borrower."
            )
        elif total_rows <= 1:
            errors.append(f"[Investment Panel] Insufficient rows ({total_rows}) to satisfy multiplicity criteria.")

    # 5. Date formatting
    date_errors = validate_dates(investment_df, ["period_end_date", "filing_date", "maturity_date"], "Investment Panel")
    errors.extend(date_errors)

    return errors, details


def validate_cross_table(
    fund_df: pd.DataFrame,
    investment_df: pd.DataFrame
) -> Tuple[List[str], ValidationMetrics]:
    """Validate cross-table reconciliation, entity/date consistency, and unit uniformity."""
    errors = []
    metrics = ValidationMetrics()

    metrics.fund_rows = len(fund_df)
    metrics.investment_rows = len(investment_df)

    if fund_df.empty or investment_df.empty:
        errors.append("[Cross-Table] Cannot perform cross-table validation with empty DataFrame(s).")
        metrics.errors = errors
        return errors, metrics

    # 1. Unit Consistency Check
    fund_units = fund_df["unit"].dropna().unique().tolist() if "unit" in fund_df.columns else []
    inv_units = investment_df["unit"].dropna().unique().tolist() if "unit" in investment_df.columns else []

    if len(fund_units) != 1:
        errors.append(f"[Unit Consistency] Fund panel does not have a single uniform unit: {fund_units}")
    if len(inv_units) != 1:
        errors.append(f"[Unit Consistency] Investment panel does not have a single uniform unit: {inv_units}")

    if fund_units and inv_units:
        metrics.unit_fund = str(fund_units[0])
        metrics.unit_investment = str(inv_units[0])
        if fund_units[0] != inv_units[0]:
            errors.append(
                f"[Unit Consistency] Unit mismatch between Fund panel ('{fund_units[0]}') and Investment panel ('{inv_units[0]}')."
            )
        else:
            metrics.unit_consistency_passed = True

    # 2. Date & Entity Consistency
    fund_entities = set(zip(fund_df["bdc_name"].astype(str), fund_df["cik"].astype(str), fund_df["period_end_date"].astype(str)))
    inv_entities = set(zip(investment_df["bdc_name"].astype(str), investment_df["cik"].astype(str), investment_df["period_end_date"].astype(str)))

    metrics.entity_names = fund_df["bdc_name"].dropna().unique().tolist() if "bdc_name" in fund_df.columns else []
    metrics.period_end_dates = fund_df["period_end_date"].dropna().unique().tolist() if "period_end_date" in fund_df.columns else []

    if inv_entities != fund_entities:
        diff_inv_fund = inv_entities - fund_entities
        diff_fund_inv = fund_entities - inv_entities
        msg = f"[Date & Entity Consistency] Mismatch between Fund and Investment panels."
        if diff_inv_fund:
            msg += f" Investment has entities/dates not in Fund: {diff_inv_fund}."
        if diff_fund_inv:
            msg += f" Fund has entities/dates not in Investment: {diff_fund_inv}."
        errors.append(msg)

    # 3. Fair Value Reconciliation Check per entity/date
    for entity in fund_entities:
        name, cik, period_end = entity
        fund_sub = fund_df[
            (fund_df["bdc_name"].astype(str) == name) &
            (fund_df["cik"].astype(str) == cik) &
            (fund_df["period_end_date"].astype(str) == period_end)
        ]
        inv_sub = investment_df[
            (investment_df["bdc_name"].astype(str) == name) &
            (investment_df["cik"].astype(str) == cik) &
            (investment_df["period_end_date"].astype(str) == period_end)
        ]

        if fund_sub.empty or inv_sub.empty:
            continue

        fund_fv = float(fund_sub["total_investments_fair_value"].iloc[0])
        inv_fv_sum = float(inv_sub["fair_value"].sum())

        abs_diff = abs(inv_fv_sum - fund_fv)
        rel_diff = abs_diff / fund_fv if fund_fv > 0 else float("inf")
        rel_diff_pct = rel_diff * 100.0

        metrics.fund_total_investments_fair_value = fund_fv
        metrics.investment_sum_fair_value = inv_fv_sum
        metrics.fair_value_abs_diff = abs_diff
        metrics.fair_value_rel_diff_pct = rel_diff_pct

        if rel_diff <= 0.001:  # within 0.1% tolerance
            metrics.reconciliation_passed = True
        else:
            metrics.reconciliation_passed = False
            errors.append(
                f"[Reconciliation Check] Fair value reconciliation failed for {name} ({period_end}): "
                f"SOI Sum = {inv_fv_sum:,.2f}, Fund Balance Sheet Total = {fund_fv:,.2f}, "
                f"Abs Diff = {abs_diff:,.2f}, Rel Diff = {rel_diff_pct:.4f}% (Threshold: <= 0.1000%)"
            )

    # Populate additional metrics
    if "borrower_name" in investment_df.columns:
        metrics.unique_borrowers = investment_df["borrower_name"].dropna().astype(str).str.strip().nunique()
        if metrics.investment_rows > 0:
            metrics.borrower_multiplicity_ratio = metrics.unique_borrowers / metrics.investment_rows

    if not fund_df.empty:
        if "total_assets" in fund_df.columns:
            metrics.fund_total_assets = float(fund_df["total_assets"].iloc[0])
        if "total_liabilities" in fund_df.columns:
            metrics.fund_total_liabilities = float(fund_df["total_liabilities"].iloc[0])
        if "net_assets" in fund_df.columns:
            metrics.fund_net_assets = float(fund_df["net_assets"].iloc[0])
        metrics.accounting_identity_diff = abs(
            (metrics.fund_total_liabilities + metrics.fund_net_assets) - metrics.fund_total_assets
        )
        metrics.accounting_identity_passed = metrics.accounting_identity_diff < 1.0

    metrics.errors = errors
    return errors, metrics


def validate_datasets(
    fund_df: pd.DataFrame,
    investment_df: pd.DataFrame
) -> Tuple[bool, ValidationMetrics]:
    """Execute complete validation suite on Fund and Investment DataFrames."""
    all_errors = []
    
    # Make working copies
    f_df = fund_df.copy()
    i_df = investment_df.copy()

    # 1. Fund panel validation
    fund_errors, _ = validate_fund_panel(f_df)
    all_errors.extend(fund_errors)

    # 2. Investment panel validation
    inv_errors, _ = validate_investment_panel(i_df)
    all_errors.extend(inv_errors)

    # 3. Cross-table validation
    cross_errors, metrics = validate_cross_table(f_df, i_df)
    all_errors.extend(cross_errors)

    metrics.errors = all_errors
    
    # Record check results
    metrics.check_results = {
        "Fund Schema & Non-Null": len(fund_errors) == 0,
        "Fund Accounting Identity": metrics.accounting_identity_passed,
        "Investment Schema & Non-Null": len([e for e in inv_errors if "Missing required" in e or "Mandatory field" in e]) == 0,
        "Investment Borrower Multiplicity": metrics.unique_borrowers < metrics.investment_rows if metrics.investment_rows > 1 else False,
        "Cross-Table Date & Entity Match": len([e for e in cross_errors if "Date & Entity" in e]) == 0,
        "Cross-Table Fair Value Reconciliation (<= 0.1%)": metrics.reconciliation_passed,
        "Cross-Table Unit Uniformity": metrics.unit_consistency_passed
    }

    is_valid = len(all_errors) == 0
    return is_valid, metrics


def generate_validation_report_md(
    metrics: ValidationMetrics,
    fund_df: pd.DataFrame,
    investment_df: pd.DataFrame,
    output_files: Dict[str, str]
) -> str:
    """Generate comprehensive Markdown validation report."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    overall_status = "PASSED" if not metrics.errors else "FAILED"

    report = []
    report.append(f"# BDC Dataset Validation & Reconciliation Report\n")
    report.append(f"**Generated at**: `{timestamp}`  ")
    report.append(f"**Overall Status**: `{overall_status}`\n")
    report.append("---\n")

    # 1. Executive Summary Table
    report.append("## 1. Validation Matrix Summary\n")
    report.append("| Validation Check | Specification Threshold | Observed Value | Status |")
    report.append("| :--- | :--- | :--- | :--- |")
    
    # Fund non-null
    fund_nn_status = "PASS" if metrics.check_results.get("Fund Schema & Non-Null", False) else "FAIL"
    report.append(f"| Fund Panel Non-Null Integrity | No nulls in mandatory fields | {metrics.fund_rows} rows verified | `{fund_nn_status}` |")

    # Accounting Identity
    acct_status = "PASS" if metrics.accounting_identity_passed else "FAIL"
    report.append(
        f"| Fund Accounting Identity | |Liab + Net Assets - Assets| < 1.0 | "
        f"Diff = {metrics.accounting_identity_diff:.4f} | `{acct_status}` |"
    )

    # Investment non-null
    inv_nn_status = "PASS" if metrics.check_results.get("Investment Schema & Non-Null", False) else "FAIL"
    report.append(f"| Investment Panel Non-Null Integrity | No nulls in mandatory fields | {metrics.investment_rows} positions verified | `{inv_nn_status}` |")

    # Borrower Multiplicity
    mult_status = "PASS" if metrics.check_results.get("Investment Borrower Multiplicity", False) else "FAIL"
    report.append(
        f"| Borrower Multiplicity | Unique Borrowers < Total Positions | "
        f"{metrics.unique_borrowers} borrowers / {metrics.investment_rows} positions ({metrics.borrower_multiplicity_ratio:.1%}) | `{mult_status}` |"
    )

    # Date & Entity
    entity_status = "PASS" if metrics.check_results.get("Cross-Table Date & Entity Match", False) else "FAIL"
    report.append(
        f"| Date & Entity Consistency | Exact match across Fund & SOI | "
        f"Entities: {', '.join(metrics.entity_names)} ({', '.join(metrics.period_end_dates)}) | `{entity_status}` |"
    )

    # Fair Value Reconciliation
    recon_status = "PASS" if metrics.reconciliation_passed else "FAIL"
    report.append(
        f"| Fair Value Reconciliation | Relative Diff <= 0.1000% | "
        f"Diff = {metrics.fair_value_abs_diff:,.2f} ({metrics.fair_value_rel_diff_pct:.4f}%) | `{recon_status}` |"
    )

    # Unit Uniformity
    unit_status = "PASS" if metrics.unit_consistency_passed else "FAIL"
    report.append(
        f"| Unit Uniformity | Standardized unit across tables | "
        f"Fund: `{metrics.unit_fund}`, SOI: `{metrics.unit_investment}` | `{unit_status}` |"
    )

    report.append("\n---\n")

    # 2. Detailed Breakdown
    report.append("## 2. Detailed Accounting & Reconciliation Audit\n")
    report.append("### 2.1. Balance Sheet Accounting Identity (Fund Panel)")
    report.append("```")
    report.append(f"Total Assets:       ${metrics.fund_total_assets:>18,.2f} ({metrics.unit_fund})")
    report.append(f"Total Liabilities:  ${metrics.fund_total_liabilities:>18,.2f} ({metrics.unit_fund})")
    report.append(f"Net Assets:         ${metrics.fund_net_assets:>18,.2f} ({metrics.unit_fund})")
    report.append(f"Liab + Net Assets:  ${(metrics.fund_total_liabilities + metrics.fund_net_assets):>18,.2f} ({metrics.unit_fund})")
    report.append(f"Absolute Difference: ${metrics.accounting_identity_diff:>18,.4f}")
    report.append(f"Accounting Balance: {'BALANCED (< 1.0 unit diff)' if metrics.accounting_identity_passed else 'OUT OF BALANCE'}")
    report.append("```\n")

    report.append("### 2.2. Schedule of Investments (SOI) vs. Balance Sheet Reconciliation")
    report.append("```")
    report.append(f"Balance Sheet Portfolio Fair Value: ${metrics.fund_total_investments_fair_value:>18,.2f} ({metrics.unit_fund})")
    report.append(f"SOI Sum of Position Fair Values:   ${metrics.investment_sum_fair_value:>18,.2f} ({metrics.unit_investment})")
    report.append(f"Absolute Discrepancy:              ${metrics.fair_value_abs_diff:>18,.2f}")
    report.append(f"Relative Discrepancy:               {metrics.fair_value_rel_diff_pct:>17.4f}%")
    report.append(f"Tolerance Threshold:                                 0.1000%")
    report.append(f"Reconciliation Status:              {'RECONCILED (Within Tolerance)' if metrics.reconciliation_passed else 'RECONCILIATION FAILED'}")
    report.append("```\n")

    report.append("### 2.3. Portfolio Diversity & Multiplicity Metrics")
    report.append(f"- **Total Investment Positions**: `{metrics.investment_rows}`")
    report.append(f"- **Unique Portfolio Companies / Borrowers**: `{metrics.unique_borrowers}`")
    report.append(f"- **Multiplicity Ratio (Borrowers / Positions)**: `{metrics.borrower_multiplicity_ratio:.2%}`")
    report.append(f"- **Average Positions per Borrower**: `{(metrics.investment_rows / metrics.unique_borrowers if metrics.unique_borrowers > 0 else 0):.2f}`\n")

    # 3. Output Artifacts
    if output_files:
        report.append("## 3. Exported Final Deliverables\n")
        report.append("| File Path | Format | Row Count | File Size |")
        report.append("| :--- | :--- | :--- | :--- |")
        for path_str, desc in output_files.items():
            p = Path(path_str)
            size_kb = p.stat().st_size / 1024.0 if p.exists() else 0.0
            row_cnt = len(fund_df) if "fund" in p.name else len(investment_df)
            report.append(f"| `{p.as_posix()}` | {p.suffix.upper()} | {row_cnt:,} | {size_kb:.2f} KB |")
        report.append("\n")

    # 4. Error / Warning Log
    if metrics.errors:
        report.append("## 4. Validation Errors Detected\n")
        for err in metrics.errors:
            report.append(f"- :x: `{err}`")
        report.append("\n")

    return "\n".join(report)


def clean_output_dir(output_dir: Path, output_filenames: List[str]):
    """Clean partial or corrupt files from output directory upon failure."""
    for fname in output_filenames:
        target = output_dir / fname
        if target.exists():
            try:
                target.unlink()
                logger.info(f"Cleaned partial output file: {target}")
            except Exception as e:
                logger.warning(f"Failed to delete {target}: {e}")


def export_atomic(
    fund_df: pd.DataFrame,
    investment_df: pd.DataFrame,
    output_dir: Path,
    note_dir: Path,
    metrics: ValidationMetrics
) -> Dict[str, str]:
    """
    Atomically writes final validated CSV, Parquet, and Markdown files.
    Writes to a temporary directory first, then moves files into final destination.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    note_dir.mkdir(parents=True, exist_ok=True)

    # Use atomic write via temp directory
    with tempfile.TemporaryDirectory(dir=output_dir) as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        tmp_fund_csv = tmp_dir / "bdc_quarter_fund_panel.csv"
        tmp_fund_parquet = tmp_dir / "bdc_quarter_fund_panel.parquet"
        tmp_inv_csv = tmp_dir / "bdc_quarter_investment_panel.csv"
        tmp_inv_parquet = tmp_dir / "bdc_quarter_investment_panel.parquet"

        fund_df.to_csv(tmp_fund_csv, index=False)
        fund_df.to_parquet(tmp_fund_parquet, index=False)
        investment_df.to_csv(tmp_inv_csv, index=False)
        investment_df.to_parquet(tmp_inv_parquet, index=False)

        # Move to target paths
        shutil.move(str(tmp_fund_csv), str(output_dir / "bdc_quarter_fund_panel.csv"))
        shutil.move(str(tmp_fund_parquet), str(output_dir / "bdc_quarter_fund_panel.parquet"))
        shutil.move(str(tmp_inv_csv), str(output_dir / "bdc_quarter_investment_panel.csv"))
        shutil.move(str(tmp_inv_parquet), str(output_dir / "bdc_quarter_investment_panel.parquet"))

    final_output_map = {
        str(output_dir / "bdc_quarter_fund_panel.csv"): "Fund Panel CSV",
        str(output_dir / "bdc_quarter_fund_panel.parquet"): "Fund Panel Parquet",
        str(output_dir / "bdc_quarter_investment_panel.csv"): "Investment Panel CSV",
        str(output_dir / "bdc_quarter_investment_panel.parquet"): "Investment Panel Parquet",
    }

    # Write report
    report_content = generate_validation_report_md(metrics, fund_df, investment_df, final_output_map)
    report_file = note_dir / "validation_report.md"
    report_file.write_text(report_content, encoding="utf-8")
    final_output_map[str(report_file)] = "Validation Report Markdown"

    return final_output_map


def run_pipeline(
    fund_interim_path: Path,
    investment_interim_path: Path,
    output_dir: Path,
    note_dir: Path
) -> bool:
    """
    Main orchestration function for bdc_05_validate_reconcile.
    """
    logger.info("Starting BDC Acceptance Criteria Validation & Reconciliation Engine...")
    logger.info(f"Reading Fund interim data from: {fund_interim_path}")
    logger.info(f"Reading Investment interim data from: {investment_interim_path}")

    # 1. Verify existence of interim files
    if not fund_interim_path.exists():
        logger.error(f"Fund interim file not found: {fund_interim_path}")
        sys.exit(1)
    if not investment_interim_path.exists():
        logger.error(f"Investment interim file not found: {investment_interim_path}")
        sys.exit(1)

    try:
        fund_df = pd.read_csv(fund_interim_path)
        investment_df = pd.read_csv(investment_interim_path)
    except Exception as e:
        logger.error(f"Failed to read interim CSV files: {e}")
        sys.exit(1)

    # 2. Run Validation Suite
    is_valid, metrics = validate_datasets(fund_df, investment_df)

    if not is_valid:
        logger.error("=" * 70)
        logger.error("VALIDATION FAILED: Acceptance criteria violated.")
        for err in metrics.errors:
            logger.error(f"  - {err}")
        logger.error("=" * 70)
        
        # Clean any partial files in output
        clean_output_dir(
            output_dir,
            [
                "bdc_quarter_fund_panel.csv",
                "bdc_quarter_fund_panel.parquet",
                "bdc_quarter_investment_panel.csv",
                "bdc_quarter_investment_panel.parquet"
            ]
        )
        sys.exit(1)

    # 3. Export Verified Datasets Atomically
    logger.info("All validation checks passed successfully!")
    logger.info(f"Fund Accounting Balance: Diff = {metrics.accounting_identity_diff:.4f} (< 1.0)")
    logger.info(f"Fair Value Reconciliation: Diff = {metrics.fair_value_abs_diff:,.2f} ({metrics.fair_value_rel_diff_pct:.4f}% <= 0.1%)")
    logger.info(f"Borrower Multiplicity: {metrics.unique_borrowers} unique borrowers for {metrics.investment_rows} positions")

    try:
        output_files = export_atomic(fund_df, investment_df, output_dir, note_dir, metrics)
        logger.info("Exported files successfully:")
        for path_str in output_files:
            logger.info(f"  - {path_str}")
    except Exception as e:
        logger.error(f"Failed during atomic export: {e}")
        clean_output_dir(
            output_dir,
            [
                "bdc_quarter_fund_panel.csv",
                "bdc_quarter_fund_panel.parquet",
                "bdc_quarter_investment_panel.csv",
                "bdc_quarter_investment_panel.parquet"
            ]
        )
        sys.exit(1)

    logger.info("Validation & Reconciliation pipeline completed successfully (Exit Code 0).")
    return True


def main():
    base_dir = Path(__file__).resolve().parent.parent
    fund_interim = base_dir / "data" / "interim" / "bdc_fund_clean.csv"
    investment_interim = base_dir / "data" / "interim" / "bdc_investment_clean.csv"
    output_dir = base_dir / "output"
    note_dir = base_dir / "note"

    run_pipeline(fund_interim, investment_interim, output_dir, note_dir)


if __name__ == "__main__":
    main()
