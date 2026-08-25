#!/usr/bin/env python3
"""
test_acceptance_criteria.py
---------------------------
Comprehensive unit test suite for BDC acceptance criteria and validation engine.
Tests all validation rules, schemas, accounting identities, reconciliation tolerances,
borrower multiplicity sanity, unit consistency, and atomic export behaviors.

Uses mock test data without touching raw filings or parser internals.
"""

import sys
import os
import shutil
import tempfile
import unittest
from pathlib import Path
import pandas as pd
import numpy as np

# Ensure code/ is on path
code_dir = Path(__file__).resolve().parent
if str(code_dir) not in sys.path:
    sys.path.insert(0, str(code_dir))

from bdc_05_validate_reconcile import (
    validate_fund_panel,
    validate_investment_panel,
    validate_cross_table,
    validate_datasets,
    generate_validation_report_md,
    export_atomic,
    clean_output_dir,
    FUND_PANEL_SCHEMA,
    INVESTMENT_PANEL_SCHEMA,
)


def get_mock_valid_fund_df() -> pd.DataFrame:
    """Create a valid fund panel DataFrame adhering strictly to plan_v1.md schema."""
    data = [{
        "bdc_name": "Ares Capital Corporation",
        "bdc_ticker": "ARCC",
        "cik": "0001279495",
        "filing_type": "10-Q",
        "fiscal_year": 2024,
        "fiscal_quarter": "Q3",
        "period_end_date": "2024-09-30",
        "filing_date": "2024-10-30",
        "unit": "USD_THOUSANDS",
        "total_investments_fair_value": 25000000.0,
        "total_investments_amortized_cost": 25200000.0,
        "cash_and_cash_equivalents": 500000.0,
        "other_assets": 400000.0,
        "total_assets": 25900000.0,
        "debt_outstanding": 13000000.0,
        "other_liabilities": 400000.0,
        "total_liabilities": 13400000.0,
        "net_assets": 12500000.0,  # 13,400,000 + 12,500,000 = 25,900,000 == Total Assets
        "shares_outstanding": 640000.0,
        "net_asset_value_per_share": 19.53
    }]
    return pd.DataFrame(data)


def get_mock_valid_investment_df() -> pd.DataFrame:
    """Create a valid investment panel DataFrame with borrower multiplicity."""
    # 10 positions across 6 unique borrowers, total fair value = 25,000,000.0
    # Borrower Multiplicity: 6 unique < 10 rows
    positions = [
        # Borrower A: 2 positions
        {"borrower_name": "Acme Software Corp", "investment_type": "First Lien Senior Secured Loan", "fair_value": 3000000.0, "maturity_date": "2029-06-30"},
        {"borrower_name": "Acme Software Corp", "investment_type": "Second Lien Senior Secured Loan", "fair_value": 1500000.0, "maturity_date": "2030-06-30"},
        # Borrower B: 2 positions
        {"borrower_name": "Apex Healthcare LLC", "investment_type": "First Lien Senior Secured Loan", "fair_value": 4000000.0, "maturity_date": "2028-12-31"},
        {"borrower_name": "Apex Healthcare LLC", "investment_type": "Preferred Equity", "fair_value": 1000000.0, "maturity_date": None},
        # Borrower C: 2 positions
        {"borrower_name": "Beacon Logistics Inc", "investment_type": "First Lien Senior Secured Loan", "fair_value": 3500000.0, "maturity_date": "2029-03-31"},
        {"borrower_name": "Beacon Logistics Inc", "investment_type": "Subordinated Debt", "fair_value": 1500000.0, "maturity_date": "2030-03-31"},
        # Borrower D: 2 positions
        {"borrower_name": "Cascade Digital Group", "investment_type": "First Lien Senior Secured Loan", "fair_value": 3000000.0, "maturity_date": "2028-09-30"},
        {"borrower_name": "Cascade Digital Group", "investment_type": "Common Equity", "fair_value": 500000.0, "maturity_date": None},
        # Borrower E: 1 position
        {"borrower_name": "Delta Energy Services", "investment_type": "First Lien Senior Secured Loan", "fair_value": 4000000.0, "maturity_date": "2029-11-30"},
        # Borrower F: 1 position
        {"borrower_name": "Echo Industrial Systems", "investment_type": "First Lien Senior Secured Loan", "fair_value": 3000000.0, "maturity_date": "2028-05-31"},
    ]

    rows = []
    for pos in positions:
        row = {
            "bdc_name": "Ares Capital Corporation",
            "bdc_ticker": "ARCC",
            "cik": "0001279495",
            "period_end_date": "2024-09-30",
            "filing_date": "2024-10-30",
            "borrower_name": pos["borrower_name"],
            "industry": "Software & Tech",
            "investment_category": "First Lien",
            "investment_type": pos["investment_type"],
            "interest_rate_type": "Floating",
            "reference_rate": "SOFR",
            "spread_bps": 575.0,
            "interest_floor_pct": 1.0,
            "total_coupon_rate_pct": 10.75,
            "is_pik": False,
            "is_non_accrual": False,
            "maturity_date": pos["maturity_date"],
            "unit": "USD_THOUSANDS",
            "principal_amount": pos["fair_value"],
            "amortized_cost": pos["fair_value"],
            "fair_value": pos["fair_value"],
            "pct_of_net_assets": (pos["fair_value"] / 12500000.0) * 100.0
        }
        rows.append(row)

    return pd.DataFrame(rows)


