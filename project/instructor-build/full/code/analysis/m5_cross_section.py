"""Module 5 - cross-section: composition, concentration, marks, stress, persistence.

Run standalone from the project root:

    python3 code/analysis/m5_cross_section.py

Everything is computed on the window-filtered investment panel returned by
common.load_panels() (31,067 rows, 30 quarters, 2018Q3-2026Q2).  All
composition figures are fair-value weighted; the two places where an
equal-weighted count is used (distinct borrowers, spell lengths) say so in
the exhibit title.

Two data facts shape this module and are disclosed in the exhibits:

1. ARCC's Schedule-of-Investments industry taxonomy changes twice in the
   window.  The 2019Q2-to-2019Q4 change is a real re-bucketing: only
   15.9% of 2018Q3 fair value sits in a label that still exists in
   2026Q2, so nothing before 2019Q4 is spliced onto the composition
   comparison.  The 2024Q3-to-2025Q1 change is a name-only GICS rename
   and is bridged by the 7-entry LEGACY_CROSSWALK below, applied only in
   part (a) and disclosed on that exhibit.
2. 2019Q3 and 2022Q1 are absent from the panel.  Nothing is
   interpolated; they are drawn as gaps and the persistence measure is
   defined over panel quarters, not calendar quarters.
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
    pct_axis, usd_axis, quarter_ticks, WINDOW_LABEL,
    NAVY, TEAL, AMBER, RUST, SAGE, PLUM, SLATE, LIGHT,
)

PERIOD = WINDOW_LABEL
INV_TOTAL = None   # set in main from the loaded panel
Q_TOTAL = None

TAXONOMY_BASE = "2019Q4"   # first quarter under the current industry taxonomy
LATEST = None              # set in main
FIRST = None


# ------------------------------------------------------------------ helpers

def hhi(values: pd.Series) -> float:
    """Herfindahl index in 0-10000 points on fair-value shares."""
    tot = values.sum()
    if tot <= 0:
        return float("nan")
    s = 100.0 * values / tot
    return float((s ** 2).sum())


def fv_share(df: pd.DataFrame, key: str) -> pd.Series:
    g = df.groupby(key)["fair_value"].sum()
    return 100.0 * g / g.sum()


# Documented GICS industry-group renames that ARCC adopted in its Schedule of
# Investments between 2024Q3 and 2025Q1.  This is an INFERENCE, not something
# read out of the filings: the labels are mapped by name, one to one, so that
# the 2019Q4 book can be compared with the 2026Q2 book on a single vocabulary.
# It is applied ONLY in the change-in-share exhibit (part a) and is disclosed
# there.  Legacy labels with no modern counterpart are left as they are.
LEGACY_CROSSWALK = {
    "Diversified Financials": "Financial Services",
    "Insurance Services": "Insurance",
    "Retailing": "Consumer Distribution and Retail",
    "Retailing and Distribution": "Consumer Distribution and Retail",
    "Media and Entertainment": "Sports, Media and Entertainment",
    "Healthcare Services": "Healthcare Equipment and Services",
    "Power Generation": "Independent Power and Renewable Electricity Producers",
}


def missing_quarters(quarters: list[str]) -> dict[str, str]:
    """Derive, not hardcode, the calendar quarters absent from the panel.

    Returns {quarter_before_the_gap: first_missing_quarter}.  Deriving this
    from the panel means the gap rules stay correct if the panel is rebuilt
    with more (or fewer) filings.
    """
    p = [pd.Period(qq, freq="Q") for qq in quarters]
    out = {}
    for a, b in zip(p, p[1:]):
        if (b - a).n > 1:
            out[str(a)] = str(a + 1)
    return out


def gap_shade(ax, quarters: list[str], label: bool = True) -> None:
    """Mark the quarters missing from the panel as gaps, not zeros.

    Drawn as a dashed rule rather than a filled band so it can never be
    mistaken for a data bar.  Note that the x axis is the PANEL-quarter
    index, not calendar time: the series is drawn on evenly spaced panel
    quarters, so the line segment spanning a gap connects the two quarters
    that bracket it.  No value is interpolated or imputed for the missing
    quarter; the dashed rule marks where the calendar jumps.
    """
    missing = missing_quarters(quarters)
    for i, qq in enumerate(quarters):
        if qq in missing and i + 1 < len(quarters):
            ax.axvline(i + 0.5, color=AMBER, ls=(0, (3, 2)), lw=1.0, zorder=1)
            if label:
                lo, hi = ax.get_ylim()
                ax.text(i + 0.5, lo + 0.02 * (hi - lo), f" no {missing[qq]} filing",
                        fontsize=6.0, color=AMBER, va="bottom", ha="left", rotation=90)


# ------------------------------------------------------------------ (a)

def part_a(inv: pd.DataFrame) -> dict:
    x = inv.copy()
    x["industry_cw"] = x.industry_norm.replace(LEGACY_CROSSWALK)
    lat = x[x.quarter == LATEST]
    base = x[x.quarter == TAXONOMY_BASE]
    first = x[x.quarter == FIRST]

    lat_sh = fv_share(lat, "industry_cw").sort_values(ascending=False)
    base_sh = fv_share(base, "industry_cw")
    top12 = lat_sh.head(12)

    # Share of FIRST-quarter fair value that still carries a label used in the
    # latest quarter.  Computed, not asserted, because it is the number that
    # justifies anchoring the comparison on 2019Q4 instead of 2018Q3.
    carry_pct = 100.0 * (first[first.industry_norm.isin(set(lat.industry_norm))]
                         .fair_value.sum() / first.fair_value.sum())

    # --- the union universe, so INDUSTRY EXITS cannot be censored out.
    # Selecting on "top 12 by LATEST fair value" alone is a survivorship
    # filter: an industry that shrank to nothing by the latest quarter can
    # never enter the frame, however large its 2019Q4 weight was.  The
    # figure therefore plots the top 12 by latest fair value PLUS every
    # industry whose share moved by at least MOVER_PP either way.
    MOVER_PP = 1.0
    uni = pd.concat([lat_sh.rename("share_latest_pct"),
                     base_sh.rename("share_2019q4_pct")], axis=1)
    uni["absent_latest"] = uni.share_latest_pct.isna()
    uni["absent_base"] = uni.share_2019q4_pct.isna()
    uni = uni.fillna(0.0)
    uni["change_pp"] = uni.share_latest_pct - uni.share_2019q4_pct
    sel = sorted(set(top12.index) | set(uni.index[uni.change_pp.abs() >= MOVER_PP]))
    figd = uni.loc[sel].copy()
    figd["in_top12"] = figd.index.isin(top12.index)
    n_added = int((~figd.in_top12).sum())

    comp = pd.DataFrame({
        "industry_norm": top12.index,
        "fv_latest_usd": lat.groupby("industry_cw").fair_value.sum().reindex(top12.index).values,
        "share_latest_pct": top12.values,
        "share_2019q4_pct": base_sh.reindex(top12.index).fillna(0.0).values,
    })
    comp["change_pp"] = comp.share_latest_pct - comp.share_2019q4_pct
    comp = comp.sort_values("change_pp", ascending=False).reset_index(drop=True)

    # --- figure: diverging bar of the change in fair-value share
    fig, ax = plt.subplots(figsize=(7.4, 5.9))
    d = figd.sort_values("change_pp")
    colors = [TEAL if v >= 0 else RUST for v in d.change_pp]
    y = np.arange(len(d))
    ax.barh(y, d.change_pp, color=colors, height=0.68)
    ax.barh(y[~d.in_top12.values], d.change_pp[~d.in_top12.values],
            color="none", edgecolor="#42505E", lw=0.8, ls=(0, (2, 1.6)),
            height=0.68, zorder=4)
    ax.set_yticks(y)
    ax.set_yticklabels([(t if len(t) <= 42 else t[:40] + "..") + ("" if k else "  *")
                        for t, k in zip(d.index, d.in_top12)])
    ax.axvline(0, color="#42505E", lw=0.9)
    for yi, (chg, a, b, na, nb) in enumerate(zip(
            d.change_pp, d.share_2019q4_pct, d.share_latest_pct,
            d.absent_latest, d.absent_base)):
        sa = "no such label" if nb else f"{a:.1f}"
        sb = "no such label" if na else f"{b:.1f}%"
        off = 0.18 if chg >= 0 else -0.18
        ax.text(chg + off, yi, f"{sa} to {sb}", va="center",
                ha="left" if chg >= 0 else "right", fontsize=6.4, color="#42505E")
    ax.set_xlabel("Change in share of portfolio fair value (percentage points)")
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:+.0f}"))
    ax.grid(axis="y", visible=False)
    ax.set_xlim(d.change_pp.min() - 6.0, d.change_pp.max() + 5.0)
    cov = Coverage("investment-panel", int(len(lat) + len(base)), INV_TOTAL,
                   note=(f"Selection rule: the top 12 industries by {LATEST} fair value, "
                         f"PLUS every other industry whose share moved by at least "
                         f"{MOVER_PP:.1f}pp either way ({n_added} added, marked * and "
                         "outlined). Ranking on latest size alone would censor industries "
                         "that shrank to nothing, which is exactly where the book moved. "
                         f"Anchored on {TAXONOMY_BASE}, the first quarter after ARCC's 2019 "
                         f"taxonomy change; only {carry_pct:.1f}% of {FIRST} fair value "
                         "carries a label still used in the latest quarter, so "
                         f"{FIRST}-2019Q2 is not spliced on. A second, name-only GICS "
                         "rename between 2024Q3 and 2025Q1 is bridged by a 7-entry "
                         "crosswalk (for example Diversified Financials to Financial "
                         "Services); that mapping is an inference by the analyst, not a "
                         "filing disclosure. A bar reading 'no such label' is a label that "
                         "does not exist in that quarter's taxonomy, which is NOT the same "
                         "as zero exposure: the exposure may sit under a different label "
                         "the crosswalk does not bridge."))
    save_fig(fig, "m5_industry_share_change",
             "Where the book moved: change in industry share of fair value",
             PERIOD, cov,
             subtitle=(f"{TAXONOMY_BASE} to {LATEST}, fair-value weighted; top 12 industries "
                       f"as of {LATEST} plus every mover of {MOVER_PP:.0f}pp or more (*)"),
             values={
                 "latest_quarter": LATEST,
                 "base_quarter": TAXONOMY_BASE,
                 "selection_rule": (f"top 12 by {LATEST} FV union movers >= {MOVER_PP}pp"),
                 "n_industries_plotted": int(len(figd)),
                 "n_added_beyond_top12": n_added,
                 "top12_share_of_latest_fv_pct": round(float(top12.sum()), 2),
                 "first_quarter_fv_share_on_surviving_labels_pct": round(float(carry_pct), 2),
                 # largest gain/loss over the FULL industry universe, not just top 12
                 "largest_gain_industry": str(uni.change_pp.idxmax()),
                 "largest_gain_pp": round(float(uni.change_pp.max()), 2),
                 "largest_loss_industry": str(uni.change_pp.idxmin()),
                 "largest_loss_pp": round(float(uni.change_pp.min()), 2),
                 "largest_loss_industry_within_top12": str(comp.iloc[-1].industry_norm),
                 "largest_loss_pp_within_top12": round(float(comp.iloc[-1].change_pp), 2),
                 "largest_loss_outside_top12": str(
                     uni[~uni.index.isin(top12.index)].change_pp.idxmin()),
                 "largest_loss_outside_top12_pp": round(
                     float(uni[~uni.index.isin(top12.index)].change_pp.min()), 2),
                 "top1_industry": str(lat_sh.index[0]),
                 "top1_share_latest_pct": round(float(lat_sh.iloc[0]), 2),
                 "denominator": f"each quarter's own total fair value; the {LATEST} book is "
                                f"${lat.fair_value.sum()/1e9:,.2f}bn and the {TAXONOMY_BASE} "
                                f"book ${base.fair_value.sum()/1e9:,.2f}bn",
             })

    # --- table: composition detail plus the legacy-taxonomy start of window
    tab = comp.copy()
    tab["fv_latest_usd_mm"] = tab.fv_latest_usd / 1e6
    tab = tab[["industry_norm", "fv_latest_usd_mm", "share_latest_pct",
               "share_2019q4_pct", "change_pp"]]
    tab.columns = ["Industry (normalized)", f"FV {LATEST} ($mm)",
                   f"Share {LATEST} (%)", f"Share {TAXONOMY_BASE} (%)",
                   "Change (pp)"]
    exits = uni[(~uni.index.isin(top12.index)) & (uni.change_pp <= -1.0)].sort_values("change_pp")
    exit_txt = "; ".join(f"{k} {v.share_2019q4_pct:.1f} to {v.share_latest_pct:.1f}% "
                         f"({v.change_pp:+.1f}pp)" for k, v in exits.iterrows())
    covt = Coverage("investment-panel", int(len(lat) + len(base)), INV_TOTAL,
                    note=(f"{len(lat):,} {LATEST} rows and {len(base):,} {TAXONOMY_BASE} rows. "
                          "Shares are of each quarter's own total fair value."))
    save_table(tab, "m5_industry_composition",
               f"Industry composition of the ARCC book, {TAXONOMY_BASE} vs {LATEST}",
               PERIOD, covt,
               note=("Fair-value weighted. Labels are common.normalize_industry "
                     "output (57 normalized labels in window, from 68 raw labels), "
                     "plus a 7-entry legacy crosswalk applied to the 2019Q4 column "
                     "only: Diversified Financials to Financial Services; Insurance "
                     "Services to Insurance; Retailing and Retailing and Distribution "
                     "to Consumer Distribution and Retail; Media and Entertainment to "
                     "Sports, Media and Entertainment; Healthcare Services to "
                     "Healthcare Equipment and Services; Power Generation to "
                     "Independent Power and Renewable Electricity Producers. The "
                     "comparison starts at 2019Q4 because the 2019 taxonomy break "
                     "cannot be bridged by renaming. THIS TABLE RANKS ON LATEST FAIR "
                     "VALUE, so industries the book exited are not rows in it. The "
                     f"exits of 1pp or more of {TAXONOMY_BASE} fair value are: "
                     f"{exit_txt}. They are plotted in the companion figure. A latest "
                     "share of 0.0% can mean the label no longer exists in the "
                     "taxonomy rather than that the exposure was sold."),
               values={
                   "top12_share_of_latest_fv_pct": round(float(top12.sum()), 2),
                   "n_industries_latest": int(lat.industry_cw.nunique()),
                   "n_industries_base": int(base.industry_cw.nunique()),
                   "n_industries_window_normalized": int(inv.industry_norm.nunique()),
                   "crosswalk_entries": len(LEGACY_CROSSWALK),
                   "excluded_exits": {k: round(float(v.change_pp), 2)
                                      for k, v in exits.iterrows()},
                   "denominator": f"{LATEST} total fair value ${lat.fair_value.sum()/1e9:,.2f}bn "
                                  f"for the latest column; {TAXONOMY_BASE} total fair value "
                                  f"${base.fair_value.sum()/1e9:,.2f}bn for the base column",
               })

    first_sh = fv_share(first, "industry_cw").sort_values(ascending=False).head(8)
    return {
        "comp": comp,
        "top12_share": float(top12.sum()),
        "legacy_top8": {k: round(float(v), 2) for k, v in first_sh.items()},
        "latest_fv": float(lat.fair_value.sum()),
        "first_fv": float(first.fair_value.sum()),
    }


# ------------------------------------------------------------------ (b)

def part_b(inv: pd.DataFrame) -> dict:
    qs = sorted(inv.quarter.unique())
    missing_note = " and ".join(missing_quarters(qs).values()) or "no quarters"
    rows = []
    for qq in qs:
        s = inv[inv.quarter == qq]
        sh = fv_share(s, "industry_norm").sort_values(ascending=False)
        rows.append({"quarter": qq,
                     "hhi_industry": hhi(s.groupby("industry_norm").fair_value.sum()),
                     "top5_share_pct": float(sh.head(5).sum()),
                     "n_industries": int(s.industry_norm.nunique())})
    d = pd.DataFrame(rows)

    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    x = np.arange(len(d))
    ax.plot(x, d.hhi_industry, color=NAVY, marker="o", ms=2.6, label="Industry HHI (left)")
    ax.set_ylabel("Herfindahl index (0-10,000 points)")
    gap_shade(ax, qs)
    ax.axvline(qs.index(TAXONOMY_BASE) - 0.5, color=SLATE, ls=":", lw=1.0)
    ax.text(qs.index(TAXONOMY_BASE) - 0.4, ax.get_ylim()[1], " taxonomy change",
            fontsize=6.4, color=SLATE, va="top")
    ax2 = ax.twinx()
    ax2.plot(x, d.top5_share_pct, color=AMBER, marker="s", ms=2.4,
             label="Top-5 industry share of FV (right)")
    ax2.set_ylabel("Top-5 industry share of fair value")
    ax2.grid(False)
    pct_axis(ax2)
    quarter_ticks(ax, qs, every=3)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left", ncol=2)
    pre = d.set_index("quarter")
    q_pre = qs[qs.index(TAXONOMY_BASE) - 1]
    hhi_break = float(pre.hhi_industry[TAXONOMY_BASE] - pre.hhi_industry[q_pre])
    cov = Coverage("investment-panel", int(len(inv)), INV_TOTAL,
                   note=(f"{missing_note} are absent from the panel and are drawn "
                         "with a dashed amber rule; the x axis is the panel-quarter index, "
                         "so the line spans the gap without any value being interpolated. "
                         "The dotted grey line marks the 2019 industry-taxonomy change. "
                         "THE LEVEL IS NOT COMPARABLE ACROSS THAT LINE: the bucket count "
                         f"falls from {int(pre.n_industries[q_pre])} labels in {q_pre} to "
                         f"{int(pre.n_industries[TAXONOMY_BASE])} in {TAXONOMY_BASE}, yet the "
                         f"measured HHI moves {hhi_break:+.0f} points across the same break, "
                         "because the re-bucketing split as well as merged sectors. Read the "
                         f"pre-{TAXONOMY_BASE} segment and the post-{TAXONOMY_BASE} segment as "
                         "two separate series, not as one trend. A second, name-only GICS "
                         "rename between 2024Q3 and 2025Q1 leaves the bucket count broadly "
                         f"unchanged ({int(pre.n_industries['2024Q3'])} to "
                         f"{int(pre.n_industries['2025Q1'])}) and so does not move these series."))
    save_fig(fig, "m5_industry_concentration",
             "Industry concentration through time",
             PERIOD, cov,
             subtitle="Fair-value weighted Herfindahl index and top-5 industry share, by quarter",
             values={
                 "hhi_latest_pts": round(float(d.hhi_industry.iloc[-1]), 1),
                 "hhi_2019q4_pts": round(float(d.set_index('quarter').hhi_industry[TAXONOMY_BASE]), 1),
                 "hhi_min_pts": round(float(d.hhi_industry.min()), 1),
                 "hhi_min_quarter": str(d.loc[d.hhi_industry.idxmin(), "quarter"]),
                 "hhi_max_pts": round(float(d.hhi_industry.max()), 1),
                 "hhi_max_quarter": str(d.loc[d.hhi_industry.idxmax(), "quarter"]),
                 "top5_share_latest_pct": round(float(d.top5_share_pct.iloc[-1]), 2),
                 "top5_share_2019q4_pct": round(float(d.set_index('quarter').top5_share_pct[TAXONOMY_BASE]), 2),
                 "n_industries_latest": int(d.n_industries.iloc[-1]),
                 "denominator": "each quarter's own total portfolio fair value",
             })
    return {"conc": d}


# ------------------------------------------------------------------ (c)

def part_c(inv: pd.DataFrame) -> dict:
    qs = sorted(inv.quarter.unique())
    rows = []
    for qq in qs:
        s = inv[inv.quarter == qq]
        g = s.groupby("borrower").fair_value.sum().sort_values(ascending=False)
        rows.append({"quarter": qq,
                     "n_borrowers": int(s.borrower.nunique()),
                     "n_positions": int(len(s)),
                     "top10_share_pct": float(100.0 * g.head(10).sum() / g.sum()),
                     "hhi_borrower": hhi(g)})
    d = pd.DataFrame(rows)

    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    x = np.arange(len(qs))
    ax.bar(x, d.n_borrowers, color=LIGHT, width=0.72, label="Distinct borrowers (left, equal-weight count)")
    ax.set_ylabel("Distinct borrowers in the book")
    ax.set_ylim(0, d.n_borrowers.max() * 1.18)
    gap_shade(ax, qs)
    ax2 = ax.twinx()
    ax2.plot(x, d.top10_share_pct, color=RUST, marker="o", ms=2.6,
             label="Top-10 borrower share of FV (right)")
    ax2.plot(x, d.hhi_borrower / 10.0, color=NAVY, marker="s", ms=2.2,
             label="Borrower HHI / 10 (right)")
    ax2.set_ylabel("Percent (HHI shown as points / 10)")
    ax2.grid(False)
    ax2.set_ylim(0, max(d.top10_share_pct.max(), (d.hhi_borrower / 10).max()) * 1.45)
    quarter_ticks(ax, qs, every=3)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=6.8)
    cov = Coverage("investment-panel", int(len(inv)), INV_TOTAL,
                   note=("Borrower identity is the raw borrower string in the filing; "
                         "no fuzzy matching is applied, so a renamed obligor counts "
                         "as a new borrower and the borrower count is an upper bound "
                         "on distinct obligors. The bars are an equal-weighted count "
                         "of names and carry no size information. "
                         f"{' and '.join(missing_quarters(qs).values())} are marked with "
                         "dashed amber rules; the x axis is the panel-quarter index and "
                         "nothing is interpolated across the gaps."))
    save_fig(fig, "m5_borrower_concentration",
             "Borrower breadth and borrower concentration",
             PERIOD, cov,
             subtitle="Distinct borrowers per quarter, top-10 borrower fair-value share, and borrower-level HHI",
             values={
                 "n_borrowers_first": int(d.n_borrowers.iloc[0]),
                 "first_quarter": qs[0],
                 "n_borrowers_latest": int(d.n_borrowers.iloc[-1]),
                 "latest_quarter": qs[-1],
                 "top10_share_first_pct": round(float(d.top10_share_pct.iloc[0]), 2),
                 "top10_share_latest_pct": round(float(d.top10_share_pct.iloc[-1]), 2),
                 "top10_share_max_pct": round(float(d.top10_share_pct.max()), 2),
                 "top10_share_max_quarter": str(d.loc[d.top10_share_pct.idxmax(), "quarter"]),
                 "hhi_borrower_first_pts": round(float(d.hhi_borrower.iloc[0]), 1),
                 "hhi_borrower_latest_pts": round(float(d.hhi_borrower.iloc[-1]), 1),
                 "denominator": "each quarter's own total portfolio fair value; "
                                "borrower counts are equal-weighted counts of distinct names",
             })

    # --- table: largest 15 positions in the latest quarter
    lat = inv[inv.quarter == LATEST].copy()
    tot = lat.fair_value.sum()
    top15 = lat.sort_values("fair_value", ascending=False).head(15).copy()
    top15["fv_share_pct"] = 100.0 * top15.fair_value / tot
    top15["fv_over_cost"] = np.where(top15.cost > 0, top15.fair_value / top15.cost, np.nan)
    t = pd.DataFrame({
        "Borrower": top15.borrower.values,
        "Industry (normalized)": top15.industry_norm.values,
        "Type": top15.investment_type.values,
        "Fair value ($mm)": top15.fair_value.values / 1e6,
        "FV share of book (%)": top15.fv_share_pct.values,
        "FV / cost (x)": top15.fv_over_cost.values,
        "Non-accrual": np.where(top15.is_non_accrual.values, "yes", "no"),
    })
    covt = Coverage("investment-panel", int(len(top15)), INV_TOTAL,
                    note=(f"The window share above rounds to 0.0% by construction: this is a "
                          f"top-15 cut of one quarter. The meaningful coverage is "
                          f"{len(top15)} of the {len(lat):,} positions held in {LATEST} "
                          f"({100.0*len(top15)/len(lat):.1f}% of that quarter's rows), which "
                          f"carry {float(top15.fv_share_pct.sum()):.2f}% of its fair value. "
                          "Rows are single positions, not borrower aggregates, so one "
                          "borrower can appear more than once and a borrower's total "
                          "exposure is larger than any single row shown."))
    save_table(t, "m5_top15_positions_latest",
               f"Largest 15 positions by fair value, {LATEST}",
               PERIOD, covt,
               note=("FV/cost is blank where reported cost is zero or missing. "
                     "Share denominator is the whole book's fair value in that quarter."),
               values={
                   "latest_quarter": LATEST,
                   "book_fv_usd_bn": round(tot / 1e9, 3),
                   "top15_fv_usd_bn": round(float(top15.fair_value.sum()) / 1e9, 3),
                   "top15_share_of_book_pct": round(float(top15.fv_share_pct.sum()), 2),
                   "largest_position_borrower": str(top15.iloc[0].borrower),
                   "largest_position_fv_usd_mm": round(float(top15.iloc[0].fair_value) / 1e6, 1),
                   "largest_position_share_pct": round(float(top15.iloc[0].fv_share_pct), 2),
                   "largest_position_type": str(top15.iloc[0].investment_type),
                   "largest_borrower_all_positions_n": int(
                       (lat.borrower == top15.iloc[0].borrower).sum()),
                   "largest_borrower_all_positions_share_pct": round(float(
                       100.0 * lat[lat.borrower == top15.iloc[0].borrower].fair_value.sum()
                       / tot), 2),
                   "n_positions_latest": int(len(lat)),
                   "n_borrowers_latest": int(lat.borrower.nunique()),
                   "denominator": f"{LATEST} total fair value ${tot/1e9:,.3f}bn",
               })
    return {"bconc": d, "top15": t}


# ------------------------------------------------------------------ (d)

def part_d(inv: pd.DataFrame) -> dict:
    lat = inv[inv.quarter == LATEST].copy()
    priced = lat[lat.cost > 0].copy()
    priced["ratio"] = priced.fair_value / priced.cost

    top12 = (lat.groupby("industry_norm").fair_value.sum()
             .sort_values(ascending=False).head(12).index.tolist())
    g = priced[priced.industry_norm.isin(top12)].groupby("industry_norm")
    agg = pd.DataFrame({
        "fv": g.fair_value.sum(),
        "cost": g.cost.sum(),
        "n": g.size(),
        "p25": g.ratio.quantile(0.25),
        "p75": g.ratio.quantile(0.75),
    })
    agg["fv_over_cost"] = agg.fv / agg.cost
    agg["iqr"] = agg.p75 - agg.p25
    agg = agg.reindex(top12)
    book_ratio = priced.fair_value.sum() / priced.cost.sum()

    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    d = agg.sort_values("fv_over_cost")
    y = np.arange(len(d))
    ax.hlines(y, d.p25, d.p75, color=LIGHT, lw=5.0, zorder=1)
    ax.scatter(d.fv_over_cost, y, color=NAVY, s=26, zorder=3,
               label="FV-weighted FV/cost")
    ax.scatter(d.p25, y, color=SLATE, s=9, zorder=2)
    ax.scatter(d.p75, y, color=SLATE, s=9, zorder=2,
               label="Position-level interquartile range (equal-weight)")
    ax.axvline(book_ratio, color=RUST, ls="--", lw=1.1,
               label=f"Whole book {book_ratio:.3f}x")
    ax.axvline(1.0, color="#42505E", lw=0.8)
    ax.set_yticks(y)
    ax.set_yticklabels([(t if len(t) <= 38 else t[:36] + "..") + f"  (n={int(k)})"
                        for t, k in zip(d.index, d.n)])
    ax.set_xlabel("Fair value / cost (x)")
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower right", fontsize=6.8)
    # count zero AND missing cost explicitly rather than with `<= 0`, which
    # silently drops NaN from the exclusion count it is meant to report.
    n_excl = int(len(lat) - len(priced))
    excl_fv = float(lat.fair_value.sum() - priced.fair_value.sum())
    cov = Coverage("investment-panel", int(len(priced[priced.industry_norm.isin(top12)])),
                   INV_TOTAL,
                   note=(f"{LATEST} only, top 12 industries by fair value (these 12 hold "
                         f"{100.0*float(agg.fv.sum()/priced.fair_value.sum()):.1f}% of priced "
                         f"fair value in the quarter). {n_excl} of {len(lat):,} positions in "
                         "the quarter report zero or missing cost and are excluded from every "
                         f"ratio, including the whole-book line; they carry ${excl_fv/1e6:,.1f}mm "
                         f"({100.0*excl_fv/lat.fair_value.sum():.2f}% of book fair value), so the "
                         "line is a whole-book mark for practical purposes. The dot is FV-weighted "
                         "and the bar is an EQUAL-WEIGHTED position-level IQR: the two answer "
                         "different questions and need not agree. Industry n is shown on each "
                         "label because several IQRs rest on very few positions."))
    save_fig(fig, "m5_marks_by_industry",
             "Cross-section of marks: fair value against cost by industry",
             PERIOD, cov,
             subtitle=f"{LATEST}, FV-weighted industry ratio with the equal-weighted position-level IQR",
             values={
                 "latest_quarter": LATEST,
                 "book_fv_over_cost_x": round(float(book_ratio), 4),
                 "highest_mark_industry": str(agg.fv_over_cost.idxmax()),
                 "highest_mark_x": round(float(agg.fv_over_cost.max()), 4),
                 "lowest_mark_industry": str(agg.fv_over_cost.idxmin()),
                 "lowest_mark_x": round(float(agg.fv_over_cost.min()), 4),
                 "highest_mark_n": int(agg.n[agg.fv_over_cost.idxmax()]),
                 "lowest_mark_n": int(agg.n[agg.fv_over_cost.idxmin()]),
                 "widest_iqr_industry": str(agg.iqr.idxmax()),
                 "widest_iqr_x": round(float(agg.iqr.max()), 4),
                 "widest_iqr_n": int(agg.n[agg.iqr.idxmax()]),
                 "narrowest_iqr_industry": str(agg.iqr.idxmin()),
                 "narrowest_iqr_x": round(float(agg.iqr.min()), 4),
                 "narrowest_iqr_n": int(agg.n[agg.iqr.idxmin()]),
                 "narrowest_iqr_at_cost_share_pct": round(100.0 * float(
                     (priced[priced.industry_norm == agg.iqr.idxmin()].ratio.round(6)
                      == 1.0).mean()), 2),
                 "narrowest_iqr_note": ("interquartile range is exactly 0.0x because "
                                        "the majority of that industry's positions are "
                                        "marked at cost"),
                 "iqr_weighting": "equal-weighted across positions; the dot is FV-weighted",
                 "share_positions_marked_at_cost_pct": round(
                     100.0 * float((priced.ratio.round(6) == 1.0).mean()), 2),
                 "n_priced_positions": int(len(priced)),
                 "positions_excluded_zero_or_missing_cost": n_excl,
                 "excluded_fv_usd_mm": round(excl_fv / 1e6, 1),
                 "excluded_fv_share_of_book_pct": round(
                     100.0 * excl_fv / float(lat.fair_value.sum()), 3),
                 "denominator": "aggregate reported cost of the positions in each "
                                "industry with strictly positive cost; the at-cost share "
                                f"is out of the {len(priced):,} priced positions in {LATEST}",
             })
    return {"marks": agg, "book_ratio": book_ratio}


# ------------------------------------------------------------------ (e)

def part_e(inv: pd.DataFrame) -> dict:
    na = inv[inv.is_non_accrual]
    by = inv.groupby("industry_norm").agg(cost_all=("cost", "sum"),
                                          fv_all=("fair_value", "sum"),
                                          n_all=("cost", "size"))
    nag = na.groupby("industry_norm").agg(cost_na=("cost", "sum"),
                                          fv_na=("fair_value", "sum"),
                                          n_na=("cost", "size"))
    t = by.join(nag, how="left").fillna({"cost_na": 0.0, "fv_na": 0.0, "n_na": 0})
    t["na_rate_of_cost_pct"] = np.where(t.cost_all > 0, 100.0 * t.cost_na / t.cost_all, np.nan)
    t["na_recovery_x"] = np.where(t.cost_na > 0, t.fv_na / t.cost_na, np.nan)
    t = t[t.cost_na > 0].sort_values("cost_na", ascending=False)
    top = t.head(12)

    fig, axes = plt.subplots(1, 2, figsize=(7.6, 4.4), sharey=True,
                             gridspec_kw={"width_ratios": [2.0, 1.0], "wspace": 0.06})
    y = np.arange(len(top))[::-1]
    ax = axes[0]
    ax.barh(y + 0.18, top.cost_na / 1e6, color=SLATE, height=0.34, label="Non-accrual cost")
    ax.barh(y - 0.18, top.fv_na / 1e6, color=RUST, height=0.34, label="Non-accrual fair value")
    ax.set_yticks(y)
    ax.set_yticklabels([s if len(s) <= 40 else s[:38] + ".." for s in top.index])
    ax.set_xlabel("$mm of quarter-position rows, pooled over 30 quarters")
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower right", fontsize=7)

    ax = axes[1]
    ax.barh(y, top.na_rate_of_cost_pct, color=AMBER, height=0.6)
    ax.set_xlabel("Non-accrual cost as % of\nthat industry's pooled cost")
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, top.na_rate_of_cost_pct.max() * 1.35)
    for yi, r in zip(y, top.na_rate_of_cost_pct):
        ax.text(r, yi, f" {r:.1f}%", va="center", ha="left", fontsize=6.4,
                color="#42505E")
    ax = axes[0]
    cov = Coverage("investment-panel", int(len(na)), INV_TOTAL,
                   note=("Rows flagged is_non_accrual, pooled across the 30 panel "
                         "quarters. Pooling repeats a position once per quarter it "
                         "stays on non-accrual, so these are quarter-position dollars "
                         "and not a single-date exposure. Labels here are the "
                         "normalized filing labels with NO legacy crosswalk applied, "
                         "so the pre-2025 and post-2025 names for one sector (for "
                         "example Healthcare Services and Healthcare Equipment and "
                         "Services) appear as separate rows."))
    save_fig(fig, "m5_nonaccrual_by_industry",
             "Which industries carry the non-accruals",
             PERIOD, cov,
             subtitle="Non-accrual cost and fair value by industry, pooled over 2018Q3-2026Q2",
             values={
                 "na_rows": int(len(na)),
                 "na_row_share_of_panel_pct": round(100.0 * len(na) / len(inv), 2),
                 "na_cost_usd_bn_pooled": round(float(na.cost.sum()) / 1e9, 3),
                 "na_fv_usd_bn_pooled": round(float(na.fair_value.sum()) / 1e9, 3),
                 "na_recovery_x_pooled": round(float(na.fair_value.sum() / na.cost.sum()), 4),
                 "na_cost_share_of_panel_cost_pct": round(
                     100.0 * float(na.cost.sum() / inv.cost.sum()), 2),
                 "top_na_industry_by_cost": str(top.index[0]),
                 "top_na_industry_cost_usd_mm": round(float(top.cost_na.iloc[0]) / 1e6, 1),
                 "highest_na_rate_industry": str(t.na_rate_of_cost_pct.idxmax()),
                 "highest_na_rate_pct": round(float(t.na_rate_of_cost_pct.max()), 2),
                 "denominator": "pooled reported cost of all quarter-position rows in "
                                "that industry over the 30 panel quarters",
             })

    out = pd.DataFrame({
        "Industry (normalized)": top.index,
        "Non-accrual cost ($mm)": top.cost_na.values / 1e6,
        "Non-accrual FV ($mm)": top.fv_na.values / 1e6,
        "NA FV / NA cost (x)": top.na_recovery_x.values,
        "Industry cost ($mm)": top.cost_all.values / 1e6,
        "NA rate (% of industry cost)": top.na_rate_of_cost_pct.values,
        "NA rows": top.n_na.values.astype(int),
    })
    covt = Coverage("investment-panel", int(top.n_na.sum()), INV_TOTAL,
                    note=(f"Top 12 industries by pooled non-accrual cost: "
                          f"{int(top.n_na.sum())} of the {len(na)} non-accrual rows in the "
                          f"window, carrying {100.0*float(top.cost_na.sum()/na.cost.sum()):.2f}% "
                          f"of pooled non-accrual cost, spread over {len(t)} industries that "
                          "ever show a non-accrual."))
    save_table(out, "m5_nonaccrual_by_industry",
               "Non-accrual exposure by industry, pooled 2018Q3-2026Q2",
               PERIOD, covt,
               note=("Quarter-position dollars: a position on non-accrual for six "
                     "quarters contributes six rows. The rate denominator is the "
                     "same pooled cost basis for that industry, so numerator and "
                     "denominator are consistent."),
               values={
                   "n_industries_with_nonaccruals": int(len(t)),
                   "pooled_na_cost_usd_bn": round(float(na.cost.sum()) / 1e9, 3),
                   "top12_share_of_pooled_na_cost_pct": round(
                       100.0 * float(top.cost_na.sum() / na.cost.sum()), 2),
               })
    return {"na": t, "na_rows": len(na)}


# ------------------------------------------------------------------ (f)

def part_f(inv: pd.DataFrame) -> dict:
    """Persistence measured in PANEL quarters, not calendar quarters.

    The 30 quarters present in the panel are indexed 0..29 in time order.
    A borrower's spell is a run of consecutive *panel* indices in which the
    borrower appears.  Because 2019Q3 and 2022Q1 are missing from the panel,
    a borrower present on both sides of a gap is treated as continuous: the
    measure cannot distinguish "stayed through the gap" from "left and came
    back inside it", and that is why it is called approximate.
    """
    qs = sorted(inv.quarter.unique())
    idx = {qq: k for k, qq in enumerate(qs)}
    pres = inv[["borrower", "quarter"]].drop_duplicates()
    pres["k"] = pres.quarter.map(idx)

    longest, total_q = {}, {}
    for b, grp in pres.groupby("borrower"):
        ks = sorted(grp.k)
        total_q[b] = len(ks)
        best = run = 1
        for a, c in zip(ks, ks[1:]):
            run = run + 1 if c == a + 1 else 1
            best = max(best, run)
        longest[b] = best
    sp = pd.DataFrame({"borrower": list(longest), "longest_spell": list(longest.values())})
    sp["quarters_present"] = sp.borrower.map(total_q)

    lat = inv[inv.quarter == LATEST]
    lat_fv = lat.fair_value.sum()
    since_start = set(inv[inv.quarter == FIRST].borrower)
    lat_borr = set(lat.borrower)
    survivors = since_start & lat_borr
    surv_fv = lat[lat.borrower.isin(survivors)].fair_value.sum()

    # borrowers in the latest quarter, by their longest spell
    lat_sp = sp.set_index("borrower").longest_spell
    lat_g = lat.assign(spell=lat.borrower.map(lat_sp))
    bins = [0, 2, 4, 8, 12, 20, 31]
    labels = ["1-2", "3-4", "5-8", "9-12", "13-20", "21-30"]
    lat_g["bucket"] = pd.cut(lat_g.spell, bins=bins, labels=labels, right=True)
    fv_by_bucket = lat_g.groupby("bucket", observed=False).fair_value.sum()
    fv_by_bucket_pct = 100.0 * fv_by_bucket / lat_fv
    cnt_by_bucket = (sp.assign(bucket=pd.cut(sp.longest_spell, bins=bins,
                                             labels=labels, right=True))
                     .groupby("bucket", observed=False).size())

    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.9))
    ax = axes[0]
    ax.bar(np.arange(len(cnt_by_bucket)), cnt_by_bucket.values, color=NAVY, width=0.7)
    ax.set_xticks(np.arange(len(cnt_by_bucket)))
    ax.set_xticklabels(labels)
    ax.set_xlabel("Longest run of consecutive panel quarters")
    ax.set_ylabel("Borrowers (equal-weight count)")
    ax.set_title("All borrowers ever in the window", fontsize=8.5)
    for i, v in enumerate(cnt_by_bucket.values):
        ax.text(i, v, f"{v:,}", ha="center", va="bottom", fontsize=6.6, color="#42505E")

    ax = axes[1]
    ax.bar(np.arange(len(fv_by_bucket_pct)), fv_by_bucket_pct.values, color=TEAL, width=0.7)
    ax.set_xticks(np.arange(len(fv_by_bucket_pct)))
    ax.set_xticklabels(labels)
    ax.set_xlabel("Longest run of consecutive panel quarters")
    ax.set_ylabel(f"Share of {LATEST} fair value")
    pct_axis(ax)
    ax.set_title(f"{LATEST} fair value by longest-ever spell", fontsize=8.5)
    for i, v in enumerate(fv_by_bucket_pct.values):
        ax.text(i, v, f"{v:.0f}%", ha="center", va="bottom", fontsize=6.6, color="#42505E")
    fig.tight_layout(rect=(0, 0, 1, 0.93))

    cov = Coverage("investment-panel", int(len(inv)), INV_TOTAL,
                   note=(f"Spells are runs of consecutive PANEL quarters (the {len(qs)} "
                         "quarters actually present), not calendar quarters. "
                         f"{' and '.join(missing_quarters(qs).values())} are missing, so a "
                         "borrower present either side of a gap is counted as continuous; "
                         "the measure is therefore an upper bound on true continuous tenure. "
                         "Borrower identity is the raw filing string, so a rename breaks a "
                         "spell and inflates the count. Both panels bin on the LONGEST-EVER "
                         "spell in the window, not on tenure as at the latest quarter: a "
                         "borrower with a long early run who returned recently sits in a high "
                         "band. The left panel is an equal-weighted count of names over all "
                         f"{int(len(sp)):,} borrowers ever in the window; the right panel is "
                         f"fair-value weighted over the {int(lat.borrower.nunique())} borrowers "
                         f"held in {LATEST} only."))
    save_fig(fig, "m5_borrower_persistence",
             "How long a borrower stays in the book",
             PERIOD, cov,
             subtitle="Longest consecutive panel-quarter spell per borrower, and the fair value that sits with each tenure band",
             values={
                 "n_distinct_borrowers_window": int(len(sp)),
                 "median_longest_spell_quarters": float(sp.longest_spell.median()),
                 "mean_longest_spell_quarters": round(float(sp.longest_spell.mean()), 2),
                 "share_borrowers_spell_le_2_pct": round(
                     100.0 * float((sp.longest_spell <= 2).mean()), 2),
                 "share_borrowers_spell_ge_21_pct": round(
                     100.0 * float((sp.longest_spell >= 21).mean()), 2),
                 "n_borrowers_full_30_quarters": int((sp.longest_spell == 30).sum()),
                 "latest_fv_share_borrowers_since_2018q3_pct": round(
                     100.0 * float(surv_fv / lat_fv), 2),
                 "n_borrowers_since_2018q3_still_present": int(len(survivors)),
                 "n_borrowers_2018q3": int(len(since_start)),
                 "n_borrowers_latest": int(len(lat_borr)),
                 "latest_fv_usd_bn": round(float(lat_fv) / 1e9, 3),
                 "denominator": f"{LATEST} total fair value for the FV shares; "
                                f"{len(sp):,} distinct borrowers for the count shares",
             })
    return {"spells": sp, "surv_share": 100.0 * surv_fv / lat_fv,
            "n_surv": len(survivors)}


# ------------------------------------------------------------------ main

def main() -> None:
    global INV_TOTAL, Q_TOTAL, LATEST, FIRST
    qtr, inv = load_panels()
    INV_TOTAL, Q_TOTAL = len(inv), len(qtr)
    qs = sorted(inv.quarter.unique())
    FIRST, LATEST = qs[0], qs[-1]

    raw_labels = inv.industry.nunique()
    norm_labels = inv.industry_norm.nunique()
    print(f"window: {FIRST}..{LATEST}, {len(qs)} panel quarters, "
          f"{INV_TOTAL:,} investment rows, {Q_TOTAL} quarter rows")
    print(f"industry labels: {raw_labels} raw -> {norm_labels} normalized")

    a = part_a(inv)
    b = part_b(inv)
    c = part_c(inv)
    d = part_d(inv)
    e = part_e(inv)
    f = part_f(inv)

    # ---- independent recomputations (different code path than the exhibits)
    lat = inv[inv.quarter == LATEST]
    chk_top1 = (lat[lat.industry_norm == "Software and Services"].fair_value.sum()
                / lat.fair_value.sum() * 100)
    print(f"CHECK top-1 industry share {LATEST}: {chk_top1:.4f}% "
          f"(exhibit: {a['comp'].set_index('industry_norm').share_latest_pct.get('Software and Services'):.4f}%)")

    shares = lat.groupby("borrower").fair_value.sum().sort_values(ascending=False)
    chk_top10 = 100 * shares.head(10).sum() / lat.fair_value.sum()
    print(f"CHECK top-10 borrower share {LATEST}: {chk_top10:.4f}% "
          f"(exhibit: {c['bconc'].top10_share_pct.iloc[-1]:.4f}%)")

    chk_hhi = float(((lat.groupby("industry_norm").fair_value.sum()
                      / lat.fair_value.sum() * 100) ** 2).sum())
    print(f"CHECK industry HHI {LATEST}: {chk_hhi:.2f} "
          f"(exhibit: {b['conc'].hhi_industry.iloc[-1]:.2f})")

    na = inv[inv.is_non_accrual]
    print(f"CHECK non-accrual rows: {len(na)} ({100*len(na)/len(inv):.2f}% of {len(inv):,})")

    print(f"CHECK survivor FV share since {FIRST}: {f['surv_share']:.2f}% "
          f"({f['n_surv']} borrowers)")

    dump_exhibit_log("m5_cross_section")
    print("done")


if __name__ == "__main__":
    main()
