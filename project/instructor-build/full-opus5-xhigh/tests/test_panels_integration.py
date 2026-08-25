"""Integration tests: the REAL panels against independently derived ground truth.

Nothing here reads the parser's source. Every expected figure comes from
tests/expected_values.json, which was derived from the filing HTML, the
filing's inline XBRL, and the SEC companyfacts API before the panels existed.

If the parser is not finished, every test in this file skips with a message
that says exactly which file is missing.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import bdc_08_checks as G

ROOT = Path(__file__).resolve().parent.parent
INTERIM = ROOT / "data" / "interim"
QUARTER_CSV = INTERIM / "bdc_quarter.csv"
INVESTMENT_CSV = INTERIM / "bdc_quarter_investment.csv"

# 0.1 percent, the tolerance plan_v1 section 4 uses for the tie-outs and the
# XBRL cross-check. Applied here to every money figure.
TOL = 0.001


def _require_panels():
    missing = [str(p) for p in (QUARTER_CSV, INVESTMENT_CSV) if not p.exists()]
    if missing:
        pytest.skip("parser output not present yet; missing: " + ", ".join(missing))


@pytest.fixture(scope="module")
def panels():
    _require_panels()
    return pd.read_csv(QUARTER_CSV), pd.read_csv(INVESTMENT_CSV)


@pytest.fixture(scope="module")
def qrow(panels):
    q, _ = panels
    assert len(q) == 1, f"expected exactly one bdc_quarter row for one filing, got {len(q)}"
    return q.iloc[0]


@pytest.fixture(scope="module")
def real_context(manifest):
    return G.build_context()


def close(actual, expected, tol=TOL):
    a, e = G._num(actual), float(expected)
    assert a is not None, f"value is null, expected {e:,.2f}"
    rel = G._rel_diff(a, e)
    assert rel <= tol, (
        f"actual={a:,.2f} expected={e:,.2f} abs_diff={abs(a - e):,.2f} "
        f"rel_diff={rel * 100:.6f}% tolerance={tol * 100:.4f}%"
    )


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

def test_identity_fields_match_the_filing(qrow, filing_meta):
    assert int(qrow["cik"]) == filing_meta["cik"]
    assert str(qrow["accession"]).strip() == filing_meta["accession"]
    assert str(qrow["form_type"]).strip() == filing_meta["form_type"]
    assert G._as_date(qrow["period_end"]) == date(2026, 6, 30)
    assert G._as_date(qrow["filing_date"]) == date(2026, 7, 29)


def test_source_scale_is_recorded_as_millions(qrow, expected):
    assert str(qrow["source_scale"]).strip().lower() == expected["source_scale"]["value"]


def test_comparative_date_was_read_not_inferred(qrow):
    """2025-12-31, the prior fiscal year end, NOT 2026-03-31."""
    assert G._as_date(qrow["period_end_prior"]) == date(2025, 12, 31), (
        "period_end_prior must be the December 31, 2025 column header from the "
        "filing. 2026-03-31 would mean it was computed as period_end minus one quarter."
    )
    assert str(qrow["period_end_prior_kind"]).strip() == "prior_fiscal_year_end"


# ---------------------------------------------------------------------------
# Current column vs independently derived values
# ---------------------------------------------------------------------------

CURRENT_FIELDS = [
    ("total_investments_fv", "total_investments_fv"),
    ("total_assets", "total_assets"),
    ("total_liabilities", "total_liabilities"),
    ("net_assets", "net_assets"),
]


@pytest.mark.parametrize("panel_field,truth_key", CURRENT_FIELDS)
def test_current_column_matches_ground_truth(qrow, expected, panel_field, truth_key):
    close(qrow[panel_field], expected["current"][truth_key]["value"])


@pytest.mark.parametrize("panel_field,truth_key", CURRENT_FIELDS)
def test_prior_column_matches_ground_truth(qrow, expected, panel_field, truth_key):
    close(qrow[f"{panel_field}_prior"], expected["prior"][truth_key]["value"])


def test_nav_per_share_matches_ground_truth(qrow, expected):
    if G._isnull(qrow.get("nav_per_share")):
        pytest.skip("nav_per_share is nullable per plan 3.1 and was not extracted")
    close(qrow["nav_per_share"], expected["current"]["nav_per_share"]["value"], tol=0.0005)
    close(qrow["nav_per_share_prior"], expected["prior"]["nav_per_share"]["value"], tol=0.0005)


def test_shares_outstanding_is_in_units_not_millions(qrow, expected):
    if G._isnull(qrow.get("shares_outstanding")):
        pytest.skip("shares_outstanding is nullable per plan 3.1 and was not extracted")
    sh = float(qrow["shares_outstanding"])
    assert sh > 1e8, (
        f"shares_outstanding={sh:,.0f} looks like the filing's '718' left in millions; "
        f"the panel stores counts in units"
    )
    close(sh, expected["current"]["shares_outstanding"]["value"])


def test_total_debt_matches_one_of_the_two_reported_figures(qrow, expected):
    if G._isnull(qrow.get("total_debt_outstanding")):
        pytest.skip("total_debt_outstanding is nullable per plan 3.1 and was not extracted")
    truth = expected["current"]["total_debt_outstanding"]
    candidates = [truth["value"], truth["acceptable_alternative"]]
    actual = float(qrow["total_debt_outstanding"])
    assert any(G._close(actual, c, TOL) for c in candidates), (
        f"total_debt_outstanding={actual:,.2f} matches neither the balance-sheet "
        f"'Debt' line {candidates[0]:,.2f} nor the debt-note carrying amount "
        f"{candidates[1]:,.2f}"
    )


def test_the_panel_did_not_take_the_comparative_column(qrow, expected):
    """The single failure mode plan 3.1 calls out by name."""
    prior_ta = expected["prior"]["total_assets"]["value"]
    assert not G._close(float(qrow["total_assets"]), prior_ta, TOL), (
        f"total_assets equals the December 31, 2025 figure {prior_ta:,.2f}; "
        f"the comparative column was labelled as current"
    )


# ---------------------------------------------------------------------------
# The tie-outs, against ground truth rather than against the panel's own total
# ---------------------------------------------------------------------------

def test_soi_fair_value_sums_to_independently_derived_total(panels, expected):
    _, inv = panels
    target = expected["tie_out_targets"]["sum_investment_fair_value"]["value"]
    total = float(pd.to_numeric(inv["fair_value"], errors="coerce").fillna(0).sum())
    close(total, target)


def test_soi_fair_value_does_not_tie_to_the_prior_column(panels, expected):
    _, inv = panels
    prior = expected["prior"]["total_investments_fv"]["value"]
    total = float(pd.to_numeric(inv["fair_value"], errors="coerce").fillna(0).sum())
    assert not G._close(total, prior, TOL), (
        f"the SOI sums to the December 31, 2025 total {prior:,.2f}: "
        f"the current/prior column map is inverted"
    )


def test_soi_cost_sums_to_independently_derived_total(panels, expected):
    _, inv = panels
    if "cost" not in inv.columns:
        pytest.fail("investment panel has no cost column; plan 3.2 requires one")
    target = expected["tie_out_targets"]["sum_investment_cost"]["value"]
    total = float(pd.to_numeric(inv["cost"], errors="coerce").fillna(0).sum())
    close(total, target)


def test_investment_panel_has_many_positions(panels):
    _, inv = panels
    # ARCC's 2026 Q2 Schedule of Investments carries thousands of positions;
    # us-gaap:InvestmentOwnedAtFairValue is tagged 3,812 times at 2026-06-30.
    assert len(inv) > 500, (
        f"only {len(inv)} position rows; the ARCC SOI is far larger than that, "
        f"so rows were dropped or only subtotals were captured"
    )
    assert len(inv) > inv["borrower"].nunique()


def test_no_subtotal_rows_leaked_into_the_panel(panels, expected):
    _, inv = panels
    total = expected["current"]["total_investments_fv"]["value"]
    biggest = float(pd.to_numeric(inv["fair_value"], errors="coerce").max())
    assert biggest < 0.20 * total, (
        f"largest single position is {biggest:,.2f}, over 20% of the "
        f"{total:,.2f} portfolio; that is a subtotal row, not a position"
    )


# ---------------------------------------------------------------------------
# Schema conformance
# ---------------------------------------------------------------------------

def test_quarter_panel_has_the_full_schema(panels):
    q, _ = panels
    missing = [c for c in G.QUARTER_REQUIRED + G.QUARTER_NULLABLE if c not in q.columns]
    assert not missing, f"bdc_quarter is missing columns: {missing}"


def test_investment_panel_has_the_full_schema(panels):
    _, inv = panels
    required = G.INVESTMENT_REQUIRED + [
        "industry", "reference_rate", "spread_bps", "all_in_rate_pct",
        "maturity_date", "principal_amount", "cost", "pct_of_net_assets",
    ]
    missing = [c for c in required if c not in inv.columns]
    assert not missing, f"bdc_quarter_investment is missing columns: {missing}"


def test_is_subtotal_row_is_not_in_the_panel(panels):
    """plan 3.2: is_subtotal_row is a parsing artifact, kept out of the panel."""
    _, inv = panels
    assert "is_subtotal_row" not in inv.columns


def test_position_id_is_unique(panels):
    _, inv = panels
    dupes = inv["position_id"].duplicated().sum()
    assert dupes == 0, f"{dupes} duplicated position_id values"


# ---------------------------------------------------------------------------
# The gate itself, on the real panels
# ---------------------------------------------------------------------------

def test_full_gate_is_green_on_the_real_panels(panels, real_context):
    q, inv = panels
    results = G.run_all_checks(q, inv, real_context)
    print(G.format_report(results))
    failures = [f"check {r.id} ({r.name}): {r.message} | " + " | ".join(r.details)
                for r in results if r.status == G.FAIL]
    assert not failures, "\n".join(failures)


def test_gate_reports_all_sixteen_checks(panels, real_context):
    q, inv = panels
    results = G.run_all_checks(q, inv, real_context)
    assert {r.id for r in results} == set(range(1, 17))


def test_check_15_actually_compared_something(panels, real_context):
    """Guard against check 15 quietly degrading to a no-op."""
    q, inv = panels
    r = G.check_15_xbrl_crosscheck(q, inv, real_context)
    assert r.status != G.SKIP, f"check 15 could not evaluate: {r.message}"
    assert "comparison(s)" in r.message


def test_check_14_condition_is_met_for_this_filing(panels, real_context):
    q, inv = panels
    r = G.check_14_cost_tieout(q, inv, real_context)
    assert r.status != G.SKIP, (
        "ARCC's 2026 Q2 balance sheet reports 'amortized cost of $29,675', so the "
        f"condition for check 14 IS met. The gate said: {r.message}"
    )


# ---------------------------------------------------------------------------
# The gate's own reference extraction, independent of any panel
# ---------------------------------------------------------------------------

def test_gate_derives_the_balance_sheet_columns_from_the_filing(manifest):
    doc = manifest.get("doc_path")
    if not doc or not Path(doc).exists():
        pytest.skip("filing not on disk")
    dates = G.bs_column_dates_from_filing(Path(doc))
    assert sorted(dates, reverse=True) == [date(2026, 6, 30), date(2025, 12, 31)]


def test_companyfacts_confirms_the_prior_column(manifest, expected):
    """The one date companyfacts can independently confirm."""
    fp = manifest.get("facts_path")
    if not fp or not Path(fp).exists():
        pytest.skip("companyfacts not on disk")
    facts = json.loads(Path(fp).read_text())
    for tag, key in (("Assets", "total_assets"),
                     ("Liabilities", "total_liabilities"),
                     ("StockholdersEquity", "net_assets")):
        val, prov = G.companyfacts_value(facts, tag, date(2025, 12, 31))
        assert val is not None, prov
        close(val, expected["prior"][key]["value"])