class TestFundPanelValidation(unittest.TestCase):
    """Test suite for Fund Panel acceptance criteria."""

    def test_valid_fund_panel(self):
        fund_df = get_mock_valid_fund_df()
        errors, details = validate_fund_panel(fund_df)
        self.assertEqual(len(errors), 0, f"Expected 0 errors, got: {errors}")

    def test_missing_required_column(self):
        fund_df = get_mock_valid_fund_df()
        fund_df = fund_df.drop(columns=["total_assets"])
        errors, _ = validate_fund_panel(fund_df)
        self.assertTrue(any("Missing required columns" in e and "total_assets" in e for e in errors))

    def test_mandatory_field_null(self):
        for mandatory_col in ["bdc_name", "cik", "period_end_date", "filing_date", "total_assets", "total_liabilities", "net_assets", "unit"]:
            fund_df = get_mock_valid_fund_df()
            fund_df.loc[0, mandatory_col] = None
            errors, _ = validate_fund_panel(fund_df)
            self.assertTrue(
                any(f"Mandatory field '{mandatory_col}'" in e for e in errors),
                f"Failed to catch null in {mandatory_col}"
            )

    def test_mandatory_field_empty_string(self):
        fund_df = get_mock_valid_fund_df()
        fund_df.loc[0, "bdc_name"] = "   "
        errors, _ = validate_fund_panel(fund_df)
        self.assertTrue(any("Mandatory field 'bdc_name'" in e for e in errors))

    def test_accounting_identity_exact_balance(self):
        fund_df = get_mock_valid_fund_df()
        fund_df.loc[0, "total_assets"] = 1000.0
        fund_df.loc[0, "total_liabilities"] = 600.0
        fund_df.loc[0, "net_assets"] = 400.0
        errors, details = validate_fund_panel(fund_df)
        self.assertEqual(len(errors), 0)
        self.assertEqual(details["row_0_accounting_diff"], 0.0)

    def test_accounting_identity_rounding_within_tolerance(self):
        fund_df = get_mock_valid_fund_df()
        # 600.0 + 400.4 = 1000.4 vs total assets 1000.0 -> diff = 0.4 (< 1.0)
        fund_df.loc[0, "total_assets"] = 1000.0
        fund_df.loc[0, "total_liabilities"] = 600.0
        fund_df.loc[0, "net_assets"] = 400.4
        errors, details = validate_fund_panel(fund_df)
        self.assertEqual(len(errors), 0)
        self.assertAlmostEqual(details["row_0_accounting_diff"], 0.4, places=2)

    def test_accounting_identity_violation_fails(self):
        fund_df = get_mock_valid_fund_df()
        # 600.0 + 405.0 = 1005.0 vs total assets 1000.0 -> diff = 5.0 (>= 1.0)
        fund_df.loc[0, "total_assets"] = 1000.0
        fund_df.loc[0, "total_liabilities"] = 600.0
        fund_df.loc[0, "net_assets"] = 405.0
        errors, _ = validate_fund_panel(fund_df)
        self.assertTrue(any("Accounting identity violation" in e for e in errors))

    def test_invalid_date_format(self):
        fund_df = get_mock_valid_fund_df()
        fund_df.loc[0, "period_end_date"] = "09/30/2024"  # Non YYYY-MM-DD
        errors, _ = validate_fund_panel(fund_df)
        self.assertTrue(any("Invalid date format" in e and "period_end_date" in e for e in errors))


