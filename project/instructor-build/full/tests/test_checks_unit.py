"""Unit tests for the verification gate (plan_v1 section 4, checks 1-16).

Every check gets at least one clean fixture that passes and at least one
deliberately corrupted fixture that makes it FAIL. This is the plan step 6
requirement: a check that cannot fail is not a check.

The corruptions are chosen to look like real parser mistakes, not arbitrary
garbage: a duplicated row, a dropped tranche, a swapped column, a scale error
of 1000x, a subtotal row left in the panel.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

import bdc_08_checks as G


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def run_one(fn, q, inv, ctx) -> G.CheckResult:
    return fn(q, inv, ctx)


def assert_fails(result: G.CheckResult, why: str = ""):
    assert result.status == G.FAIL, (
        f"check {result.id} ({result.name}) did NOT fail on a corrupted fixture. "
        f"status={result.status} message={result.message} {why}"
    )
    assert result.message or result.details, "a failure must report something actionable"


def assert_passes(result: G.CheckResult):
    assert result.status in (G.PASS, G.WARN), (
        f"check {result.id} ({result.name}) failed on a clean fixture: "
        f"{result.message} {result.details}"
    )


def mutate(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
    out = df.copy()
    for k, v in kwargs.items():
        out.loc[out.index[0], k] = v
    return out


# ---------------------------------------------------------------------------
# The clean fixture must pass every check that can be evaluated.
# ---------------------------------------------------------------------------

def test_clean_fixture_passes_the_whole_gate(clean_quarter, clean_investment, clean_context):
    results = G.run_all_checks(clean_quarter, clean_investment, clean_context)
    assert len(results) == 16
    assert {r.id for r in results} == set(range(1, 17))
    failures = [(r.id, r.name, r.message, r.details) for r in results if r.status == G.FAIL]
    assert not failures, f"clean synthetic fixture should pass: {failures}"
    assert G.gate_passed(results)


def test_report_is_renderable(clean_quarter, clean_investment, clean_context):
    txt = G.format_report(G.run_all_checks(clean_quarter, clean_investment, clean_context))
    assert "STATUS" in txt and "pass" in txt


# ---------------------------------------------------------------------------
# 1. uniqueness
# ---------------------------------------------------------------------------

def test_c01_clean(clean_quarter, clean_investment, clean_context):
    assert_passes(G.check_01_quarter_unique(clean_quarter, clean_investment, clean_context))


def test_c01_fails_on_duplicated_key(clean_quarter, clean_investment, clean_context):
    dup = pd.concat([clean_quarter, clean_quarter], ignore_index=True)
    assert_fails(G.check_01_quarter_unique(dup, clean_investment, clean_context))


def test_c01_fails_on_empty_panel(clean_investment, clean_context):
    assert_fails(G.check_01_quarter_unique(pd.DataFrame(), clean_investment, clean_context))


# ---------------------------------------------------------------------------
# 2. never-null
# ---------------------------------------------------------------------------

def test_c02_clean(clean_quarter, clean_investment, clean_context):
    assert_passes(G.check_02_never_null(clean_quarter, clean_investment, clean_context))


@pytest.mark.parametrize("col", ["bdc_name", "accession", "total_assets", "net_assets_prior",
                                 "period_end_prior", "period_end_prior_kind", "source_scale"])
def test_c02_fails_on_null_quarter_field(clean_quarter, clean_investment, clean_context, col):
    bad = mutate(clean_quarter, **{col: None})
    assert_fails(G.check_02_never_null(bad, clean_investment, clean_context), f"col={col}")


@pytest.mark.parametrize("col", ["borrower", "fair_value", "position_id", "investment_type_raw"])
def test_c02_fails_on_null_investment_field(clean_quarter, clean_investment, clean_context, col):
    bad = clean_investment.copy()
    bad.loc[bad.index[0], col] = None
    assert_fails(G.check_02_never_null(clean_quarter, bad, clean_context), f"col={col}")


def test_c02_allows_null_in_nullable_fields(clean_quarter, clean_investment, clean_context):
    q = mutate(clean_quarter, ticker=None, nav_per_share=None, total_debt_outstanding=None)
    inv = clean_investment.copy()
    inv.loc[inv["investment_type"] == "equity", "industry"] = None
    assert_passes(G.check_02_never_null(q, inv, clean_context))


def test_c02_fails_when_a_debt_row_has_no_principal(clean_quarter, clean_investment, clean_context):
    bad = clean_investment.copy()
    idx = bad.index[bad["investment_type"] == "first lien"][0]
    bad.loc[idx, "principal_amount"] = None
    assert_fails(G.check_02_never_null(clean_quarter, bad, clean_context))


def test_c02_allows_equity_row_without_principal(clean_quarter, clean_investment, clean_context):
    assert clean_investment.loc[
        clean_investment["investment_type"] == "equity", "principal_amount"
    ].isna().all()
    assert_passes(G.check_02_never_null(clean_quarter, clean_investment, clean_context))


# ---------------------------------------------------------------------------
# 3. rows > unique borrowers
# ---------------------------------------------------------------------------

def test_c03_clean(clean_quarter, clean_investment, clean_context):
    r = G.check_03_rows_exceed_borrowers(clean_quarter, clean_investment, clean_context)
    assert_passes(r)


def test_c03_fails_when_tranches_were_collapsed(clean_quarter, clean_investment, clean_context):
    # One row per borrower: the classic "groupby borrower" mistake.
    bad = clean_investment.drop_duplicates(subset=["borrower"]).reset_index(drop=True)
    assert_fails(G.check_03_rows_exceed_borrowers(clean_quarter, bad, clean_context))


def test_c03_fails_on_empty_investment_panel(clean_quarter, clean_investment, clean_context):
    empty = clean_investment.iloc[0:0]
    assert_fails(G.check_03_rows_exceed_borrowers(clean_quarter, empty, clean_context))


# ---------------------------------------------------------------------------
# 4. controlled vocabulary
# ---------------------------------------------------------------------------

def test_c04_clean(clean_quarter, clean_investment, clean_context):
    assert_passes(G.check_04_investment_type_vocab(clean_quarter, clean_investment, clean_context))


def test_c04_fails_on_unmapped_value(clean_quarter, clean_investment, clean_context):
    bad = clean_investment.copy()
    bad.loc[bad.index[0], "investment_type"] = "First Lien Senior Secured Loan"
    assert_fails(G.check_04_investment_type_vocab(clean_quarter, bad, clean_context))


def test_c04_fails_when_raw_values_silently_became_other(clean_quarter, clean_investment,
                                                         clean_context):
    inv = clean_investment.copy()
    inv.loc[inv.index[0], "investment_type"] = "other"
    ctx = dict(clean_context, unmapped_investment_types=["Senior Direct Lending Program"])
    assert_fails(G.check_04_investment_type_vocab(clean_quarter, inv, ctx))


# ---------------------------------------------------------------------------
# 5. exactly two dated columns
# ---------------------------------------------------------------------------

def test_c05_clean(clean_quarter, clean_investment, clean_context):
    assert_passes(G.check_05_two_dated_columns(clean_quarter, clean_investment, clean_context))


@pytest.mark.parametrize("dates", [
    [date(2026, 6, 30)],
    [date(2026, 6, 30), date(2025, 12, 31), date(2025, 6, 30)],
])
def test_c05_fails_when_column_count_is_not_two(clean_quarter, clean_investment,
                                                clean_context, dates):
    ctx = dict(clean_context, bs_column_dates=dates, doc_path=None)
    assert_fails(G.check_05_two_dated_columns(clean_quarter, clean_investment, ctx))


def test_c05_fails_when_a_header_date_does_not_parse(clean_quarter, clean_investment,
                                                     clean_context):
    ctx = dict(clean_context, bs_column_dates=[date(2026, 6, 30), "(unaudited)"], doc_path=None)
    assert_fails(G.check_05_two_dated_columns(clean_quarter, clean_investment, ctx))


def test_c05_skips_when_nothing_is_available(clean_quarter, clean_investment, clean_context):
    ctx = dict(clean_context, bs_column_dates=None, doc_path=None)
    r = G.check_05_two_dated_columns(clean_quarter, clean_investment, ctx)
    assert r.status == G.SKIP and "cannot evaluate" in r.message


# ---------------------------------------------------------------------------
# 6. current column == periodOfReport
# ---------------------------------------------------------------------------

def test_c06_clean(clean_quarter, clean_investment, clean_context):
    assert_passes(G.check_06_current_column_equals_period(clean_quarter, clean_investment,
                                                          clean_context))


def test_c06_fails_when_the_comparative_column_was_taken(clean_quarter, clean_investment,
                                                         clean_context):
    """The exact error plan 3.1 warns about: comparative column labelled as current."""
    bad = mutate(clean_quarter, period_end=date(2025, 12, 31), period_end_prior=date(2026, 6, 30))
    assert_fails(G.check_06_current_column_equals_period(bad, clean_investment, clean_context))


def test_c06_fails_on_closest_to_rather_than_equal(clean_quarter, clean_investment, clean_context):
    bad = mutate(clean_quarter, period_end=date(2026, 6, 29))
    assert_fails(G.check_06_current_column_equals_period(bad, clean_investment, clean_context))


def test_c06_fails_when_both_columns_carry_period_end(clean_quarter, clean_investment,
                                                      clean_context):
    bad = mutate(clean_quarter, period_end_prior=date(2026, 6, 30))
    assert_fails(G.check_06_current_column_equals_period(bad, clean_investment, clean_context))


# ---------------------------------------------------------------------------
# 7. prior gap
# ---------------------------------------------------------------------------

def test_c07_clean(clean_quarter, clean_investment, clean_context):
    r = G.check_07_prior_gap(clean_quarter, clean_investment, clean_context)
    assert_passes(r)
    assert "181" in r.message


@pytest.mark.parametrize("prior,label", [
    (date(2026, 5, 31), "gap 30 days, below the 80-day floor"),
    (date(2024, 12, 31), "gap 546 days, above the 380-day ceiling"),
    (date(2026, 6, 30), "prior equals current"),
    (date(2026, 9, 30), "prior after current"),
])
def test_c07_fails_outside_the_window(clean_quarter, clean_investment, clean_context,
                                      prior, label):
    bad = mutate(clean_quarter, period_end_prior=prior)
    assert_fails(G.check_07_prior_gap(bad, clean_investment, clean_context), label)


# ---------------------------------------------------------------------------
# 8. prior kind
# ---------------------------------------------------------------------------

def test_c08_clean(clean_quarter, clean_investment, clean_context):
    r = G.check_08_prior_kind(clean_quarter, clean_investment, clean_context)
    assert r.status == G.PASS


def test_c08_fails_on_unknown_kind(clean_quarter, clean_investment, clean_context):
    bad = mutate(clean_quarter, period_end_prior_kind="prior_period")
    assert_fails(G.check_08_prior_kind(bad, clean_investment, clean_context))


def test_c08_fails_when_label_contradicts_the_date(clean_quarter, clean_investment, clean_context):
    bad = mutate(clean_quarter, period_end_prior=date(2026, 3, 31),
                 period_end_prior_kind="prior_fiscal_year_end")
    assert_fails(G.check_08_prior_kind(bad, clean_investment, clean_context))


def test_c08_fails_when_quarter_label_sits_on_the_fiscal_year_end(clean_quarter, clean_investment,
                                                                  clean_context):
    bad = mutate(clean_quarter, period_end_prior_kind="prior_quarter_end")
    assert_fails(G.check_08_prior_kind(bad, clean_investment, clean_context))


def test_c08_warns_but_does_not_block_on_a_genuine_prior_quarter_end(clean_quarter,
                                                                     clean_investment,
                                                                     clean_context):
    """Plan check 8: prior_quarter_end is allowed but logged as unusual."""
    bad = mutate(clean_quarter, period_end_prior=date(2026, 3, 31),
                 period_end_prior_kind="prior_quarter_end")
    r = G.check_08_prior_kind(bad, clean_investment, clean_context)
    assert r.status == G.WARN
    assert r.ok, "a prior_quarter_end must not block promotion"
    assert any("UNUSUAL" in d for d in r.details)


def test_c08_null_kind_fails(clean_quarter, clean_investment, clean_context):
    assert_fails(G.check_08_prior_kind(mutate(clean_quarter, period_end_prior_kind=None),
                                       clean_investment, clean_context))


# ---------------------------------------------------------------------------
# 9. balance sheet identity
# ---------------------------------------------------------------------------

def test_c09_clean(clean_quarter, clean_investment, clean_context):
    assert_passes(G.check_09_balance_sheet_identity(clean_quarter, clean_investment, clean_context))


def test_c09_fails_on_current_column(clean_quarter, clean_investment, clean_context):
    bad = mutate(clean_quarter, total_liabilities=16_607_000_000.0 * 0.9)
    assert_fails(G.check_09_balance_sheet_identity(bad, clean_investment, clean_context))


def test_c09_fails_on_prior_column_too(clean_quarter, clean_investment, clean_context):
    """A prior-column break is as fatal as a current-column break (plan section 4)."""
    bad = mutate(clean_quarter, net_assets_prior=14_318_000_000.0 - 500_000_000.0)
    assert_fails(G.check_09_balance_sheet_identity(bad, clean_investment, clean_context))


def test_c09_tolerates_rounding_within_five_basis_points(clean_quarter, clean_investment,
                                                         clean_context):
    ta = float(clean_quarter.loc[0, "total_assets"])
    nudge = 0.0004 * ta  # inside max(0.05%, 1 USD)
    ok = mutate(clean_quarter, net_assets=float(clean_quarter.loc[0, "net_assets"]) + nudge)
    assert_passes(G.check_09_balance_sheet_identity(ok, clean_investment, clean_context))


def test_c09_one_dollar_floor_applies_to_tiny_balance_sheets(clean_investment, clean_context):
    q = pd.DataFrame([{"total_assets": 100.0, "total_liabilities": 60.0, "net_assets": 40.4,
                       "total_assets_prior": 100.0, "total_liabilities_prior": 60.0,
                       "net_assets_prior": 40.0}])
    assert_passes(G.check_09_balance_sheet_identity(q, clean_investment, clean_context))


# ---------------------------------------------------------------------------
# 10. nav per share
# ---------------------------------------------------------------------------

def test_c10_clean(clean_quarter, clean_investment, clean_context):
    assert_passes(G.check_10_nav_per_share(clean_quarter, clean_investment, clean_context))


def test_c10_fails_on_share_count_scale_error(clean_quarter, clean_investment, clean_context):
    """Shares left in millions instead of units: 718 rather than 718,000,000."""
    bad = mutate(clean_quarter, shares_outstanding=718.0)
    assert_fails(G.check_10_nav_per_share(bad, clean_investment, clean_context))


def test_c10_fails_on_prior_column(clean_quarter, clean_investment, clean_context):
    bad = mutate(clean_quarter, nav_per_share_prior=25.0)
    assert_fails(G.check_10_nav_per_share(bad, clean_investment, clean_context))


def test_c10_skips_when_both_columns_lack_the_nullable_inputs(clean_quarter, clean_investment,
                                                              clean_context):
    q = mutate(clean_quarter, nav_per_share=None, shares_outstanding=None,
               nav_per_share_prior=None, shares_outstanding_prior=None)
    r = G.check_10_nav_per_share(q, clean_investment, clean_context)
    assert r.status == G.SKIP and r.ok


def test_c10_tolerates_half_a_percent(clean_quarter, clean_investment, clean_context):
    na = float(clean_quarter.loc[0, "net_assets"])
    sh = float(clean_quarter.loc[0, "shares_outstanding"])
    ok = mutate(clean_quarter, nav_per_share=(na / sh) * 1.004)
    assert_passes(G.check_10_nav_per_share(ok, clean_investment, clean_context))


# ---------------------------------------------------------------------------
# 11. columns comparable
# ---------------------------------------------------------------------------

def test_c11_clean(clean_quarter, clean_investment, clean_context):
    assert_passes(G.check_11_columns_comparable(clean_quarter, clean_investment, clean_context))


def test_c11_fails_when_prior_is_not_a_balance_sheet_column(clean_quarter, clean_investment,
                                                            clean_context):
    bad = mutate(clean_quarter, total_assets_prior=299_000_000.0)
    assert_fails(G.check_11_columns_comparable(bad, clean_investment, clean_context))


def test_c11_fails_on_net_assets_too(clean_quarter, clean_investment, clean_context):
    bad = mutate(clean_quarter, net_assets_prior=1_000_000.0)
    assert_fails(G.check_11_columns_comparable(bad, clean_investment, clean_context))


# ---------------------------------------------------------------------------
# 12. columns not identical
# ---------------------------------------------------------------------------

def test_c12_clean(clean_quarter, clean_investment, clean_context):
    assert_passes(G.check_12_columns_not_identical(clean_quarter, clean_investment, clean_context))


def test_c12_fails_when_the_same_column_was_read_twice(clean_quarter, clean_investment,
                                                       clean_context):
    ta = float(clean_quarter.loc[0, "total_assets"])
    bad = mutate(clean_quarter, total_assets_prior=ta)
    assert_fails(G.check_12_columns_not_identical(bad, clean_investment, clean_context))


# ---------------------------------------------------------------------------
# 13. the tie-out
# ---------------------------------------------------------------------------

def test_c13_clean(clean_quarter, clean_investment, clean_context):
    assert_passes(G.check_13_soi_tieout(clean_quarter, clean_investment, clean_context))


def test_c13_fails_on_double_counted_subtotal(clean_quarter, clean_investment, clean_context):
    """Trap 1 from plan section 5: an industry subtotal row left in the panel."""
    bad = pd.concat([clean_investment, clean_investment.iloc[[0]]], ignore_index=True)
    r = G.check_13_soi_tieout(clean_quarter, bad, clean_context)
    assert_fails(r)
    assert any("SOI sum vs balance sheet" in d for d in r.details)


def test_c13_fails_on_a_dropped_position(clean_quarter, clean_investment, clean_context):
    bad = clean_investment.iloc[1:].reset_index(drop=True)
    assert_fails(G.check_13_soi_tieout(clean_quarter, bad, clean_context))


def test_c13_fails_on_a_thousand_x_scale_error(clean_quarter, clean_investment, clean_context):
    bad = clean_investment.copy()
    bad["fair_value"] = bad["fair_value"] / 1000.0
    assert_fails(G.check_13_soi_tieout(clean_quarter, bad, clean_context))


def test_c13_names_an_inverted_column_map(clean_quarter, clean_investment, clean_context):
    """Sum ties to the prior column: the diagnostic must say so."""
    inv = clean_investment.copy()
    prior_total = float(clean_quarter.loc[0, "total_investments_fv_prior"])
    inv.loc[inv.index[0], "fair_value"] = prior_total - float(inv["fair_value"][1:].sum())
    r = G.check_13_soi_tieout(clean_quarter, inv, clean_context)
    assert_fails(r)
    assert any("PRIOR column" in d for d in r.details)


def test_c13_tolerates_one_tenth_of_a_percent(clean_quarter, clean_investment, clean_context):
    inv = clean_investment.copy()
    total = float(clean_quarter.loc[0, "total_investments_fv"])
    inv.loc[inv.index[0], "fair_value"] += 0.0009 * total
    assert_passes(G.check_13_soi_tieout(clean_quarter, inv, clean_context))


def test_c13_rejects_a_two_tenths_percent_gap(clean_quarter, clean_investment, clean_context):
    inv = clean_investment.copy()
    total = float(clean_quarter.loc[0, "total_investments_fv"])
    inv.loc[inv.index[0], "fair_value"] += 0.002 * total
    assert_fails(G.check_13_soi_tieout(clean_quarter, inv, clean_context))


# ---------------------------------------------------------------------------
# 14. the cost tie-out (conditional)
# ---------------------------------------------------------------------------

def test_c14_clean(clean_quarter, clean_investment, clean_context):
    r = G.check_14_cost_tieout(clean_quarter, clean_investment, clean_context)
    assert_passes(r)
    assert any("condition met" in d for d in r.details)


def test_c14_fails_when_costs_do_not_tie(clean_quarter, clean_investment, clean_context):
    bad = clean_investment.copy()
    bad.loc[bad.index[0], "cost"] = float(bad.loc[bad.index[0], "cost"]) * 0.5
    assert_fails(G.check_14_cost_tieout(clean_quarter, bad, clean_context))


def test_c14_reports_the_skipped_condition_explicitly(clean_quarter, clean_investment,
                                                      clean_context):
    """No total cost anywhere: the check must SKIP loudly, not pass quietly."""
    ctx = dict(clean_context, reported_total_cost=None, doc_path=None)
    r = G.check_14_cost_tieout(clean_quarter, clean_investment, ctx)
    assert r.status == G.SKIP
    assert "CONDITION NOT MET" in r.message


def test_c14_flags_null_costs_summed_as_zero(clean_quarter, clean_investment, clean_context):
    bad = clean_investment.copy()
    bad.loc[bad.index[0], "cost"] = None
    r = G.check_14_cost_tieout(clean_quarter, bad, clean_context)
    assert_fails(r)
    assert any("null cost" in d for d in r.details)


# ---------------------------------------------------------------------------
# 15. XBRL cross-check
# ---------------------------------------------------------------------------

def test_c15_clean(clean_quarter, clean_investment, clean_context):
    r = G.check_15_xbrl_crosscheck(clean_quarter, clean_investment, clean_context)
    assert_passes(r)


@pytest.mark.parametrize("col", ["total_assets", "total_liabilities", "net_assets",
                                 "total_assets_prior", "total_liabilities_prior",
                                 "net_assets_prior"])
def test_c15_fails_on_a_thousand_x_scale_error(clean_quarter, clean_investment,
                                               clean_context, col):
    """The failure mode the internal identity cannot see if applied uniformly."""
    bad = clean_quarter.copy()
    for c in ("total_assets", "total_liabilities", "net_assets",
              "total_assets_prior", "total_liabilities_prior", "net_assets_prior"):
        bad.loc[0, c] = float(bad.loc[0, c]) / 1000.0
    # Check 9 still passes on the scaled panel...
    assert_passes(G.check_09_balance_sheet_identity(bad, clean_investment, clean_context))
    # ...and 15 is what catches it.
    assert_fails(G.check_15_xbrl_crosscheck(bad, clean_investment, clean_context), col)


def test_c15_fails_on_a_single_wrong_field(clean_quarter, clean_investment, clean_context):
    bad = mutate(clean_quarter, total_liabilities_prior=16_000_000_000.0)
    assert_fails(G.check_15_xbrl_crosscheck(bad, clean_investment, clean_context))


def test_c15_skips_when_no_reference_data_is_reachable(clean_quarter, clean_investment,
                                                       clean_context):
    ctx = dict(clean_context, doc_path=None, facts_path=None)
    r = G.check_15_xbrl_crosscheck(clean_quarter, clean_investment, ctx)
    assert r.status == G.SKIP


def test_c15_prior_column_is_confirmed_by_companyfacts(clean_quarter, clean_investment,
                                                       clean_context, manifest):
    """companyfacts alone must be enough to pin the 2025-12-31 column."""
    if not manifest.get("facts_path"):
        pytest.skip("no companyfacts on disk")
    ctx = dict(clean_context, doc_path=None)
    assert_passes(G.check_15_xbrl_crosscheck(clean_quarter, clean_investment, ctx))
    bad = mutate(clean_quarter, net_assets_prior=1.0)
    assert_fails(G.check_15_xbrl_crosscheck(bad, clean_investment, ctx))


# ---------------------------------------------------------------------------
# 16. sanity bounds
# ---------------------------------------------------------------------------

def test_c16_clean(clean_quarter, clean_investment, clean_context):
    assert_passes(G.check_16_sanity_bounds(clean_quarter, clean_investment, clean_context))


def test_c16_fails_on_negative_fair_value(clean_quarter, clean_investment, clean_context):
    bad = clean_investment.copy()
    bad.loc[bad.index[0], "fair_value"] = -1.0
    assert_fails(G.check_16_sanity_bounds(clean_quarter, bad, clean_context))


def test_c16_fails_on_absurd_fv_over_cost(clean_quarter, clean_investment, clean_context):
    bad = clean_investment.copy()
    idx = bad.index[bad["investment_type"] == "first lien"][0]
    bad.loc[idx, "cost"] = float(bad.loc[idx, "fair_value"]) / 5.0
    assert_fails(G.check_16_sanity_bounds(clean_quarter, bad, clean_context))


# The window is [period_end - 10y, period_end + 40y]. It was widened from
# [-2y, +30y] after ARCC's 2020 Q1 filing showed both ends occur for real:
# defaulted paper held years past its stated maturity (NECCO, "due 1/2018") and
# 35-year solar securitizations (Sunrun, "due 2/2055"). These fixtures stay far
# enough outside that they can only be mangled dates.
@pytest.mark.parametrize("mat", [date(1995, 1, 1), date(2120, 1, 1)])
def test_c16_fails_on_out_of_window_maturity(clean_quarter, clean_investment, clean_context, mat):
    bad = clean_investment.copy()
    bad.loc[bad.index[0], "maturity_date"] = mat
    assert_fails(G.check_16_sanity_bounds(clean_quarter, bad, clean_context))


@pytest.mark.parametrize("mat", [date(2023, 6, 1), date(2055, 2, 1)])
def test_c16_allows_real_past_due_and_long_dated_maturities(
    clean_quarter, clean_investment, clean_context, mat
):
    """Both ends were verified against the filing text before the bound moved."""
    ok = clean_investment.copy()
    ok.loc[ok.index[0], "maturity_date"] = mat
    assert G.check_16_sanity_bounds(clean_quarter, ok, clean_context).status in (G.PASS, G.WARN)


def test_c16_allows_a_marked_down_but_plausible_debt_row(clean_quarter, clean_investment,
                                                         clean_context):
    ok = clean_investment.copy()
    idx = ok.index[ok["investment_type"] == "second lien"][0]
    ok.loc[idx, "fair_value"] = float(ok.loc[idx, "cost"]) * 0.35
    r = G.check_16_sanity_bounds(clean_quarter, ok, clean_context)
    assert r.status in (G.PASS, G.WARN)


# ---------------------------------------------------------------------------
# gate mechanics: a failure must block promotion
# ---------------------------------------------------------------------------

def test_gate_blocks_output_on_any_failure(tmp_path, clean_quarter, clean_investment,
                                           clean_context, monkeypatch):
    interim, output = tmp_path / "interim", tmp_path / "output"
    interim.mkdir()
    output.mkdir()
    bad = clean_investment.copy()
    bad["fair_value"] = bad["fair_value"] / 1000.0
    clean_quarter.to_csv(interim / "bdc_quarter.csv", index=False)
    bad.to_csv(interim / "bdc_quarter_investment.csv", index=False)
    monkeypatch.setattr(G, "build_context", lambda: clean_context)
    rc = G.main(["--interim", str(interim), "--output", str(output)])
    assert rc == 1
    assert list(output.iterdir()) == [], "output/ must stay empty when the gate fails"


def test_gate_promotes_csv_and_parquet_on_green(tmp_path, clean_quarter, clean_investment,
                                                clean_context, monkeypatch):
    interim, output = tmp_path / "interim", tmp_path / "output"
    interim.mkdir()
    output.mkdir()
    clean_quarter.to_csv(interim / "bdc_quarter.csv", index=False)
    clean_investment.to_csv(interim / "bdc_quarter_investment.csv", index=False)
    monkeypatch.setattr(G, "build_context", lambda: clean_context)
    rc = G.main(["--interim", str(interim), "--output", str(output)])
    assert rc == 0
    names = sorted(p.name for p in output.iterdir())
    assert names == ["bdc_quarter.csv", "bdc_quarter.parquet",
                     "bdc_quarter_investment.csv", "bdc_quarter_investment.parquet"]


def test_gate_returns_two_when_panels_are_missing(tmp_path):
    rc = G.main(["--interim", str(tmp_path), "--output", str(tmp_path / "out")])
    assert rc == 2


def test_a_raising_check_is_a_failure_not_a_pass(clean_quarter, clean_investment,
                                                 clean_context, monkeypatch):
    def boom(q, i, c):
        raise RuntimeError("kaboom")

    boom.__name__ = "check_13_boom"
    monkeypatch.setattr(G, "ALL_CHECKS", [boom])
    results = G.run_all_checks(clean_quarter, clean_investment, clean_context)
    assert results[0].status == G.FAIL and "kaboom" in results[0].message
    assert not G.gate_passed(results)
