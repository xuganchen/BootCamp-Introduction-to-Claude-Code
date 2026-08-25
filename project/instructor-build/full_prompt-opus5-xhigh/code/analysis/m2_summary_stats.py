"""Module 2 - Summary statistics: the descriptive core of the ARCC report.

Covers 2018Q3-2026Q2 (30 quarters actually present; 2019Q3 and 2022Q1 are
absent from the panel because their filings failed the parse gate, and are
shown as gaps, never interpolated).

Sections
  (a) portfolio scale at three snapshots + change over the window
  (b) position-size distribution and top-10 / top-25 borrower concentration
  (c) cost vs fair value: aggregate mark and position-level markdown tails
  (d) non-accruals at cost and at fair value
  (e) fair-value-weighted effective yield, pooled and by year

Convention: every composition statistic is weighted by fair_value unless the
label says equal-weight. Every percentage names its denominator.

Run: python3 code/analysis/m2_summary_stats.py   (from the project root)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    Coverage, load_panels, save_fig, save_table, dump_exhibit_log,
    pct_axis, usd_axis, quarter_ticks,
    NAVY, TEAL, AMBER, RUST, SAGE, SLATE, LIGHT, WINDOW_LABEL,
)

PERIOD = WINDOW_LABEL
Q_TOTAL = None   # in-window quarter rows, set after load
I_TOTAL = None   # in-window investment rows, set after load

FIRST_Q = "2018Q3"
MID_Q = "2022Q3"     # index 14 of the 30 in-window quarters (the midpoint)
LAST_Q = "2026Q2"

# The full 32-quarter calendar the window spans.  The panel has only 30 of
# these; 2019Q3 and 2022Q1 are absent.  Every time-series figure is plotted
# against this calendar, never against the 30 quarters that happen to exist,
# so the x axis stays linear in time and a missing quarter becomes a visible
# break in the line rather than a segment drawn straight across it.
FULL_Q = [str(p) for p in pd.period_range(FIRST_Q, LAST_Q, freq="Q")]

# Three 10-K filings whose non-accrual footnote marker was not captured by the
# parser.  Asserted in section_d so that a genuinely clean quarter can never be
# deleted silently by the "zero flags" rule.
KNOWN_NON_ACCRUAL_PARSE_GAPS = ["2022Q4", "2023Q4", "2024Q4"]


def on_calendar(quarters, values) -> pd.Series:
    """Align a per-quarter series onto ``FULL_Q``, NaN in the gaps.

    matplotlib breaks a line at NaN, which is what the exhibits claim to do
    for 2019Q3 / 2022Q1 (and, in section d, for the three parse-gap 10-Ks).
    """
    return pd.Series(list(values), index=list(quarters)).reindex(FULL_Q)


# ------------------------------------------------------------------ (a)

def section_a(q: pd.DataFrame, inv: pd.DataFrame) -> dict:
    """Portfolio scale at three snapshots plus the window change."""
    qq = q.set_index("quarter")
    pos = inv.groupby("quarter").agg(
        position_count=("position_id", "size"),
        distinct_borrowers=("borrower", "nunique"),
    )

    rows = []
    for lab in (FIRST_Q, MID_Q, LAST_Q):
        r = qq.loc[lab]
        nav_ps = r["net_assets"] / r["shares_outstanding"]
        rows.append({
            "metric_quarter": lab,
            "total_investments_fv_usd_bn": r["total_investments_fv"] / 1e9,
            "total_assets_usd_bn": r["total_assets"] / 1e9,
            "net_assets_usd_bn": r["net_assets"] / 1e9,
            "total_debt_outstanding_usd_bn": r["total_debt_outstanding"] / 1e9,
            "shares_outstanding_mm": r["shares_outstanding"] / 1e6,
            "nav_per_share_derived_usd": nav_ps,
            "position_count": int(pos.loc[lab, "position_count"]),
            "distinct_borrowers": int(pos.loc[lab, "distinct_borrowers"]),
        })
    snap = pd.DataFrame(rows).set_index("metric_quarter").T
    snap.columns = [f"{c}" for c in snap.columns]
    snap["pct_change_2018Q3_to_2026Q2"] = 100.0 * (
        snap[LAST_Q] / snap[FIRST_Q] - 1.0)
    out = snap.reset_index().rename(columns={"index": "metric"})

    cov = Coverage(
        basis="quarter-panel",
        rows_used=3,
        rows_total=Q_TOTAL,
        note=("Three snapshot quarters out of the 30 in-window quarters. "
              "Position and borrower counts come from the 31,067-row investment "
              "panel restricted to those same three quarters. "
              "NAV per share is derived as net_assets / shares_outstanding "
              "because the filed nav_per_share field is 90% null in this panel."),
    )
    vals = {
        "total_investments_fv_2018Q3_usd_bn": round(float(snap.loc["total_investments_fv_usd_bn", FIRST_Q]), 2),
        "total_investments_fv_2026Q2_usd_bn": round(float(snap.loc["total_investments_fv_usd_bn", LAST_Q]), 2),
        "total_investments_fv_pct_change_2018Q3_2026Q2": round(float(snap.loc["total_investments_fv_usd_bn", "pct_change_2018Q3_to_2026Q2"]), 1),
        "net_assets_2026Q2_usd_bn": round(float(snap.loc["net_assets_usd_bn", LAST_Q]), 2),
        "net_assets_pct_change_2018Q3_2026Q2": round(float(snap.loc["net_assets_usd_bn", "pct_change_2018Q3_to_2026Q2"]), 1),
        "nav_per_share_2018Q3_usd_derived": round(float(snap.loc["nav_per_share_derived_usd", FIRST_Q]), 2),
        "nav_per_share_2026Q2_usd_derived": round(float(snap.loc["nav_per_share_derived_usd", LAST_Q]), 2),
        "nav_per_share_pct_change_2018Q3_2026Q2": round(float(snap.loc["nav_per_share_derived_usd", "pct_change_2018Q3_to_2026Q2"]), 1),
        "position_count_2018Q3": int(snap.loc["position_count", FIRST_Q]),
        "position_count_2026Q2": int(snap.loc["position_count", LAST_Q]),
        "distinct_borrowers_2018Q3": int(snap.loc["distinct_borrowers", FIRST_Q]),
        "distinct_borrowers_2026Q2": int(snap.loc["distinct_borrowers", LAST_Q]),
        "shares_outstanding_pct_change_2018Q3_2026Q2": round(float(snap.loc["shares_outstanding_mm", "pct_change_2018Q3_to_2026Q2"]), 1),
        "snapshot_quarters": [FIRST_Q, MID_Q, LAST_Q],
        "units_note": "usd_bn = billions of US dollars; mm = millions of shares; pct_change in percent",
    }
    save_table(out, "m2_a_scale_snapshots",
               "Portfolio scale at three snapshots",
               PERIOD, cov,
               note=("NAV per share is derived as net_assets / shares_outstanding. "
                     "Percentage change is 2018Q3 to 2026Q2, the first and last "
                     "in-window quarters."),
               values=vals)

    # Figure: scale over the window, gaps left open.
    order = list(q["quarter"])
    fig, ax = plt.subplots(figsize=(7.2, 3.9))
    for col, colr, lab in ((("total_assets"), NAVY, "Total assets"),
                           ("total_investments_fv", TEAL, "Investments at fair value"),
                           ("net_assets", SAGE, "Net assets"),
                           ("total_debt_outstanding", AMBER, "Debt outstanding")):
        ax.plot(FULL_Q, on_calendar(order, q[col] / 1e9), color=colr, label=lab)
    ax.set_ylabel("USD bn")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"${v:,.0f}bn"))
    quarter_ticks(ax, FULL_Q, every=4)
    ax.legend(ncol=2, loc="upper left")
    figcov = Coverage("quarter-panel", len(q), Q_TOTAL,
                      note=("The x axis is the full 32-quarter calendar. 2019Q3 and "
                            "2022Q1 are missing from the panel and appear as breaks "
                            "in every line; they are never interpolated."))
    save_fig(fig, "m2_a_scale_timeseries",
             "Balance-sheet scale, ARCC",
             PERIOD, figcov,
             subtitle="Quarterly levels, USD bn; 2019Q3 and 2022Q1 absent",
             values={
                 "total_assets_2026Q2_usd_bn": round(float(q.iloc[-1]["total_assets"] / 1e9), 2),
                 "total_assets_2018Q3_usd_bn": round(float(q.iloc[0]["total_assets"] / 1e9), 2),
                 "debt_to_net_assets_2026Q2_x": round(float(q.iloc[-1]["total_debt_outstanding"] / q.iloc[-1]["net_assets"]), 2),
                 "debt_to_net_assets_2018Q3_x": round(float(q.iloc[0]["total_debt_outstanding"] / q.iloc[0]["net_assets"]), 2),
                 "quarters_plotted": len(q),
             })

    # Figure: derived NAV per share
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    navps = q["net_assets"] / q["shares_outstanding"]
    ax.plot(FULL_Q, on_calendar(order, navps), color=NAVY, marker="o", markersize=2.6)
    ax.set_ylabel("USD per share")
    quarter_ticks(ax, FULL_Q, every=4)
    filed = q["nav_per_share"].notna().sum()
    navcov = Coverage("quarter-panel", len(q), Q_TOTAL,
                      note=(f"Derived as net_assets / shares_outstanding for all "
                            f"{len(q)} in-window quarters; the filed nav_per_share "
                            f"field is populated in only {filed} of them. Plotted on "
                            "the full 32-quarter calendar, so 2019Q3 and 2022Q1 are "
                            "breaks in the line, not interpolated points."))
    save_fig(fig, "m2_a_nav_per_share",
             "NAV per share, derived",
             PERIOD, navcov,
             subtitle="net_assets divided by shares_outstanding, USD",
             values={
                 "nav_per_share_2018Q3_usd": round(float(navps.iloc[0]), 2),
                 "nav_per_share_min_usd": round(float(navps.min()), 2),
                 "nav_per_share_min_quarter": order[int(navps.idxmin())],
                 "nav_per_share_max_usd": round(float(navps.max()), 2),
                 "nav_per_share_max_quarter": order[int(navps.idxmax())],
                 "nav_per_share_2026Q2_usd": round(float(navps.iloc[-1]), 2),
                 "filed_nav_per_share_quarters_populated": int(filed),
                 "quarters": len(q),
             })
    return vals


# ------------------------------------------------------------------ (b)

def _dist(s: pd.Series) -> dict:
    return {
        "n": int(s.size),
        "mean_usd_mm": s.mean() / 1e6,
        "p10_usd_mm": s.quantile(0.10) / 1e6,
        "p25_usd_mm": s.quantile(0.25) / 1e6,
        "median_usd_mm": s.median() / 1e6,
        "p75_usd_mm": s.quantile(0.75) / 1e6,
        "p90_usd_mm": s.quantile(0.90) / 1e6,
        "p99_usd_mm": s.quantile(0.99) / 1e6,
        "max_usd_mm": s.max() / 1e6,
    }


def section_b(inv: pd.DataFrame) -> dict:
    pooled = _dist(inv["fair_value"])
    latest = _dist(inv.loc[inv["quarter"] == LAST_Q, "fair_value"])
    tab = pd.DataFrame([{"sample": f"Pooled {PERIOD}", **pooled},
                        {"sample": f"Latest quarter {LAST_Q}", **latest}])
    cov = Coverage("investment-panel", len(inv), I_TOTAL,
                   note=("Position size is fair_value, which is 0% null, so the "
                         "pooled row uses every in-window position. The latest-quarter "
                         f"row uses the {latest['n']:,} positions dated {LAST_Q}. "
                         "These are equal-weight distributional statistics of position "
                         "size; the concentration exhibits below are fair-value-weighted."))
    valsb1 = {
        "pooled_positions_n": pooled["n"],
        "pooled_mean_position_usd_mm": round(pooled["mean_usd_mm"], 2),
        "pooled_median_position_usd_mm": round(pooled["median_usd_mm"], 2),
        "pooled_p90_position_usd_mm": round(pooled["p90_usd_mm"], 2),
        "pooled_p99_position_usd_mm": round(pooled["p99_usd_mm"], 2),
        "pooled_max_position_usd_mm": round(pooled["max_usd_mm"], 2),
        "latest_positions_n": latest["n"],
        "latest_mean_position_usd_mm": round(latest["mean_usd_mm"], 2),
        "latest_median_position_usd_mm": round(latest["median_usd_mm"], 2),
        "latest_p99_position_usd_mm": round(latest["p99_usd_mm"], 2),
        "latest_max_position_usd_mm": round(latest["max_usd_mm"], 2),
        "units_note": "usd_mm = millions of US dollars of fair value per position",
    }
    save_table(tab, "m2_b_position_size_distribution",
               "Position size at fair value: distribution",
               PERIOD, cov,
               note=("Equal-weight across positions. Denominator for the pooled row "
                     f"is all {pooled['n']:,} in-window positions; for the latest row, "
                     f"the {latest['n']:,} positions in {LAST_Q}."),
               values=valsb1)

    # Concentration per quarter, fair-value weighted.
    recs = []
    for qtr, g in inv.groupby("quarter"):
        by_b = g.groupby("borrower")["fair_value"].sum().sort_values(ascending=False)
        tot = by_b.sum()
        recs.append({
            "quarter": qtr,
            "borrowers": int(by_b.size),
            "portfolio_fv_usd_bn": tot / 1e9,
            "top10_share_pct": 100.0 * by_b.head(10).sum() / tot,
            "top25_share_pct": 100.0 * by_b.head(25).sum() / tot,
            "largest_borrower_share_pct": 100.0 * by_b.iloc[0] / tot,
            "largest_borrower": by_b.index[0],
        })
    conc = pd.DataFrame(recs).sort_values("quarter").reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    cq = list(conc["quarter"])
    ax.plot(FULL_Q, on_calendar(cq, conc["top25_share_pct"]), color=NAVY,
            label="Top 25 borrowers")
    ax.plot(FULL_Q, on_calendar(cq, conc["top10_share_pct"]), color=TEAL,
            label="Top 10 borrowers")
    ax.plot(FULL_Q, on_calendar(cq, conc["largest_borrower_share_pct"]), color=AMBER,
            label="Largest single borrower")
    pct_axis(ax, 0)
    ax.set_ylabel("Share of portfolio fair value")
    ax.set_ylim(0, max(45, conc["top25_share_pct"].max() * 1.15))
    quarter_ticks(ax, FULL_Q, every=4)
    ax.legend(ncol=3, loc="upper right")
    ccov = Coverage("investment-panel", len(inv), I_TOTAL,
                    note=("Shares are fair-value-weighted; the denominator each quarter "
                          "is that quarter's total position fair value, which ties to the "
                          "filed total_investments_fv within 0.01%. Borrowers are grouped "
                          "on the raw borrower string, which is internally consistent "
                          "within a quarter but is not reconciled across quarters, so a "
                          "borrower renamed between filings would be double-counted. "
                          "Plotted on the full 32-quarter calendar; 2019Q3 and 2022Q1 "
                          "are breaks."))
    valsb2 = {
        "top10_share_2018Q3_pct": round(float(conc.iloc[0]["top10_share_pct"]), 1),
        "top10_share_2026Q2_pct": round(float(conc.iloc[-1]["top10_share_pct"]), 1),
        "top25_share_2018Q3_pct": round(float(conc.iloc[0]["top25_share_pct"]), 1),
        "top25_share_2026Q2_pct": round(float(conc.iloc[-1]["top25_share_pct"]), 1),
        "top10_share_min_pct": round(float(conc["top10_share_pct"].min()), 1),
        "top10_share_max_pct": round(float(conc["top10_share_pct"].max()), 1),
        "largest_borrower_share_2026Q2_pct": round(float(conc.iloc[-1]["largest_borrower_share_pct"]), 1),
        "largest_borrower_2026Q2": str(conc.iloc[-1]["largest_borrower"]),
        "borrowers_2018Q3": int(conc.iloc[0]["borrowers"]),
        "borrowers_2026Q2": int(conc.iloc[-1]["borrowers"]),
        "denominator": "quarter's total position fair value",
    }
    save_fig(fig, "m2_b_concentration",
             "Borrower concentration",
             PERIOD, ccov,
             subtitle="Top-10 / top-25 borrower share of portfolio fair value, by quarter",
             values=valsb2)

    save_table(conc, "m2_b_concentration_by_quarter",
               "Borrower concentration by quarter",
               PERIOD, ccov,
               note="Fair-value-weighted. Denominator is each quarter's total position fair value.",
               values=valsb2)
    return valsb1 | valsb2


# ------------------------------------------------------------------ (c)

def section_c(inv: pd.DataFrame) -> dict:
    agg = inv.groupby("quarter").agg(fv=("fair_value", "sum"),
                                     cost=("cost", "sum"))
    agg["fv_over_cost_pct"] = 100.0 * agg["fv"] / agg["cost"]
    agg = agg.reset_index().sort_values("quarter")

    # Position-level FV/cost needs a positive cost basis.
    pos = inv[inv["cost"] > 0].copy()
    pos["fv_cost"] = pos["fair_value"] / pos["cost"]
    dropped = len(inv) - len(pos)

    recs = []
    for qtr, g in pos.groupby("quarter"):
        tot_fv = g["fair_value"].sum()
        b90 = g["fv_cost"] < 0.90
        b70 = g["fv_cost"] < 0.70
        recs.append({
            "quarter": qtr,
            "positions_with_cost_gt0": int(len(g)),
            "share_positions_below_90pct_of_cost": 100.0 * b90.mean(),
            "share_fv_below_90pct_of_cost": 100.0 * g.loc[b90, "fair_value"].sum() / tot_fv,
            "share_positions_below_70pct_of_cost": 100.0 * b70.mean(),
            "share_fv_below_70pct_of_cost": 100.0 * g.loc[b70, "fair_value"].sum() / tot_fv,
            "median_fv_over_cost_pct": 100.0 * g["fv_cost"].median(),
        })
    marks = pd.DataFrame(recs).sort_values("quarter").reset_index(drop=True)
    marks = marks.merge(agg[["quarter", "fv_over_cost_pct"]], on="quarter")

    cov_agg = Coverage("investment-panel", len(inv), I_TOTAL,
                       note=("Aggregate mark uses every in-window position: both cost "
                             "and fair_value are 0% null. Denominator each quarter is "
                             "that quarter's total cost. Plotted on the full 32-quarter "
                             "calendar; 2019Q3 and 2022Q1 are breaks in the line."))
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    ax.plot(FULL_Q, on_calendar(agg["quarter"], agg["fv_over_cost_pct"]), color=NAVY)
    ax.axhline(100, color=SLATE, linewidth=0.8, linestyle="--")
    pct_axis(ax, 0)
    ax.set_ylabel("Fair value as % of cost")
    quarter_ticks(ax, FULL_Q, every=4)
    valsc1 = {
        "fv_over_cost_2018Q3_pct": round(float(agg.iloc[0]["fv_over_cost_pct"]), 1),
        "fv_over_cost_2026Q2_pct": round(float(agg.iloc[-1]["fv_over_cost_pct"]), 1),
        "fv_over_cost_min_pct": round(float(agg["fv_over_cost_pct"].min()), 1),
        "fv_over_cost_min_quarter": str(agg.loc[agg["fv_over_cost_pct"].idxmin(), "quarter"]),
        "fv_over_cost_max_pct": round(float(agg["fv_over_cost_pct"].max()), 1),
        "fv_over_cost_max_quarter": str(agg.loc[agg["fv_over_cost_pct"].idxmax(), "quarter"]),
        "quarters_above_100pct": int((agg["fv_over_cost_pct"] > 100).sum()),
        "quarters_total": int(len(agg)),
        "denominator": "aggregate cost of all positions in the quarter",
    }
    save_fig(fig, "m2_c_fv_over_cost",
             "Aggregate mark: fair value over cost",
             PERIOD, cov_agg,
             subtitle="Portfolio fair value as a percent of portfolio cost, by quarter",
             values=valsc1)

    # Positions marked at exactly zero fair value against a positive cost are a
    # large part of the deepest tail (they are, by construction, below 70% of
    # cost).  They are overwhelmingly unfunded/expired commitments rather than
    # impaired credit, so the count has to be disclosed with the exhibit.
    zero_fv = int((pos["fair_value"] == 0).sum())
    cov_pos = Coverage("investment-panel", len(pos), I_TOTAL,
                       note=(f"{dropped:,} in-window positions carry a zero cost basis "
                             "(unfunded commitments and undrawn revolvers) and are "
                             "excluded because FV/cost is undefined for them; no position "
                             "has a negative cost. Position shares are equal-weight; "
                             "fair-value shares are fair-value-weighted, with each "
                             f"quarter's included fair value as the denominator. {zero_fv:,} "
                             "of the included positions are marked at exactly zero fair "
                             "value and therefore fall in the below-70% band by "
                             "construction; they lift the position-count tail far more "
                             "than the fair-value tail, which is why the two lines "
                             "diverge in the deep tail."))
    mq = list(marks["quarter"])
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    for col, colr, lab in (
            ("share_fv_below_90pct_of_cost", RUST, "Share of fair value below 90% of cost"),
            ("share_positions_below_90pct_of_cost", AMBER, "Share of positions below 90% of cost"),
            ("share_fv_below_70pct_of_cost", NAVY, "Share of fair value below 70% of cost"),
            ("share_positions_below_70pct_of_cost", TEAL, "Share of positions below 70% of cost")):
        ax.plot(FULL_Q, on_calendar(mq, marks[col]), color=colr, label=lab)
    pct_axis(ax, 0)
    ax.set_ylabel("Percent")
    quarter_ticks(ax, FULL_Q, every=4)
    ax.set_ylim(0, marks["share_positions_below_90pct_of_cost"].max() * 1.45)
    ax.legend(ncol=2, loc="upper right")
    valsc2 = {
        "positions_with_positive_cost": int(len(pos)),
        "positions_excluded_nonpositive_cost": int(dropped),
        "share_fv_below_90_2020Q2_pct": round(float(marks.loc[marks.quarter == "2020Q2", "share_fv_below_90pct_of_cost"].iloc[0]), 1),
        "share_positions_below_90_2020Q2_pct": round(float(marks.loc[marks.quarter == "2020Q2", "share_positions_below_90pct_of_cost"].iloc[0]), 1),
        "share_fv_below_90_2026Q2_pct": round(float(marks.iloc[-1]["share_fv_below_90pct_of_cost"]), 1),
        "share_positions_below_90_2026Q2_pct": round(float(marks.iloc[-1]["share_positions_below_90pct_of_cost"]), 1),
        "share_fv_below_70_2026Q2_pct": round(float(marks.iloc[-1]["share_fv_below_70pct_of_cost"]), 1),
        "share_positions_below_70_2026Q2_pct": round(float(marks.iloc[-1]["share_positions_below_70pct_of_cost"]), 1),
        "share_fv_below_90_max_pct": round(float(marks["share_fv_below_90pct_of_cost"].max()), 1),
        "share_fv_below_90_max_quarter": str(marks.loc[marks["share_fv_below_90pct_of_cost"].idxmax(), "quarter"]),
        "positions_marked_at_zero_fair_value": zero_fv,
    }
    save_fig(fig, "m2_c_markdown_tails",
             "Markdown tails: positions carried below cost",
             PERIOD, cov_pos,
             subtitle="Share of positions and of fair value marked below 90% and below 70% of cost",
             values=valsc2)

    save_table(marks, "m2_c_mark_by_quarter",
               "Cost versus fair value by quarter",
               PERIOD, cov_pos,
               note=("fv_over_cost_pct uses all positions; the below-90 and below-70 "
                     "columns use only positions with a positive cost basis."),
               values=valsc1 | valsc2)
    return valsc1 | valsc2


# ------------------------------------------------------------------ (d)

def section_d(inv: pd.DataFrame) -> dict:
    # Three annual filings (2022Q4, 2023Q4, 2024Q4 10-Ks) carry zero parsed
    # non-accrual flags while every neighbouring 10-Q reports 1% to 2% of cost
    # on non-accrual.  ARCC's non-accrual footnote marker was not captured in
    # those three filings, so the zeros are a parse gap, not a clean book.
    # They are dropped from the series rather than plotted as zeros.
    zero_q = sorted(inv.groupby("quarter")["is_non_accrual"].sum().pipe(
        lambda s: s[s == 0]).index)
    # Fail loudly rather than silently deleting a quarter that is genuinely
    # clean: the "zero flags" rule is only a licence to drop the three filings
    # we have diagnosed as a parse gap.
    assert list(zero_q) == KNOWN_NON_ACCRUAL_PARSE_GAPS, (
        "quarters with zero non-accrual flags changed: "
        f"{zero_q} vs known parse gaps {KNOWN_NON_ACCRUAL_PARSE_GAPS}. "
        "Re-diagnose before dropping them.")
    kept = inv[~inv["quarter"].isin(zero_q)]

    recs = []
    for qtr, g in kept.groupby("quarter"):
        na = g["is_non_accrual"]
        recs.append({
            "quarter": qtr,
            "positions": int(len(g)),
            "non_accrual_positions": int(na.sum()),
            "non_accrual_share_of_positions_pct": 100.0 * na.mean(),
            "non_accrual_share_of_fv_pct": 100.0 * g.loc[na, "fair_value"].sum() / g["fair_value"].sum(),
            "non_accrual_share_of_cost_pct": 100.0 * g.loc[na, "cost"].sum() / g["cost"].sum(),
            "non_accrual_fv_usd_mm": g.loc[na, "fair_value"].sum() / 1e6,
            "non_accrual_cost_usd_mm": g.loc[na, "cost"].sum() / 1e6,
        })
    na_q = pd.DataFrame(recs).sort_values("quarter").reset_index(drop=True)

    cov = Coverage("investment-panel", len(kept), I_TOTAL,
                   note=("is_non_accrual is a parsed flag with no nulls, so every "
                         "position in the quarters shown is classified. Denominators "
                         "are, per quarter, that quarter's position count, total fair "
                         "value and total cost. Dropped: "
                         + ", ".join(zero_q) +
                         " return exactly zero non-accrual flags while the surrounding "
                         "10-Qs report 1% to 2% of cost on non-accrual, so the flag was "
                         "not captured in those three 10-K filings; they are omitted "
                         "rather than shown as zeros, and appear as breaks in the "
                         "lines, alongside the breaks at 2019Q3 and 2022Q1. Any pooled "
                         "non-accrual share quoted from this exhibit is over the 27,588 "
                         "positions in the 27 usable quarters, not over all 31,067 "
                         "in-window positions."))
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    nq = list(na_q["quarter"])
    for col, colr, lab in (
            ("non_accrual_share_of_cost_pct", RUST, "Share of cost"),
            ("non_accrual_share_of_fv_pct", NAVY, "Share of fair value"),
            ("non_accrual_share_of_positions_pct", SLATE, "Share of positions (equal-weight)")):
        ax.plot(FULL_Q, on_calendar(nq, na_q[col]), color=colr, label=lab)
    pct_axis(ax, 0)
    ax.set_ylabel("Percent of portfolio")
    quarter_ticks(ax, FULL_Q, every=4)
    ax.legend(ncol=3, loc="upper left")
    # Pooled share: the numerator can only come from the 27 usable quarters, so
    # the denominator must be those same 27 quarters.  Dividing 562 flags by all
    # 31,067 in-window rows would silently credit the three parse-gap 10-Ks with
    # a clean book and understate the rate.
    tot_na = int(kept["is_non_accrual"].sum())
    vals = {
        "non_accrual_positions_pooled": tot_na,
        "non_accrual_positions_denominator": int(len(kept)),
        "non_accrual_share_of_positions_pooled_pct": round(100.0 * tot_na / len(kept), 2),
        "non_accrual_share_of_positions_pooled_all_rows_pct": round(
            100.0 * int(inv["is_non_accrual"].sum()) / len(inv), 2),
        "pooled_denominator_note": (
            "Pooled share is 562 of the 27,588 positions in the 27 quarters with a "
            "usable non-accrual flag. The 31,067-row denominator (1.81%) is shown "
            "only for reconciliation and understates the rate, because the three "
            "parse-gap 10-Ks contribute rows but no flags."),
        "non_accrual_share_of_cost_2026Q2_pct": round(float(na_q.iloc[-1]["non_accrual_share_of_cost_pct"]), 2),
        "non_accrual_share_of_fv_2026Q2_pct": round(float(na_q.iloc[-1]["non_accrual_share_of_fv_pct"]), 2),
        "non_accrual_share_of_positions_2026Q2_pct": round(float(na_q.iloc[-1]["non_accrual_share_of_positions_pct"]), 2),
        "non_accrual_share_of_cost_max_pct": round(float(na_q["non_accrual_share_of_cost_pct"].max()), 2),
        "non_accrual_share_of_cost_max_quarter": str(na_q.loc[na_q["non_accrual_share_of_cost_pct"].idxmax(), "quarter"]),
        "non_accrual_share_of_fv_max_pct": round(float(na_q["non_accrual_share_of_fv_pct"].max()), 2),
        "non_accrual_share_of_fv_max_quarter": str(na_q.loc[na_q["non_accrual_share_of_fv_pct"].idxmax(), "quarter"]),
        "non_accrual_fv_2026Q2_usd_mm": round(float(na_q.iloc[-1]["non_accrual_fv_usd_mm"]), 1),
        "non_accrual_cost_2026Q2_usd_mm": round(float(na_q.iloc[-1]["non_accrual_cost_usd_mm"]), 1),
        "non_accrual_recovery_mark_2026Q2_pct_of_cost": round(
            100.0 * float(na_q.iloc[-1]["non_accrual_fv_usd_mm"]) / float(na_q.iloc[-1]["non_accrual_cost_usd_mm"]), 1)
        if float(na_q.iloc[-1]["non_accrual_cost_usd_mm"]) > 0 else None,
        "denominator": "per quarter: position count, total fair value, total cost",
        "quarters_shown": int(len(na_q)),
        "quarters_dropped_zero_flag": list(zero_q),
    }
    save_fig(fig, "m2_d_non_accruals",
             "Non-accrual positions",
             PERIOD, cov,
             subtitle="Share of cost, of fair value, and of position count, by quarter",
             values=vals)

    save_table(na_q, "m2_d_non_accruals_by_quarter",
               "Non-accruals by quarter",
               PERIOD, cov,
               note=("Non-accrual at cost exceeds non-accrual at fair value in every "
                     "quarter where any exists, because the same positions are already "
                     "written down. The gap is the informative quantity."),
               values=vals)
    return vals


# ------------------------------------------------------------------ (e)

def section_e(inv: pd.DataFrame) -> dict:
    r = inv[inv["all_in_rate_pct"].notna()].copy()

    def wavg(g):
        return np.average(g["all_in_rate_pct"], weights=g["fair_value"])

    # By year
    recs = []
    inv_y = inv.assign(year=inv["period_end"].dt.year)
    r_y = r.assign(year=r["period_end"].dt.year)
    for yr, g in r_y.groupby("year"):
        allg = inv_y[inv_y["year"] == yr]
        recs.append({
            "year": int(yr),
            "positions_with_rate": int(len(g)),
            "positions_total": int(len(allg)),
            "rate_coverage_share_of_positions_pct": 100.0 * len(g) / len(allg),
            "rate_coverage_share_of_fv_pct": 100.0 * g["fair_value"].sum() / allg["fair_value"].sum(),
            "fv_weighted_all_in_rate_pct": wavg(g),
            "equal_weighted_all_in_rate_pct": g["all_in_rate_pct"].mean(),
        })
    by_year = pd.DataFrame(recs)

    pooled_w = wavg(r)
    pooled_cov_pos = 100.0 * len(r) / len(inv)
    pooled_cov_fv = 100.0 * r["fair_value"].sum() / inv["fair_value"].sum()

    # Quarterly series for the figure
    qrecs = []
    for qtr, g in r.groupby("quarter"):
        allg = inv[inv["quarter"] == qtr]
        qrecs.append({
            "quarter": qtr,
            "fv_weighted_all_in_rate_pct": wavg(g),
            "rate_coverage_share_of_fv_pct": 100.0 * g["fair_value"].sum() / allg["fair_value"].sum(),
        })
    by_q = pd.DataFrame(qrecs).sort_values("quarter").reset_index(drop=True)

    cov = Coverage("investment-panel", len(r), I_TOTAL,
                   note=(f"all_in_rate_pct is null on {100.0*(1-len(r)/len(inv)):.1f}% of "
                         "in-window positions, concentrated in equity and preferred "
                         "positions that carry no coupon. Rates are weighted by the fair "
                         "value of the rate-bearing positions only, which is "
                         f"{pooled_cov_fv:.1f}% of in-window fair value. Positions with "
                         "a null rate are dropped from the numerator and the weight, "
                         "never treated as a zero rate; the lower panel of the figure "
                         "and the coverage columns of the table state exactly how much "
                         "fair value is behind each point. Plotted on the full "
                         "32-quarter calendar, so 2019Q3 and 2022Q1 are breaks."))
    fig, (ax, ax2) = plt.subplots(
        2, 1, figsize=(7.2, 4.4), sharex=True,
        gridspec_kw={"height_ratios": [2.2, 1.0], "hspace": 0.18})
    eq_ = list(by_q["quarter"])
    ax.plot(FULL_Q, on_calendar(eq_, by_q["fv_weighted_all_in_rate_pct"]), color=NAVY)
    pct_axis(ax, 1)
    ax.set_ylabel("FV-weighted all-in rate")
    ax2.plot(FULL_Q, on_calendar(eq_, by_q["rate_coverage_share_of_fv_pct"]), color=SLATE)
    pct_axis(ax2, 0)
    ax2.set_ylim(0, 100)
    ax2.set_ylabel("Coverage:\nshare of FV\nwith a rate")
    quarter_ticks(ax2, FULL_Q, every=4)
    vals = {
        "pooled_fv_weighted_all_in_rate_pct": round(float(pooled_w), 2),
        "pooled_equal_weighted_all_in_rate_pct": round(float(r["all_in_rate_pct"].mean()), 2),
        "pooled_rate_coverage_share_of_positions_pct": round(pooled_cov_pos, 1),
        "pooled_rate_coverage_share_of_fv_pct": round(pooled_cov_fv, 1),
        "fv_weighted_rate_2019_pct": round(float(by_year.loc[by_year.year == 2019, "fv_weighted_all_in_rate_pct"].iloc[0]), 2),
        "fv_weighted_rate_2021_pct": round(float(by_year.loc[by_year.year == 2021, "fv_weighted_all_in_rate_pct"].iloc[0]), 2),
        "fv_weighted_rate_2023_pct": round(float(by_year.loc[by_year.year == 2023, "fv_weighted_all_in_rate_pct"].iloc[0]), 2),
        "fv_weighted_rate_2026_pct": round(float(by_year.loc[by_year.year == 2026, "fv_weighted_all_in_rate_pct"].iloc[0]), 2),
        "fv_weighted_rate_2026Q2_pct": round(float(by_q.iloc[-1]["fv_weighted_all_in_rate_pct"]), 2),
        "rate_coverage_share_of_fv_2026Q2_pct": round(float(by_q.iloc[-1]["rate_coverage_share_of_fv_pct"]), 1),
        "fv_weighted_rate_peak_pct": round(float(by_q["fv_weighted_all_in_rate_pct"].max()), 2),
        "fv_weighted_rate_peak_quarter": str(by_q.loc[by_q["fv_weighted_all_in_rate_pct"].idxmax(), "quarter"]),
        "fv_weighted_rate_trough_pct": round(float(by_q["fv_weighted_all_in_rate_pct"].min()), 2),
        "fv_weighted_rate_trough_quarter": str(by_q.loc[by_q["fv_weighted_all_in_rate_pct"].idxmin(), "quarter"]),
        "denominator": "fair value of rate-bearing positions in the period",
    }
    save_fig(fig, "m2_e_effective_yield",
             "Effective yield and its coverage",
             PERIOD, cov,
             subtitle="Fair-value-weighted all-in rate, with the share of fair value that reports one",
             values=vals)

    save_table(by_year, "m2_e_yield_by_year",
               "Effective yield by year",
               PERIOD, cov,
               note=("2018 and 2026 are partial years (2018Q3-2018Q4 and "
                     "2026Q1-2026Q2). The coverage columns give the denominator "
                     "behind each yield."),
               values=vals)
    return vals


# ------------------------------------------------------- data-quality note

def section_quality(inv: pd.DataFrame) -> dict:
    cols = ["reference_rate", "spread_bps", "all_in_rate_pct", "maturity_date",
            "principal_amount", "shares_units", "pct_of_net_assets", "cost",
            "fair_value", "borrower", "industry", "investment_type"]
    rows = []
    for c in cols:
        null = inv[c].isna()
        rows.append({
            "column": c,
            "null_share_of_positions_pct": 100.0 * null.mean(),
            "null_share_of_fair_value_pct": 100.0 * inv.loc[null, "fair_value"].sum() / inv["fair_value"].sum(),
            "null_share_within_equity_and_preferred_pct": 100.0 * null[inv["investment_type"].isin(["equity", "preferred"])].mean(),
            "null_share_within_debt_like_pct": 100.0 * null[inv["debt_like"]].mean(),
        })
    dq = pd.DataFrame(rows)
    n_eq = int(inv["investment_type"].isin(["equity", "preferred"]).sum())
    n_debt = int(inv["debt_like"].sum())
    cov = Coverage("investment-panel", len(inv), I_TOTAL,
                   note=(f"All in-window positions. Denominators: {len(inv):,} positions "
                         f"overall, {n_eq:,} equity or preferred positions, {n_debt:,} "
                         "debt-like (first lien, second lien, subordinated) positions."))
    vals = {
        "raw_industry_labels": int(inv["industry"].nunique()),
        "normalized_industry_labels": int(inv["industry_norm"].nunique()),
        "all_in_rate_null_share_pct": round(100.0 * inv["all_in_rate_pct"].isna().mean(), 1),
        "all_in_rate_null_share_within_equity_preferred_pct": round(
            100.0 * inv.loc[inv["investment_type"].isin(["equity", "preferred"]), "all_in_rate_pct"].isna().mean(), 1),
        "all_in_rate_null_share_within_debt_like_pct": round(
            100.0 * inv.loc[inv["debt_like"], "all_in_rate_pct"].isna().mean(), 1),
        "maturity_null_share_within_equity_preferred_pct": round(
            100.0 * inv.loc[inv["investment_type"].isin(["equity", "preferred"]), "maturity_date"].isna().mean(), 1),
        "maturity_null_share_within_debt_like_pct": round(
            100.0 * inv.loc[inv["debt_like"], "maturity_date"].isna().mean(), 1),
        "pct_of_net_assets_null_share_pct": round(100.0 * inv["pct_of_net_assets"].isna().mean(), 1),
        "equity_and_preferred_positions": n_eq,
        "debt_like_positions": n_debt,
        "in_window_positions": int(len(inv)),
    }
    save_table(dq, "m2_f_missingness",
               "Missingness by field and by position type",
               PERIOD, cov,
               note=("Missingness is not random: rate and maturity fields are absent by "
                     "construction on equity and preferred positions. pct_of_net_assets "
                     "is 100% null and is never used."),
               values=vals)
    return vals


# ------------------------------------------------------------------ main

def main() -> int:
    global Q_TOTAL, I_TOTAL
    q, inv = load_panels()
    Q_TOTAL, I_TOTAL = len(q), len(inv)
    print(f"in-window quarter rows={Q_TOTAL}, investment rows={I_TOTAL:,}")
    assert Q_TOTAL == 30 and I_TOTAL == 31067, "unexpected window row counts"
    missing = sorted(set(pd.period_range("2018Q3", "2026Q2", freq="Q").astype(str))
                     - set(q["quarter"]))
    print("missing quarters in window:", missing)

    a = section_a(q, inv)
    b = section_b(inv)
    c = section_c(inv)
    d = section_d(inv)
    e = section_e(inv)
    f = section_quality(inv)

    # ---- independent recomputations (different code path) ----
    # 1. NAV per share, latest quarter, straight from the CSV.
    raw = pd.read_csv(Path(__file__).resolve().parents[2] / "output/panel/bdc_quarter.csv")
    row = raw[raw.period_end.astype(str).str.startswith("2026-06")].iloc[0]
    chk = row.net_assets / row.shares_outstanding
    assert abs(chk - a["nav_per_share_2026Q2_usd_derived"]) < 0.01, (chk, a)
    print(f"check NAV/share 2026Q2 recomputed from raw CSV = {chk:.4f} "
          f"(table says {a['nav_per_share_2026Q2_usd_derived']}); filed field = {row.nav_per_share}")

    # 2. Pooled FV-weighted all-in rate, recomputed with a manual sum.
    rawi = pd.read_csv(Path(__file__).resolve().parents[2] / "output/panel/bdc_quarter_investment.csv",
                       low_memory=False)
    rawi["period_end"] = pd.to_datetime(rawi["period_end"])
    rw = rawi[(rawi.period_end >= "2018-01-01") & (rawi.period_end <= "2026-12-31")]
    rw = rw[rw.all_in_rate_pct.notna()]
    manual = (rw.all_in_rate_pct * rw.fair_value).sum() / rw.fair_value.sum()
    assert abs(manual - e["pooled_fv_weighted_all_in_rate_pct"]) < 0.01, (manual, e)
    print(f"check pooled FV-weighted all-in rate manual = {manual:.4f}% "
          f"(table says {e['pooled_fv_weighted_all_in_rate_pct']}%)")

    # 3. Non-accrual pooled share.
    na = rawi[(rawi.period_end >= "2018-01-01") & (rawi.period_end <= "2026-12-31")]
    na_n = na.is_non_accrual.astype(str).str.lower().eq("true").sum()
    assert na_n == d["non_accrual_positions_pooled"] == 562, (na_n, d)
    print(f"check non-accrual positions = {na_n} of {len(na):,}")

    dump_exhibit_log("m2_summary_stats")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