class TestInvestmentPanelValidation(unittest.TestCase):
    """Test suite for Investment Panel acceptance criteria."""

    def test_valid_investment_panel(self):
        inv_df = get_mock_valid_investment_df()
        errors, details = validate_investment_panel(inv_df)
        self.assertEqual(len(errors), 0, f"Expected 0 errors, got: {errors}")
        self.assertEqual(details["total_positions"], 10)
        self.assertEqual(details["unique_borrowers"], 6)

    def test_missing_required_column(self):
        inv_df = get_mock_valid_investment_df()
        inv_df = inv_df.drop(columns=["fair_value"])
        errors, _ = validate_investment_panel(inv_df)
        self.assertTrue(any("Missing required columns" in e and "fair_value" in e for e in errors))

    def test_mandatory_field_null(self):
        for mandatory_col in ["bdc_name", "period_end_date", "borrower_name", "investment_type", "fair_value", "unit"]:
            inv_df = get_mock_valid_investment_df()
            inv_df.loc[2, mandatory_col] = None
            errors, _ = validate_investment_panel(inv_df)
            self.assertTrue(
                any(f"Mandatory field '{mandatory_col}'" in e for e in errors),
                f"Failed to catch null in {mandatory_col}"
            )

    def test_borrower_multiplicity_pass(self):
        # 10 rows, 6 unique borrowers -> unique < rows -> PASS
        inv_df = get_mock_valid_investment_df()
        errors, details = validate_investment_panel(inv_df)
        self.assertEqual(len(errors), 0)
        self.assertLess(details["unique_borrowers"], details["total_positions"])

    def test_borrower_multiplicity_violation_all_unique(self):
        # If every row has a distinct borrower name, unique == rows -> FAIL
        inv_df = get_mock_valid_investment_df()
        for i in range(len(inv_df)):
            inv_df.loc[i, "borrower_name"] = f"Unique Borrower {i}"
        errors, _ = validate_investment_panel(inv_df)
        self.assertTrue(any("Borrower multiplicity check failed" in e for e in errors))

    def test_insufficient_rows_for_multiplicity(self):
        inv_df = get_mock_valid_investment_df().iloc[:1]
        errors, _ = validate_investment_panel(inv_df)
        self.assertTrue(any("Insufficient rows" in e for e in errors))

    def test_invalid_maturity_date_format(self):
        inv_df = get_mock_valid_investment_df()
        inv_df.loc[0, "maturity_date"] = "2029/06/30"
        errors, _ = validate_investment_panel(inv_df)
        self.assertTrue(any("Invalid date format" in e and "maturity_date" in e for e in errors))


class TestCrossTableValidation(unittest.TestCase):
    """Test suite for cross-table reconciliation and consistency."""

    def test_exact_fair_value_reconciliation(self):
        fund_df = get_mock_valid_fund_df()
        inv_df = get_mock_valid_investment_df()
        errors, metrics = validate_cross_table(fund_df, inv_df)
        self.assertEqual(len(errors), 0)
        self.assertTrue(metrics.reconciliation_passed)
        self.assertAlmostEqual(metrics.fair_value_abs_diff, 0.0)

    def test_fair_value_reconciliation_within_tolerance(self):
        # 0.05% discrepancy (below 0.1% threshold)
        fund_df = get_mock_valid_fund_df()
        inv_df = get_mock_valid_investment_df()
        # Change fund total from 25,000,000 to 25,012,000 (diff = 12,000 -> 0.048%)
        fund_df.loc[0, "total_investments_fair_value"] = 25012000.0
        errors, metrics = validate_cross_table(fund_df, inv_df)
        self.assertEqual(len(errors), 0)
        self.assertTrue(metrics.reconciliation_passed)
        self.assertLess(metrics.fair_value_rel_diff_pct, 0.1)

    def test_fair_value_reconciliation_exceeds_tolerance(self):
        # 0.5% discrepancy (exceeds 0.1% threshold)
        fund_df = get_mock_valid_fund_df()
        inv_df = get_mock_valid_investment_df()
        # Change fund total to 25,200,000 (diff = 200,000 -> 0.79%)
        fund_df.loc[0, "total_investments_fair_value"] = 25200000.0
        errors, metrics = validate_cross_table(fund_df, inv_df)
        self.assertFalse(metrics.reconciliation_passed)
        self.assertTrue(any("Fair value reconciliation failed" in e for e in errors))

    def test_date_and_entity_mismatch_date(self):
        fund_df = get_mock_valid_fund_df()
        inv_df = get_mock_valid_investment_df()
        inv_df["period_end_date"] = "2024-06-30"  # Mismatch with fund 2024-09-30
        errors, _ = validate_cross_table(fund_df, inv_df)
        self.assertTrue(any("Date & Entity Consistency" in e for e in errors))

    def test_date_and_entity_mismatch_cik(self):
        fund_df = get_mock_valid_fund_df()
        inv_df = get_mock_valid_investment_df()
        inv_df["cik"] = "0009999999"
        errors, _ = validate_cross_table(fund_df, inv_df)
        self.assertTrue(any("Date & Entity Consistency" in e for e in errors))


