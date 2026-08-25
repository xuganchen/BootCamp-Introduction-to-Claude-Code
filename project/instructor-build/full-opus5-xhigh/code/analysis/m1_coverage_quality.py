"""Module 1: sample coverage and data quality for the ARCC BDC panel.

Answers five questions, in this order:

  a) Which calendar quarters between 2018Q1 and 2026Q2 does the panel
     actually cover, and which are absent?  Absent quarters are drawn as
     gaps and are never interpolated.
  b) How many positions does each covered quarter carry, and how fast has
     that grown?
  c) How complete is each column of the investment panel, and does the
     completeness of the four rate/term fields improve or degrade through
     time?
  d) Where does the missingness sit?  Rate and maturity nulls are not
     random: they concentrate in equity and preferred positions.
  e) Weighted by fair value rather than by position count, what share of
     the portfolio in each quarter is carried by positions with a usable
     spread and a usable all-in rate?  Every downstream rate exhibit
     inherits this number.

Plus a balance-sheet identity check on the quarter panel.

Run standalone from the project root:  python3 code/analysis/m1_coverage_quality.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import (
    AMBER, LIGHT, NAVY, PLUM, RUST, SAGE, SLATE, TEAL,
    Coverage, dump_exhibit_log, load_panels, pct_axis, quarter_ticks,
    save_fig, save_table,
)

PERIOD = "2018Q3-2026Q2"
CALENDAR_LABEL = "2018Q1-2026Q2 calendar grid"

# The window label spans 2018Q3-2026Q2 but the panel holds only 30 of the 32
# calendar quarters inside that span (2019Q3 and 2022Q1 are absent).  Any
# pooled exhibit whose period stamp reads "2018Q3-2026Q2" gets this appended
# so the stamp is never read as continuous coverage.
GAP_NOTE = ("The 2018Q3-2026Q2 stamp is not continuous: 30 of the 32 calendar "
            "quarters in that span are present; 2019Q3 and 2022Q1 are absent "
            "from the panel and contribute no rows here.")

# The four fields whose completeness governs every downstream rate exhibit.
RATE_TERM_FIELDS = ["reference_rate", "spread_bps", "all_in_rate_pct", "maturity_date"]


def calendar_quarters(start: str = "2018Q1", end: str = "2026Q2") -> list[str]:
    rng = pd.period_range(start=start, end=end, freq="Q")
    return [str(p) for p in rng]


# ------------------------------------------------------------------ (a)

def fig_filing_coverage(q: pd.DataFrame, inv: pd.DataFrame) -> dict:
    cal = calendar_quarters()
    present = set(q["quarter"])
    absent = [c for c in cal if c not in present]

    counts = inv.groupby("quarter").size()
    fig, ax = plt.subplots(figsize=(7.2, 2.6))
    for k, lab in enumerate(cal):
        year = int(lab[:4])
        col = NAVY if lab in present else LIGHT
        ax.bar(k, 1, color=col, width=0.82, edgecolor="white", linewidth=0.6)
        if lab not in present:
            ax.text(k, 1.12, "x", ha="center", va="bottom", fontsize=7,
                    color=RUST, fontweight="bold")
    ax.set_ylim(0, 2.0)
    ax.set_yticks([])
    ax.grid(False)
    ax.set_xticks(range(len(cal)))
    ax.set_xticklabels([c if c.endswith("Q1") or c.endswith("Q3") else ""
                        for c in cal], rotation=90, fontsize=6.2)
    ax.spines["left"].set_visible(False)
    handles = [plt.Rectangle((0, 0), 1, 1, color=NAVY),
               plt.Rectangle((0, 0), 1, 1, color=LIGHT)]
    ax.legend(handles, [f"filing parsed and in panel ({len(present)})",
                        f"no parsed filing ({len(absent)})"],
              loc="upper center", ncol=2)

    vals = {
        "calendar_quarters_2018Q1_2026Q2_count": len(cal),
        "quarters_present_count": len(present),
        "quarters_absent_count": len(absent),
        "quarters_absent_list": ", ".join(absent),
        "in_window_quarters_first": min(present),
        "in_window_quarters_last": max(present),
        "note_units": "counts of calendar quarters; denominator is the "
                      f"{len(cal)} calendar quarters from 2018Q1 to 2026Q2",
    }
    cov = Coverage(
        basis="quarter-panel",
        rows_used=len(q),
        rows_total=len(q),
        note=(f"{len(present)} of {len(cal)} calendar quarters in 2018Q1-2026Q2 are "
              f"present. Absent: {', '.join(absent)}. Absent quarters are shown as "
              "gaps and are never interpolated."),
    )
    save_fig(fig, "m1_filing_coverage",
             "Filing coverage: parsed quarters vs the calendar",
             CALENDAR_LABEL, cov,
             subtitle=("Each bar is one calendar quarter; grey bars marked x have no "
                       "filing that cleared the parse gate"),
             values=vals)
    return vals


# ------------------------------------------------------------------ (b)

def fig_position_counts(inv: pd.DataFrame) -> dict:
    counts = inv.groupby("quarter").size().sort_index()
    cal = calendar_quarters("2018Q3", "2026Q2")
    series = counts.reindex(cal)  # NaN at 2019Q3 and 2022Q1: a gap, not a zero

    fig, ax = plt.subplots()
    x = np.arange(len(cal))
    ax.plot(x, series.values, color=NAVY, marker="o", markersize=2.6)
    miss = [k for k, c in enumerate(cal) if pd.isna(series.iloc[k])]
    for k in miss:
        ax.axvspan(k - 0.5, k + 0.5, color=LIGHT, alpha=0.55, lw=0)
        ax.text(k, series.max() * 0.06, cal[k], rotation=90, ha="center",
                va="bottom", fontsize=6.2, color=SLATE)
    ax.set_ylabel("positions in the Schedule of Investments")
    ax.set_ylim(0, series.max() * 1.12)
    quarter_ticks(ax, cal, every=4)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    first, last = float(series.iloc[0]), float(series.iloc[-1])
    n_quarters = len(cal) - 1              # 2018Q3 to 2026Q2 = 31 quarter steps
    years = n_quarters / 4.0
    pct_change = 100.0 * (last / first - 1.0)
    cagr = 100.0 * ((last / first) ** (1.0 / years) - 1.0)

    vals = {
        "positions_2018Q3": int(first),
        "positions_2026Q2": int(last),
        "positions_pct_change_2018Q3_to_2026Q2_pct": round(pct_change, 1),
        "positions_cagr_pct_per_year": round(cagr, 2),
        "elapsed_years": years,
        "positions_min_quarter": str(series.idxmin()),
        "positions_min": int(series.min()),
        "positions_max_quarter": str(series.idxmax()),
        "positions_max": int(series.max()),
        "total_in_window_positions": int(len(inv)),
        "note_units": ("counts of position-rows; percentage change and CAGR are "
                       "computed on the 2018Q3 and 2026Q2 endpoints only"),
    }
    cov = Coverage(
        basis="investment-panel",
        rows_used=int(len(inv)),
        rows_total=int(len(inv)),
        note=("All in-window position rows. 2019Q3 and 2022Q1 are shaded as gaps; "
              "no value is interpolated across them."),
    )
    save_fig(fig, "m1_positions_per_quarter",
             "Position count per quarter",
             PERIOD, cov,
             subtitle=(f"{int(first):,} positions in 2018Q3 to {int(last):,} in 2026Q2: "
                       f"+{pct_change:.1f}%, an {cagr:.1f}% CAGR over {years:.2f} years"),
             values=vals)
    return vals


# ------------------------------------------------------------------ (c)

def table_null_share(inv: pd.DataFrame) -> dict:
    raw_cols = ["cik", "bdc_name", "period_end", "accession", "position_id",
                "borrower", "industry", "investment_type", "investment_type_raw",
                "reference_rate", "spread_bps", "all_in_rate_pct", "maturity_date",
                "principal_amount", "shares_units", "cost", "fair_value",
                "pct_of_net_assets", "is_non_accrual", "source_scale", "source_url"]
    cols = [c for c in raw_cols if c in inv.columns]
    n = len(inv)
    rows = []
    for c in cols:
        nulls = int(inv[c].isna().sum())
        rows.append({
            "column": c,
            "non_null_rows": n - nulls,
            "null_rows": nulls,
            "null_share_pct": round(100.0 * nulls / n, 2),
        })
    tab = pd.DataFrame(rows).sort_values("null_share_pct", ascending=False)

    d = {r["column"]: r["null_share_pct"] for r in rows}
    n_industry_raw = int(inv["industry"].nunique())
    n_industry_norm = int(inv["industry_norm"].nunique())
    vals = {
        "denominator_rows": n,
        "null_share_pct_of_net_assets_pct": d["pct_of_net_assets"],
        "null_share_shares_units_pct": d["shares_units"],
        "null_share_spread_bps_pct": d["spread_bps"],
        "null_share_reference_rate_pct": d["reference_rate"],
        "null_share_all_in_rate_pct_pct": d["all_in_rate_pct"],
        "null_share_maturity_date_pct": d["maturity_date"],
        "null_share_principal_amount_pct": d["principal_amount"],
        "columns_with_zero_nulls": ", ".join(
            [r["column"] for r in rows if r["null_rows"] == 0]),
        "industry_labels_raw_count": n_industry_raw,
        "industry_labels_normalized_count": n_industry_norm,
        "note_units": (f"percentages of the {n:,} in-window investment-panel rows"),
    }
    save_table(
        tab, "m1_null_share_by_column",
        "Field completeness: null share by column, in-window investment panel",
        PERIOD,
        Coverage(basis="investment-panel", rows_used=n, rows_total=n,
                 note="Null share is computed on every in-window row of the panel."),
        note=("pct_of_net_assets is 100% null and must never be used. "
              f"industry carries {n_industry_raw} raw labels that collapse to "
              f"{n_industry_norm} once punctuation and taxonomy variants are "
              "normalized (industry_norm); use the normalized column. "
              "In the quarter panel nav_per_share is 90% null (27 of 30 quarters), so "
              "NAV per share is derived as net_assets / shares_outstanding throughout "
              "this report. " + GAP_NOTE),
        values=vals,
    )
    return vals


def fig_completeness_through_time(inv: pd.DataFrame) -> dict:
    cal = calendar_quarters("2018Q3", "2026Q2")
    comp = (inv.groupby("quarter")[RATE_TERM_FIELDS]
            .apply(lambda g: 100.0 * g.notna().mean())
            .reindex(cal))

    fig, ax = plt.subplots()
    x = np.arange(len(cal))
    # reference_rate and all_in_rate_pct are non-null on exactly the same rows
    # (0 disagreements in 31,067 rows), so reference_rate is drawn as a wide
    # band under the all-in-rate line instead of an invisible fourth line.
    ax.plot(x, comp["reference_rate"].values, color=NAVY, lw=4.2, alpha=0.35,
            solid_capstyle="round",
            label="reference_rate (coincides exactly with all_in_rate_pct)")
    for f, c in (("all_in_rate_pct", AMBER), ("maturity_date", PLUM),
                 ("spread_bps", TEAL)):
        ax.plot(x, comp[f].values, color=c, marker="o", markersize=2.2, label=f)
    for k, lab in enumerate(cal):
        if pd.isna(comp.iloc[k].iloc[0]):
            ax.axvspan(k - 0.5, k + 0.5, color=LIGHT, alpha=0.55, lw=0)
    ax.set_ylabel("share of that quarter's positions that are non-null")
    ax.set_ylim(40, 90)
    pct_axis(ax)
    quarter_ticks(ax, cal, every=4)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
    ax.legend(ncol=2, loc="lower center", fontsize=6.8)

    first_q, last_q = cal[0], cal[-1]
    vals = {"denominator": "positions in each quarter (varies by quarter)"}
    for f in RATE_TERM_FIELDS:
        vals[f"completeness_{f}_{first_q}_pct"] = round(float(comp.loc[first_q, f]), 1)
        vals[f"completeness_{f}_{last_q}_pct"] = round(float(comp.loc[last_q, f]), 1)
        vals[f"completeness_{f}_change_pp"] = round(
            float(comp.loc[last_q, f] - comp.loc[first_q, f]), 1)
        vals[f"completeness_{f}_min_pct"] = round(float(comp[f].min()), 1)
        vals[f"completeness_{f}_min_quarter"] = str(comp[f].idxmin())
    vals["note_units"] = ("percentage points; each series is the non-null share of "
                          "that field within that quarter's position rows")

    cov = Coverage(
        basis="investment-panel",
        rows_used=int(len(inv)),
        rows_total=int(len(inv)),
        note=("Each point is a within-quarter non-null share; the denominator is that "
              "quarter's own position count. 2019Q3 and 2022Q1 are gaps."),
    )
    save_fig(fig, "m1_rate_term_completeness_through_time",
             "Completeness of the four rate and term fields, quarter by quarter",
             PERIOD, cov,
             subtitle=("Higher is better; the series test whether the panel degrades "
                       "over time (y-axis truncated at 40%)"),
             values=vals)
    return vals


# ------------------------------------------------------------------ (d)

def missingness_by_type(inv: pd.DataFrame) -> dict:
    order = (inv.groupby("investment_type").size().sort_values(ascending=False).index)
    rows = []
    for t in order:
        g = inv[inv.investment_type == t]
        rec = {"investment_type": t,
               "positions": int(len(g)),
               "share_of_positions_pct": round(100.0 * len(g) / len(inv), 2),
               # Denominator is fair value POOLED over all 30 quarter-ends, so a
               # position held for k quarters enters k times.  This is a share of
               # position-quarter fair value, NOT a portfolio share at any single
               # date; the column name and the table note both say so.
               "share_of_pooled_fair_value_pct": round(
                   100.0 * g.fair_value.sum() / inv.fair_value.sum(), 2)}
        for f in RATE_TERM_FIELDS + ["principal_amount"]:
            rec[f"null_{f}_pct"] = round(100.0 * g[f].isna().mean(), 1)
        rows.append(rec)
    tab = pd.DataFrame(rows)

    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    fields = ["spread_bps", "all_in_rate_pct", "maturity_date", "principal_amount"]
    colours = [TEAL, AMBER, PLUM, SAGE]
    x = np.arange(len(tab))
    w = 0.2
    for j, (f, c) in enumerate(zip(fields, colours)):
        ax.bar(x + (j - 1.5) * w, tab[f"null_{f}_pct"], width=w, color=c, label=f)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{t}\n({n:,} pos)" for t, n in
                        zip(tab.investment_type, tab.positions)], fontsize=7)
    ax.set_ylabel("null share within the investment type")
    ax.set_ylim(0, 105)
    pct_axis(ax)
    ax.legend(ncol=1, loc="upper left", fontsize=7, title="null share of",
              title_fontsize=7)

    eq = tab[tab.investment_type == "equity"].iloc[0]
    pf = tab[tab.investment_type == "preferred"].iloc[0]
    fl = tab[tab.investment_type == "first lien"].iloc[0]
    non_debt = inv[~inv.investment_type.isin(["first lien", "second lien", "subordinated"])]
    debt = inv[inv.investment_type.isin(["first lien", "second lien", "subordinated"])]
    share_of_spread_nulls_from_nondebt = (
        100.0 * non_debt.spread_bps.isna().sum() / inv.spread_bps.isna().sum())

    vals = {
        "denominator_rows": int(len(inv)),
        "equity_positions": int(eq.positions),
        "equity_null_spread_bps_pct": float(eq.null_spread_bps_pct),
        "equity_null_all_in_rate_pct": float(eq.null_all_in_rate_pct_pct),
        "equity_null_maturity_date_pct": float(eq.null_maturity_date_pct),
        "preferred_positions": int(pf.positions),
        "preferred_null_spread_bps_pct": float(pf.null_spread_bps_pct),
        "preferred_null_maturity_date_pct": float(pf.null_maturity_date_pct),
        "first_lien_positions": int(fl.positions),
        "first_lien_null_spread_bps_pct": float(fl.null_spread_bps_pct),
        "first_lien_null_maturity_date_pct": float(fl.null_maturity_date_pct),
        "debt_like_positions": int(len(debt)),
        "debt_like_null_spread_bps_pct": round(100.0 * debt.spread_bps.isna().mean(), 1),
        "non_debt_share_of_all_spread_nulls_pct": round(share_of_spread_nulls_from_nondebt, 1),
        "note_units": ("null percentages are within-investment-type shares "
                       "(denominator = that type's own position count); "
                       "share_of_pooled_fair_value_pct is weighted by fair value "
                       "pooled across all 30 quarter-ends, not a single-date "
                       "portfolio share"),
    }
    cov = Coverage(
        basis="investment-panel",
        rows_used=int(len(inv)),
        rows_total=int(len(inv)),
        note="Every in-window position row is classified into exactly one investment type.",
    )
    save_fig(fig, "m1_missingness_by_investment_type",
             "Missingness is structural: nulls concentrate in equity and preferred",
             PERIOD, cov,
             subtitle=("Rate and maturity fields are simply not reported for "
                       "non-yielding instruments"),
             values=vals)
    save_table(tab, "m1_missingness_by_investment_type",
               "Null share of rate and term fields by investment type",
               PERIOD, cov,
               note=("Positions are counted equal-weight. share_of_pooled_fair_value_pct "
                     "is weighted by fair value POOLED over all 30 quarter-ends, so a "
                     "position held for k quarters enters k times; read it as a share of "
                     "position-quarter fair value, not as a portfolio weight at any one "
                     "date. Null shares use each type's own position count as the "
                     "denominator. Nulls in equity and preferred are structural, not "
                     "parse failures: those instruments carry no coupon or stated "
                     "maturity in the Schedule of Investments. " + GAP_NOTE),
               values=vals)
    return vals


def fig_missingness_by_vintage(inv: pd.DataFrame) -> dict:
    """Second leg of the 'missingness is not random' claim: filing age."""
    cal = calendar_quarters("2018Q3", "2026Q2")
    debt = inv[inv.debt_like]
    d = (debt.groupby("quarter")["spread_bps"]
         .apply(lambda s: 100.0 * s.isna().mean()).reindex(cal))
    e = (inv[~inv.debt_like].groupby("quarter")["spread_bps"]
         .apply(lambda s: 100.0 * s.isna().mean()).reindex(cal))

    fig, ax = plt.subplots()
    x = np.arange(len(cal))
    ax.plot(x, d.values, color=NAVY, marker="o", markersize=2.4,
            label="debt-like positions (first / second lien, subordinated)")
    ax.plot(x, e.values, color=RUST, marker="o", markersize=2.4,
            label="non-debt positions (equity, preferred, other)")
    for k in range(len(cal)):
        if pd.isna(d.iloc[k]) and pd.isna(e.iloc[k]):
            ax.axvspan(k - 0.5, k + 0.5, color=LIGHT, alpha=0.55, lw=0)
    ax.set_ylabel("spread_bps null share")
    ax.set_ylim(0, 105)
    pct_axis(ax)
    quarter_ticks(ax, cal, every=4)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
    ax.legend(loc="center left")

    early = [c for c in cal if c < "2021"]
    late = [c for c in cal if c >= "2024"]
    vals = {
        "debt_like_rows": int(len(debt)),
        "debt_spread_null_pct_2018Q3": round(float(d.loc["2018Q3"]), 1),
        "debt_spread_null_pct_2026Q2": round(float(d.loc["2026Q2"]), 1),
        "debt_spread_null_pct_mean_pre2021": round(float(d.reindex(early).mean()), 1),
        "debt_spread_null_pct_mean_2024_onward": round(float(d.reindex(late).mean()), 1),
        "nondebt_spread_null_pct_mean": round(float(e.mean()), 1),
        "debt_spread_null_pct_peak": round(float(d.max()), 1),
        "debt_spread_null_pct_peak_quarter": str(d.idxmax()),
        "debt_spread_null_pct_trough": round(float(d.min()), 1),
        "debt_spread_null_pct_trough_quarter": str(d.idxmin()),
        "note_units": ("percent of that quarter's positions in the stated group with a "
                       "null spread_bps"),
    }
    cov = Coverage(
        basis="investment-panel",
        rows_used=int(len(inv)),
        rows_total=int(len(inv)),
        note=("Split into debt-like and non-debt groups; the two groups partition the "
              "panel. 2019Q3 and 2022Q1 are gaps."),
    )
    save_fig(fig, "m1_spread_missingness_by_vintage",
             "The other axis of missingness: filing vintage",
             PERIOD, cov,
             subtitle=("Debt-like spread nulls peak in the 2020-2021 filings and settle "
                       "near 10% from 2022Q2 on; non-debt positions almost never "
                       "carry a spread"),
             values=vals)
    return vals


# ------------------------------------------------------------------ (e)

def fig_fv_weighted_rate_coverage(inv: pd.DataFrame) -> dict:
    cal = calendar_quarters("2018Q3", "2026Q2")
    d = inv.copy()
    d["usable_spread"] = d.spread_bps.notna() & (d.spread_bps > 0)
    d["usable_rate"] = d.all_in_rate_pct.notna() & (d.all_in_rate_pct > 0)
    d["usable_both"] = d.usable_spread & d.usable_rate

    def wshare(g, flag):
        tot = g.fair_value.sum()
        return 100.0 * g.loc[g[flag], "fair_value"].sum() / tot if tot else np.nan

    cols = ["fair_value", "usable_spread", "usable_rate", "usable_both"]
    grp = d.groupby("quarter")[cols]
    sp = grp.apply(lambda g: wshare(g, "usable_spread")).reindex(cal)
    rt = grp.apply(lambda g: wshare(g, "usable_rate")).reindex(cal)
    both = grp.apply(lambda g: wshare(g, "usable_both")).reindex(cal)
    # equal-weight comparison, explicitly labelled as such
    ew = grp.apply(lambda g: 100.0 * g["usable_both"].mean()).reindex(cal)

    fig, ax = plt.subplots()
    x = np.arange(len(cal))
    ax.plot(x, rt.values, color=AMBER, marker="o", markersize=2.4,
            label="usable all_in_rate_pct (FV-weighted)")
    # The spread series lies exactly on the 'both' series: every position with
    # a usable spread also carries a usable all-in rate (0 exceptions in the
    # window), so it is drawn as a wide band under the navy line rather than as
    # a fourth line that would be invisible.
    ax.plot(x, sp.values, color=TEAL, lw=4.2, alpha=0.45, solid_capstyle="round",
            label="usable spread_bps (FV-weighted)")
    ax.plot(x, both.values, color=NAVY, marker="o", markersize=2.8,
            label="both usable (FV-weighted); identical to spread coverage")
    ax.plot(x, ew.values, color=SLATE, ls="--", lw=1.1,
            label="both usable (equal-weight, for contrast)")
    for k in range(len(cal)):
        if pd.isna(both.iloc[k]):
            ax.axvspan(k - 0.5, k + 0.5, color=LIGHT, alpha=0.55, lw=0)
    ax.set_ylabel("share of quarter-end portfolio fair value")
    ax.set_ylim(40, 100)
    pct_axis(ax)
    quarter_ticks(ax, cal, every=4)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
    ax.legend(ncol=2, loc="lower center", fontsize=6.8)

    tab = pd.DataFrame({
        "quarter": cal,
        "fv_share_usable_spread_pct": sp.round(2).values,
        "fv_share_usable_all_in_rate_pct": rt.round(2).values,
        "fv_share_both_usable_pct": both.round(2).values,
        "equal_weight_share_both_usable_pct": ew.round(2).values,
    })
    tab = tab.dropna(subset=["fv_share_both_usable_pct"]).reset_index(drop=True)

    # Pooled counterpart of the quarterly mean: total usable fair value over
    # total fair value across the whole window.  The plotted mean is an
    # UNWEIGHTED average of the 30 quarterly shares (every quarter counts the
    # same regardless of portfolio size); the pooled figure weights quarters by
    # their fair value.  They differ, so both are reported.
    pooled = 100.0 * d.loc[d.usable_both, "fair_value"].sum() / d.fair_value.sum()
    zero_fv = int((d.fair_value == 0).sum())

    vals = {
        "denominator": "quarter-end total portfolio fair value of all positions in that quarter",
        "fv_share_both_usable_min_pct": round(float(both.min()), 1),
        "fv_share_both_usable_min_quarter": str(both.idxmin()),
        "fv_share_both_usable_max_pct": round(float(both.max()), 1),
        "fv_share_both_usable_max_quarter": str(both.idxmax()),
        "fv_share_both_usable_2018Q3_pct": round(float(both.loc["2018Q3"]), 1),
        "fv_share_both_usable_2026Q2_pct": round(float(both.loc["2026Q2"]), 1),
        "fv_share_both_usable_mean_of_30_quarters_unweighted_pct": round(
            float(both.mean()), 1),
        "fv_share_both_usable_pooled_over_window_pct": round(float(pooled), 1),
        "fv_share_both_usable_mean_2023_onward_unweighted_pct": round(
            float(both.reindex([c for c in cal if c >= "2023"]).mean()), 1),
        "fv_share_usable_all_in_rate_mean_of_30_quarters_unweighted_pct": round(
            float(rt.mean()), 1),
        "equal_weight_share_both_usable_mean_of_30_quarters_pct": round(
            float(ew.mean()), 1),
        "positions_with_usable_spread": int(d.usable_spread.sum()),
        "positions_with_usable_all_in_rate": int(d.usable_rate.sum()),
        "positions_with_spread_but_no_all_in_rate": int(
            (d.usable_spread & ~d.usable_rate).sum()),
        "rows_entering_fv_denominator": int(len(d)),
        "rows_with_zero_fair_value": zero_fv,
        "rows_with_zero_fair_value_share_pct": round(100.0 * zero_fv / len(d), 1),
        "note_units": ("percent of quarter-end portfolio fair value; 'usable' means "
                       "non-null and strictly positive. Every 'mean' key above is an "
                       "unweighted average of the 30 quarterly shares, not a "
                       "fair-value-weighted average over the window; the pooled "
                       "fair-value-weighted figure is reported separately."),
    }
    # Coverage is a statement about how many panel rows the exhibit was
    # COMPUTED ON, and this exhibit is computed on every in-window row: the
    # non-usable rows are not dropped, they sit in the fair-value denominator
    # and are exactly what the exhibit measures.  Stamping rows_used as the
    # 19,136 usable rows would read as "38% of the panel was discarded", which
    # is the opposite of what the chart does.
    cov = Coverage(
        basis="investment-panel",
        rows_used=int(len(d)),
        rows_total=int(len(inv)),
        note=(f"No rows are dropped: all {len(d):,} in-window positions enter the "
              f"fair-value denominator, and {int(d.usable_both.sum()):,} of them "
              f"({100.0 * d.usable_both.sum() / len(d):.1f}% of rows, equal-weight) "
              "carry both a usable spread and a usable all-in rate. The plotted "
              "series are fair-value weighted, which is the relevant credibility "
              f"measure for rate exhibits. {zero_fv:,} rows carry a fair value of "
              "exactly $0 and therefore get zero weight in every plotted series "
              "while still counting in the equal-weight line."),
    )
    save_fig(fig, "m1_fv_weighted_rate_coverage",
             "Fair-value-weighted coverage of the rate fields",
             PERIOD, cov,
             subtitle=("Share of each quarter's portfolio fair value carried by "
                       "positions with a usable spread and a usable all-in rate "
                       "(y-axis truncated at 40%)"),
             values=vals)
    save_table(tab, "m1_fv_weighted_rate_coverage",
               "Fair-value-weighted rate-field coverage by quarter",
               PERIOD, cov,
               note=("'Usable' means non-null and strictly positive. Every position "
                     f"with a usable spread also carries a usable all-in rate (0 of "
                     f"{len(d):,} rows are an exception), so the spread column and the "
                     "both-usable column are identical by observation, not by "
                     "construction. Each row's denominator is that quarter's own total "
                     "portfolio fair value across all positions; no position is "
                     "excluded from the denominator. The equal-weight column is shown "
                     "only for contrast; all report statements use the "
                     "fair-value-weighted columns. Averaging this table's rows gives an "
                     "UNWEIGHTED mean across quarters "
                     f"({both.mean():.1f}%); pooling fair value across the whole window "
                     f"instead gives {pooled:.1f}%. 2019Q3 and 2022Q1 are absent from "
                     "the panel and are omitted rather than interpolated, so the 30 "
                     "rows are not an evenly spaced series."),
               values=vals)
    return vals


# ---------------------------------------------------- balance-sheet tie

def table_balance_sheet_identity(q: pd.DataFrame) -> dict:
    d = q[["quarter", "period_end", "total_assets", "total_liabilities",
           "net_assets"]].copy()
    d["implied_net_assets"] = d.total_assets - d.total_liabilities
    d["discrepancy_usd"] = d.implied_net_assets - d.net_assets
    d["discrepancy_bps_of_net_assets"] = (
        1e4 * d.discrepancy_usd / d.net_assets)
    d["abs_discrepancy_usd"] = d.discrepancy_usd.abs()

    worst = d.loc[d.abs_discrepancy_usd.idxmax()]
    max_abs_usd = float(worst.abs_discrepancy_usd)
    max_abs_bps = float(d.discrepancy_bps_of_net_assets.abs().max())
    n_exact = int((d.abs_discrepancy_usd < 1.0).sum())
    ties = max_abs_bps < 1.0

    out = d[["quarter", "total_assets", "total_liabilities", "net_assets",
             "implied_net_assets", "discrepancy_usd",
             "discrepancy_bps_of_net_assets"]].copy()

    vals = {
        "quarters_checked": int(len(d)),
        "quarters_exact_to_under_1_usd": n_exact,
        "max_abs_discrepancy_usd": round(max_abs_usd, 2),
        "max_abs_discrepancy_quarter": str(worst.quarter),
        "max_abs_discrepancy_bps_of_net_assets": round(max_abs_bps, 4),
        "identity_ties": bool(ties),
        "verdict": ("The identity total_assets - total_liabilities = net_assets ties "
                    f"in all {len(d)} in-window quarters; the largest absolute "
                    f"discrepancy is ${max_abs_usd:,.2f} "
                    f"({max_abs_bps:.4f} bps of net assets, in {worst.quarter})."
                    if ties else
                    f"The identity does NOT tie: max absolute discrepancy "
                    f"${max_abs_usd:,.2f} ({max_abs_bps:.2f} bps of net assets) in "
                    f"{worst.quarter}."),
        "note_units": "USD and basis points of net assets",
    }
    cov = Coverage(
        basis="quarter-panel",
        rows_used=int(len(d)),
        rows_total=int(len(q)),
        note="All in-window quarters carry the three balance-sheet fields, so the "
             "check runs on every one of them.",
    )
    save_table(out, "m1_balance_sheet_identity",
               "Balance-sheet identity check: total assets - total liabilities vs net assets",
               PERIOD, cov,
               note=(vals["verdict"] + " Read this as a parse-integrity confirmation "
                     "rather than an independent audit: total_assets, "
                     "total_liabilities and net_assets are each parsed separately "
                     "from the filing, but the same identity is one of the 16 gate "
                     "checks the build applies (tolerance max(0.05% of total assets, "
                     "$1)), so any filing that broke it was excluded from the panel. "
                     "2019Q3 and 2022Q1 failed the gate and are absent; which check "
                     "each of them failed is not established here."),
               values=vals)
    return vals


# ------------------------------------------------------------- verify

def independent_check(inv: pd.DataFrame, fv_vals: dict, pos_vals: dict) -> None:
    """Recompute two headline numbers a second, different way."""
    # 1) 2026Q2 fair-value-weighted 'both usable' share, recomputed with a
    #    plain boolean mask and raw sums rather than groupby/apply.
    g = inv[inv.quarter == "2026Q2"]
    m = (g.spread_bps.notna() & (g.spread_bps > 0)
         & g.all_in_rate_pct.notna() & (g.all_in_rate_pct > 0))
    check = 100.0 * g.loc[m, "fair_value"].sum() / g.fair_value.sum()
    assert abs(check - fv_vals["fv_share_both_usable_2026Q2_pct"]) < 0.05, (
        check, fv_vals["fv_share_both_usable_2026Q2_pct"])

    # 2) position CAGR, recomputed from raw row counts with logs.
    a = int((inv.quarter == "2018Q3").sum())
    b = int((inv.quarter == "2026Q2").sum())
    cagr = 100.0 * (np.exp(np.log(b / a) / (31 / 4)) - 1.0)
    assert a == pos_vals["positions_2018Q3"] and b == pos_vals["positions_2026Q2"]
    assert abs(cagr - pos_vals["positions_cagr_pct_per_year"]) < 0.02
    print(f"[verify] 2026Q2 FV-weighted usable-rate share recomputed: {check:.2f}%")
    print(f"[verify] position CAGR recomputed by logs: {cagr:.2f}% per year "
          f"({a} -> {b} positions)")


def main() -> None:
    q, inv = load_panels()
    print(f"quarter panel rows (window): {len(q)}")
    print(f"investment panel rows (window): {len(inv):,}")

    cov_vals = fig_filing_coverage(q, inv)
    pos_vals = fig_position_counts(inv)
    null_vals = table_null_share(inv)
    comp_vals = fig_completeness_through_time(inv)
    type_vals = missingness_by_type(inv)
    vint_vals = fig_missingness_by_vintage(inv)
    fv_vals = fig_fv_weighted_rate_coverage(inv)
    bs_vals = table_balance_sheet_identity(q)

    independent_check(inv, fv_vals, pos_vals)
    dump_exhibit_log("m1_coverage_quality")

    print("\n--- headline numbers ---")
    for name, dd in [("coverage", cov_vals), ("positions", pos_vals),
                     ("nulls", null_vals), ("completeness", comp_vals),
                     ("by_type", type_vals), ("vintage", vint_vals),
                     ("fv_rate_coverage", fv_vals), ("balance_sheet", bs_vals)]:
        print(f"[{name}]")
        for k, v in dd.items():
            print(f"    {k}: {v}")


if __name__ == "__main__":
    main()