class TestUnitConsistency(unittest.TestCase):
    """Test suite for currency unit uniformity."""

    def test_matching_units_pass(self):
        fund_df = get_mock_valid_fund_df()
        inv_df = get_mock_valid_investment_df()
        errors, metrics = validate_cross_table(fund_df, inv_df)
        self.assertTrue(metrics.unit_consistency_passed)

    def test_mismatched_units_fail(self):
        fund_df = get_mock_valid_fund_df()
        inv_df = get_mock_valid_investment_df()
        inv_df["unit"] = "USD"  # Fund is USD_THOUSANDS
        errors, metrics = validate_cross_table(fund_df, inv_df)
        self.assertFalse(metrics.unit_consistency_passed)
        self.assertTrue(any("Unit mismatch" in e for e in errors))

    def test_mixed_units_within_investment_panel(self):
        fund_df = get_mock_valid_fund_df()
        inv_df = get_mock_valid_investment_df()
        inv_df.loc[0, "unit"] = "USD"
        inv_df.loc[1, "unit"] = "USD_THOUSANDS"
        errors, _ = validate_cross_table(fund_df, inv_df)
        self.assertTrue(any("Investment panel does not have a single uniform unit" in e for e in errors))


class TestEndToEndValidationAndAtomicExport(unittest.TestCase):
    """Test full validation workflow, report generation, and atomic export / cleanup."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.output_dir = Path(self.temp_dir) / "output"
        self.note_dir = Path(self.temp_dir) / "note"
        self.output_dir.mkdir(parents=True)
        self.note_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_full_validation_success(self):
        fund_df = get_mock_valid_fund_df()
        inv_df = get_mock_valid_investment_df()

        is_valid, metrics = validate_datasets(fund_df, inv_df)
        self.assertTrue(is_valid)
        self.assertEqual(len(metrics.errors), 0)

        output_files = export_atomic(fund_df, inv_df, self.output_dir, self.note_dir, metrics)

        # Verify all expected files exist
        self.assertTrue((self.output_dir / "bdc_quarter_fund_panel.csv").exists())
        self.assertTrue((self.output_dir / "bdc_quarter_fund_panel.parquet").exists())
        self.assertTrue((self.output_dir / "bdc_quarter_investment_panel.csv").exists())
        self.assertTrue((self.output_dir / "bdc_quarter_investment_panel.parquet").exists())
        self.assertTrue((self.note_dir / "validation_report.md").exists())

        # Check report content
        report_text = (self.note_dir / "validation_report.md").read_text()
        self.assertIn("Overall Status**: `PASSED`", report_text)
        self.assertIn("Balance Sheet Accounting Identity", report_text)
        self.assertIn("Schedule of Investments (SOI) vs. Balance Sheet Reconciliation", report_text)
        self.assertIn("Portfolio Diversity & Multiplicity Metrics", report_text)

    def test_fail_closed_cleanup(self):
        # Create dummy partial files
        dummy_fund = self.output_dir / "bdc_quarter_fund_panel.csv"
        dummy_fund.write_text("partial corrupt content")
        self.assertTrue(dummy_fund.exists())

        clean_output_dir(self.output_dir, ["bdc_quarter_fund_panel.csv"])
        self.assertFalse(dummy_fund.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
