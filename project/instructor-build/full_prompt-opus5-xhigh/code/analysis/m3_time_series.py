"""Module 3: the through-time story for ARCC, 2018Q3-2026Q2.

Six exhibits plus three tables:
  (a) portfolio growth, levels and indexed to 100 at 2018Q3
  (b) leverage: debt / net assets and debt / total assets
  (c) rate-benchmark transition on the debt book (LIBOR -> SOFR)
  (d) FV-weighted all-in yield and spread, with per-quarter coverage
  (e) credit stress: non-accrual share and aggregate FV / cost
  (f) asset-mix drift by investment_type

The window contains 30 of a possible 32 calendar quarters.  2019Q3 and
2022Q1 are absent from the panel (their filings did not clear the parse
gate).  Every time series below is reindexed onto the full 32-quarter
calendar so those two quarters render as breaks in the line and holes in
the stacked areas.  Nothing is interpolated or bridged.

Run standalone from the project root:
    python3 code/analysis/m3_time_series.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from common import (
    Coverage, load_panels, save_fig, save_table, dump_exhibit_log,
    pct_axis, usd_axis, quarter_ticks,
    NAVY, TEAL, AMBER, RUST, SAGE, PLUM, SLATE, LIGHT,
)

PERIOD = "2018Q3-2026Q2"
Q_TOTAL = 30          # quarter-panel rows in window
I_TOTAL = 31067       # investment-panel rows in window
MISSING = ["2019Q3", "2022Q1"]
GAP_NOTE = ("The panel holds 30 of the 32 calendar quarters in the window: "
            "2019Q3 and 2022Q1 are absent and are shown as breaks; no value "
            "is interpolated or bridged across them.")

# Full calendar of quarters in the window, including the two missing ones.
CAL = [str(p) for p in pd.period_range("2018Q3", "2026Q2", freq="Q")]


def on_calendar(s: pd.Series) -> pd.Series:
    """Reindex a quarter-indexed series onto the full 32-quarter calendar."""
    return s.reindex(CAL)


def contiguous_blocks(mask) -> list[list[int]]:
    """Index runs where mask is True, so areas break at the missing quarters."""
    blocks, cur = [], []
    for k, ok in enumerate(mask):
        if ok:
            cur.append(k)
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    return blocks


def mark_gaps(ax) -> None:
    for gq in MISSING:
        ax.axvspan(CAL.index(gq) - 0.5, CAL.index(gq) + 0.5,
                   color="#EEF1F4", zorder=0)
        ax.text(CAL.index(gq), ax.get_ylim()[1], "no filing", rotation=90,
                fontsize=5.6, color=SLATE, va="top", ha="center")


def fv_weighted(g: pd.DataFrame, col: str) -> float:
    """FV-weighted mean of col over rows where col is present."""
    sub = g[g[col].notna() & g["fair_value"].notna()]
    w = sub["fair_value"].sum()
    return float((sub[col] * sub["fair_value"]).sum() / w) if w else np.nan


def rate_bucket(x) -> str:
    """Collapse the raw reference_rate labels into five reporting buckets.

    The debt book carries 17 distinct non-null labels (SOFR, 'SOFR (B)',
    'SOFR (W)', LIBOR, 'GBP Libor', 'fixed', Base Rate, 'CAD Base Rate',
    Euribor, CORRA, CDOR, SONIA, CIBOR, BBSY, NIBOR, BKBM, TONA) plus a
    null case, which becomes 'Unclassified'.
    """
    if not isinstance(x, str) or not x.strip() or x.strip().lower() == "nan":
        return "Unclassified"
    s = x.strip().lower()
    if "sofr" in s:
        return "SOFR"
    if "libor" in s:
        return "LIBOR"
    if s == "fixed":
        return "Fixed"
    return "Other floating"


RATE_ORDER = ["LIBOR", "SOFR", "Other floating", "Fixed", "Unclassified"]
RATE_COLOR = {"LIBOR": AMBER, "SOFR": NAVY, "Other floating": TEAL,
              "Fixed": SAGE, "Unclassified": LIGHT}
TYPE_ORDER = ["first lien", "second lien", "subordinated", "preferred",
              "equity", "other"]
TYPE_COLOR = {"first lien": NAVY, "second lien": TEAL, "subordinated": SAGE,
              "preferred": PLUM, "equity": AMBER, "other": SLATE}


def main() -> None:
    q, inv = load_panels()
    assert len(q) == Q_TOTAL, f"quarter panel is {len(q)} rows, expected {Q_TOTAL}"
    assert len(inv) == I_TOTAL, f"investment panel is {len(inv)} rows, expected {I_TOTAL}"
    q = q.set_index("quarter")
    inv["rate_bucket"] = inv["reference_rate"].map(rate_bucket)

    # ---- independent recomputation ------------------------------------
    # The balance-sheet total_investments_fv must equal the sum of the
    # position-level fair values for the same quarter.  This is the tie-out
    # that validates using the two panels side by side below.
    pos_fv = inv.groupby("quarter")["fair_value"].sum()
    chk = pd.DataFrame({"bs": q["total_investments_fv"], "soi": pos_fv}).dropna()
    max_rel = float(((chk["soi"] - chk["bs"]).abs() / chk["bs"]).max())
    print(f"tie-out: max |SOI - balance sheet| / balance sheet = {max_rel:.3e} "
          f"over {len(chk)} quarters")
    # Tolerance is 10 bps: both panels are reported in millions, so the sum of
    # ~1,000 rounded position values differs from the rounded balance-sheet
    # total by rounding only.  Observed max is 4.5e-5 (0.0045%).
    assert max_rel < 1e-3, "SOI total does not tie to the balance sheet"

    x = np.arange(len(CAL))
    facts: dict[str, dict] = {}

    # ================================================== (a) growth
    lev = {c: on_calendar(q[c]) for c in
           ("total_investments_fv", "total_assets", "net_assets")}
    fig, ax = plt.subplots()
    for col, lab, c in [("total_assets", "Total assets", SLATE),
                        ("total_investments_fv", "Investments at fair value", NAVY),
                        ("net_assets", "Net assets", TEAL)]:
        ax.plot(x, lev[col].values, color=c, label=lab,
                lw=2.0 if col == "total_investments_fv" else 1.4)
    usd_axis(ax, "bn", 0)
    quarter_ticks(ax, CAL, every=4)
    ax.set_xlim(-0.5, len(CAL) - 0.5)
    ax.legend(loc="upper left")
    mark_gaps(ax)
    base_fv = lev["total_investments_fv"]["2018Q3"]
    end_fv = lev["total_investments_fv"]["2026Q2"]
    base_na = lev["net_assets"]["2018Q3"]
    end_na = lev["net_assets"]["2026Q2"]
    base_ta = lev["total_assets"]["2018Q3"]
    end_ta = lev["total_assets"]["2026Q2"]
    # CAGR is compounded over ELAPSED time, not over the count of quarters
    # observed.  2018Q3 and 2026Q2 are 32 quarter-*labels* inclusive, but the
    # span between the two balance-sheet dates (2018-09-30 -> 2026-06-30) is
    # 31 quarters = 7.75 years.  Using 8.0 here understated the growth rate
    # by roughly 44bps per year.
    n_yrs = 7.75
    cagr_fv = ((end_fv / base_fv) ** (1 / n_yrs) - 1) * 100
    cagr_na = ((end_na / base_na) ** (1 / n_yrs) - 1) * 100
    v_growth = {
        "investments_fv_2018Q3_usd_bn": round(base_fv / 1e9, 3),
        "investments_fv_2026Q2_usd_bn": round(end_fv / 1e9, 3),
        "investments_fv_growth_pct": round((end_fv / base_fv - 1) * 100, 1),
        "cagr_years_elapsed": n_yrs,
        "cagr_endpoints": "period_end 2018-09-30 to 2026-06-30 (31 quarters)",
        "investments_fv_cagr_pct_per_yr": round(cagr_fv, 2),
        "total_assets_2018Q3_usd_bn": round(base_ta / 1e9, 3),
        "total_assets_2026Q2_usd_bn": round(end_ta / 1e9, 3),
        "net_assets_2018Q3_usd_bn": round(base_na / 1e9, 3),
        "net_assets_2026Q2_usd_bn": round(end_na / 1e9, 3),
        "net_assets_growth_pct": round((end_na / base_na - 1) * 100, 1),
        "net_assets_cagr_pct_per_yr": round(cagr_na, 2),
        "cagr_caveat": ("endpoint-to-endpoint compound rate; the two missing "
                        "quarters are interior and do not affect it, but no "
                        "intra-window path is implied"),
    }
    facts["ts_growth_levels"] = v_growth
    save_fig(fig, "ts_growth_levels",
             "Balance sheet in levels, quarter by quarter",
             PERIOD,
             Coverage("quarter-panel", Q_TOTAL, Q_TOTAL, GAP_NOTE +
                      " The growth rate is an endpoint-to-endpoint compound "
                      "rate over the 7.75 years from 2018-09-30 to 2026-06-30, "
                      "not an average of quarterly growth."),
             subtitle=("Investments at fair value grew from "
                       f"${base_fv/1e9:.1f}bn to ${end_fv/1e9:.1f}bn "
                       f"({cagr_fv:.1f}% per year over 7.75 years)"),
             values=v_growth)

    # indexed
    fig, ax = plt.subplots()
    idx_vals = {}
    for col, lab, c in [("total_assets", "Total assets", SLATE),
                        ("total_investments_fv", "Investments at fair value", NAVY),
                        ("net_assets", "Net assets", TEAL)]:
        s = on_calendar(q[col]) / q.loc["2018Q3", col] * 100
        idx_vals[col] = s
        ax.plot(x, s.values, color=c, label=lab,
                lw=2.0 if col == "total_investments_fv" else 1.4)
    ax.axhline(100, color=SLATE, lw=0.8, ls=":")
    quarter_ticks(ax, CAL, every=4)
    ax.set_xlim(-0.5, len(CAL) - 0.5)
    ax.set_ylabel("Index, 2018Q3 = 100")
    ax.legend(loc="upper left")
    mark_gaps(ax)
    v_idx = {
        "index_base_quarter": "2018Q3 = 100",
        "investments_fv_index_2026Q2": round(float(idx_vals["total_investments_fv"]["2026Q2"]), 1),
        "total_assets_index_2026Q2": round(float(idx_vals["total_assets"]["2026Q2"]), 1),
        "net_assets_index_2026Q2": round(float(idx_vals["net_assets"]["2026Q2"]), 1),
        "investments_fv_index_2020Q2_covid": round(float(idx_vals["total_investments_fv"]["2020Q2"]), 1),
        "net_assets_index_2020Q1_covid": round(float(idx_vals["net_assets"]["2020Q1"]), 1),
    }
    facts["ts_growth_indexed"] = v_idx
    save_fig(fig, "ts_growth_indexed",
             "Balance sheet indexed to 100 at 2018Q3",
             PERIOD,
             Coverage("quarter-panel", Q_TOTAL, Q_TOTAL, GAP_NOTE),
             subtitle=("Investments reach "
                       f"{v_idx['investments_fv_index_2026Q2']:.0f} and net assets "
                       f"{v_idx['net_assets_index_2026Q2']:.0f} by 2026Q2"),
             values=v_idx)

    # ================================================== (b) leverage
    dna = on_calendar(q["total_debt_outstanding"] / q["net_assets"])
    dta = on_calendar(q["total_debt_outstanding"] / q["total_assets"] * 100)
    fig, ax = plt.subplots()
    ax.plot(x, dna.values, color=NAVY, label="Debt / net assets (x)", lw=2.0)
    ax.set_ylabel("Debt / net assets (x)")
    ax.set_ylim(0, 1.45)
    ax2 = ax.twinx()
    ax2.plot(x, dta.values, color=AMBER, label="Debt / total assets (%)", lw=1.4)
    ax2.set_ylabel("Debt / total assets (%)")
    ax2.set_ylim(0, 72)
    ax2.grid(False)
    pct_axis(ax2, 0)
    quarter_ticks(ax, CAL, every=4)
    ax.set_xlim(-0.5, len(CAL) - 0.5)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="lower right")
    mark_gaps(ax)
    peak_q = dna.idxmax()
    v_lev = {
        "debt_net_assets_2018Q3_x": round(float(dna["2018Q3"]), 3),
        "debt_net_assets_2026Q2_x": round(float(dna["2026Q2"]), 3),
        "debt_net_assets_peak_x": round(float(dna.max()), 3),
        "debt_net_assets_peak_quarter": peak_q,
        "debt_net_assets_2020Q1_covid_x": round(float(dna["2020Q1"]), 3),
        "debt_net_assets_2020Q2_x": round(float(dna["2020Q2"]), 3),
        "debt_total_assets_2018Q3_pct": round(float(dta["2018Q3"]), 1),
        "debt_total_assets_2026Q2_pct": round(float(dta["2026Q2"]), 1),
        "debt_total_assets_2020Q1_pct": round(float(dta["2020Q1"]), 1),
        "first_quarter_debt_net_assets_above_1x": dna.dropna()[dna.dropna() > 1].index[0],
        "quarters_above_1x_of_30": int((dna.dropna() > 1).sum()),
        "denominator": "quarter-panel balance sheet, 30 quarters",
    }
    facts["ts_leverage"] = v_lev
    save_fig(fig, "ts_leverage",
             "Leverage: debt to net assets and debt to total assets",
             PERIOD,
             Coverage("quarter-panel", Q_TOTAL, Q_TOTAL,
                      GAP_NOTE + " Debt is total_debt_outstanding as reported "
                      "on the balance sheet; it is not adjusted for cash."),
             subtitle=(f"{dna['2018Q3']:.2f}x at 2018Q3, peaking at "
                       f"{dna.max():.2f}x in {peak_q}, {dna['2026Q2']:.2f}x at 2026Q2"),
             values=v_lev)

    lev_tab = pd.DataFrame({
        "quarter": CAL,
        "total_debt_usd_bn": (on_calendar(q["total_debt_outstanding"]) / 1e9).round(3).values,
        "net_assets_usd_bn": (on_calendar(q["net_assets"]) / 1e9).round(3).values,
        "debt_net_assets_x": dna.round(3).values,
        "debt_total_assets_pct": dta.round(1).values,
        "nav_per_share_derived_usd": on_calendar(
            q["net_assets"] / q["shares_outstanding"]).round(2).values,
    })
    lev_tab["status"] = np.where(lev_tab["quarter"].isin(MISSING),
                                 "no filing parsed", "reported")
    save_table(lev_tab, "ts_leverage_table",
               "Leverage and NAV per share by quarter",
               PERIOD,
               Coverage("quarter-panel", Q_TOTAL, Q_TOTAL, GAP_NOTE),
               note=("NAV per share is derived as net_assets / shares_outstanding "
                     "because the reported nav_per_share column is null in 27 of "
                     "the 30 in-window quarters (90%)."),
               values={
                   "nav_per_share_derived_2018Q3_usd": round(
                       float(q.loc['2018Q3', 'net_assets'] / q.loc['2018Q3', 'shares_outstanding']), 2),
                   "nav_per_share_derived_2026Q2_usd": round(
                       float(q.loc['2026Q2', 'net_assets'] / q.loc['2026Q2', 'shares_outstanding']), 2),
                   "nav_per_share_derived_2020Q1_usd": round(
                       float(q.loc['2020Q1', 'net_assets'] / q.loc['2020Q1', 'shares_outstanding']), 2),
                   "rows": len(lev_tab),
               })

    # ================================================== (c) rate transition
    dbt = inv[inv["debt_like"]].copy()
    dbt_fv = dbt.groupby("quarter")["fair_value"].sum()
    mix = (dbt.pivot_table(index="quarter", columns="rate_bucket",
                           values="fair_value", aggfunc="sum")
           .reindex(columns=RATE_ORDER).fillna(0.0))
    assert set(dbt["rate_bucket"].unique()) <= set(RATE_ORDER), "rate bucket lost"
    mix_pct = mix.div(dbt_fv, axis=0) * 100
    # Every quarter's five buckets must exhaust that quarter's debt-book FV.
    assert float((mix_pct.sum(axis=1) - 100).abs().max()) < 1e-6, \
        "reference-rate buckets do not exhaust the debt-book fair value"
    mix_pct = mix_pct.reindex(CAL)

    fig, ax = plt.subplots()
    have = mix_pct.notna().all(axis=1).values
    base = np.zeros(len(CAL))
    for b in RATE_ORDER:
        vals = mix_pct[b].values
        top = base + np.nan_to_num(vals)
        for blk in contiguous_blocks(have):
            ax.fill_between(x[blk], base[blk], top[blk], color=RATE_COLOR[b],
                            lw=0, label=b if blk == contiguous_blocks(have)[0] else None)
        base = top
    ax.set_ylim(0, 100)
    ax.set_ylabel("Share of debt-book fair value")
    pct_axis(ax, 0)
    quarter_ticks(ax, CAL, every=4)
    ax.set_xlim(-0.5, len(CAL) - 0.5)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.28), ncol=5, fontsize=7)
    mark_gaps(ax)
    obs = mix_pct.dropna()
    cross = obs[obs["SOFR"] > obs["LIBOR"]]
    cross_q = cross.index[0] if len(cross) else None
    prev_q = obs.index[obs.index.get_loc(cross_q) - 1] if cross_q else None
    sofr_first = obs[obs["SOFR"] > 0].index[0]
    libor_end = obs[obs["LIBOR"] > 0].index[-1]
    v_rate = {
        "basis": "FV-weighted share of the debt book (first lien, second lien, subordinated)",
        "crossover_quarter_sofr_exceeds_libor": cross_q,
        "sofr_share_at_crossover_pct": round(float(obs.loc[cross_q, "SOFR"]), 1),
        "libor_share_at_crossover_pct": round(float(obs.loc[cross_q, "LIBOR"]), 1),
        "sofr_share_prior_quarter_pct": round(float(obs.loc[prev_q, "SOFR"]), 1),
        "libor_share_prior_quarter_pct": round(float(obs.loc[prev_q, "LIBOR"]), 1),
        "prior_quarter": prev_q,
        "first_quarter_with_any_sofr": sofr_first,
        "last_quarter_with_any_libor": libor_end,
        "libor_share_2018Q3_pct": round(float(obs.loc["2018Q3", "LIBOR"]), 1),
        "sofr_share_2026Q2_pct": round(float(obs.loc["2026Q2", "SOFR"]), 1),
        "libor_share_2026Q2_pct": round(float(obs.loc["2026Q2", "LIBOR"]), 1),
        "unclassified_share_2018Q3_pct": round(float(obs.loc["2018Q3", "Unclassified"]), 1),
        "unclassified_share_2026Q2_pct": round(float(obs.loc["2026Q2", "Unclassified"]), 1),
        "debt_book_fv_share_of_panel_fv_pct": round(
            100 * dbt["fair_value"].sum() / inv["fair_value"].sum(), 1),
        "debt_book_rows": int(len(dbt)),
        "debt_book_row_share_of_panel_pct": round(100 * len(dbt) / I_TOTAL, 1),
        "raw_reference_rate_labels_n": int(dbt["reference_rate"].dropna().nunique()),
        "reference_rate_null_share_of_debt_rows_pct": round(
            100 * dbt["reference_rate"].isna().mean(), 1),
    }
    # The two shares below are different numbers and must not be swapped:
    # the debt book is 70.5% of in-window *rows* but 77.5% of panel *fair
    # value*.  Every share in this exhibit is the fair-value one.
    DBT_COV_NOTE = (
        f" Debt-like rows are {100*len(dbt)/I_TOTAL:.1f}% of in-window panel "
        f"rows and {v_rate['debt_book_fv_share_of_panel_fv_pct']:.1f}% of "
        "in-window panel fair value; the shares plotted are fair-value "
        "shares, never position counts.")
    facts["ts_rate_mix"] = v_rate
    save_fig(fig, "ts_rate_mix",
             "Reference-rate mix of the debt book, weighted by fair value",
             PERIOD,
             Coverage("investment-panel, debt-like positions", len(dbt), I_TOTAL,
                      GAP_NOTE + DBT_COV_NOTE + " 'Unclassified' is positions "
                      "with no reference_rate parsed from the filing "
                      f"({100*dbt['reference_rate'].isna().mean():.1f}% of "
                      "debt-book rows); they are kept in the denominator, not "
                      "dropped."),
             subtitle=(f"SOFR overtakes LIBOR in {cross_q} "
                       f"({obs.loc[cross_q,'SOFR']:.0f}% vs {obs.loc[cross_q,'LIBOR']:.0f}%); "
                       f"LIBOR last appears in {libor_end}"),
             values=v_rate)

    rate_tab = mix_pct.round(1).reset_index().rename(columns={"index": "quarter"})
    rate_tab.columns = ["quarter"] + [f"{c}_pct_of_debt_fv" for c in RATE_ORDER]
    rate_tab["debt_book_fv_usd_bn"] = (on_calendar(dbt_fv) / 1e9).round(3).values
    rate_tab["status"] = np.where(rate_tab["quarter"].isin(MISSING),
                                  "no filing parsed", "reported")
    save_table(rate_tab, "ts_rate_mix_table",
               "Reference-rate mix of the debt book by quarter (FV-weighted)",
               PERIOD,
               Coverage("investment-panel, debt-like positions", len(dbt), I_TOTAL,
                        GAP_NOTE + DBT_COV_NOTE),
               note=("Denominator each quarter is that quarter's debt-book fair "
                     "value (first lien, second lien and subordinated only), so "
                     "each row sums to 100%. Rows for 2019Q3 and 2022Q1 are "
                     "blank by construction."),
               values=v_rate)

    # ================================================== (d) yield and spread
    yr = dbt.groupby("quarter").apply(
        lambda g: pd.Series({
            "rate": fv_weighted(g, "all_in_rate_pct"),
            "spread": fv_weighted(g, "spread_bps"),
            "rate_cov": 100 * g.loc[g.all_in_rate_pct.notna(), "fair_value"].sum() / g["fair_value"].sum(),
            "spread_cov": 100 * g.loc[g.spread_bps.notna(), "fair_value"].sum() / g["fair_value"].sum(),
        }), include_groups=False).reindex(CAL)

    fig, (axa, axb) = plt.subplots(2, 1, figsize=(7.2, 5.2), sharex=True)
    axa.plot(x, yr["rate"].values, color=NAVY, lw=2.0, label="FV-weighted all-in rate")
    axa.set_ylabel("All-in rate (%)")
    pct_axis(axa, 1)
    axa.legend(loc="upper left")
    axb.plot(x, yr["spread"].values, color=RUST, lw=2.0, label="FV-weighted spread")
    axb.set_ylabel("Spread (bps)")
    axb.legend(loc="upper left")
    for ax_, cov_col, c in ((axa, "rate_cov", NAVY), (axb, "spread_cov", RUST)):
        axc = ax_.twinx()
        axc.bar(x, yr[cov_col].values, color=LIGHT, width=0.7, zorder=0, alpha=0.65)
        axc.set_ylim(0, 400)
        axc.set_yticks([0, 50, 100])
        axc.set_ylabel("FV coverage (%)", fontsize=7)
        axc.grid(False)
        ax_.set_zorder(axc.get_zorder() + 1)
        ax_.patch.set_visible(False)
    quarter_ticks(axb, CAL, every=4)
    axb.set_xlim(-0.5, len(CAL) - 0.5)
    for ax_ in (axa, axb):
        mark_gaps(ax_)
    o = yr.dropna(subset=["rate"])
    rate_min_q, rate_max_q = o["rate"].idxmin(), o["rate"].idxmax()
    os_ = yr.dropna(subset=["spread"])
    v_yield = {
        "basis": "FV-weighted over debt-like positions with the field present",
        "all_in_rate_2018Q3_pct": round(float(yr.loc["2018Q3", "rate"]), 2),
        "all_in_rate_2026Q2_pct": round(float(yr.loc["2026Q2", "rate"]), 2),
        "all_in_rate_trough_pct": round(float(o["rate"].min()), 2),
        "all_in_rate_trough_quarter": rate_min_q,
        "all_in_rate_peak_pct": round(float(o["rate"].max()), 2),
        "all_in_rate_peak_quarter": rate_max_q,
        "all_in_rate_trough_to_peak_bps": round(
            float(o["rate"].max() - o["rate"].min()) * 100, 0),
        "spread_bps_2018Q3": round(float(yr.loc["2018Q3", "spread"]), 0),
        "spread_bps_2026Q2": round(float(yr.loc["2026Q2", "spread"]), 0),
        "spread_bps_peak": round(float(os_["spread"].max()), 0),
        "spread_bps_peak_quarter": os_["spread"].idxmax(),
        "spread_bps_trough": round(float(os_["spread"].min()), 0),
        "spread_bps_trough_quarter": os_["spread"].idxmin(),
        "rate_fv_coverage_min_pct": round(float(o["rate_cov"].min()), 1),
        "rate_fv_coverage_min_quarter": o["rate_cov"].idxmin(),
        "spread_fv_coverage_min_pct": round(float(os_["spread_cov"].min()), 1),
        "spread_fv_coverage_min_quarter": os_["spread_cov"].idxmin(),
        "spread_fv_coverage_2026Q2_pct": round(float(yr.loc["2026Q2", "spread_cov"]), 1),
        # The spread peak lands in the single worst-covered quarter, so the
        # peak is the least reliable point on the series.  Stamp it.
        "spread_fv_coverage_at_peak_quarter_pct": round(
            float(yr.loc[os_["spread"].idxmax(), "spread_cov"]), 1),
        "rate_fv_coverage_at_peak_quarter_pct": round(
            float(yr.loc[rate_max_q, "rate_cov"]), 1),
        "debt_rows_with_all_in_rate": int(dbt["all_in_rate_pct"].notna().sum()),
        "debt_rows_with_spread": int(dbt["spread_bps"].notna().sum()),
        "debt_rows_total": int(len(dbt)),
        "weighting": "fair-value weighted; rows with the field null are excluded "
                     "from both numerator and denominator of that quarter's mean",
    }
    facts["ts_yield_spread"] = v_yield
    save_fig(fig, "ts_yield_spread",
             "All-in rate and spread on the debt book, fair-value weighted",
             PERIOD,
             Coverage("investment-panel, debt-like positions", len(dbt), I_TOTAL,
                      GAP_NOTE + DBT_COV_NOTE + " Grey bars are the share of "
                      "that quarter's debt-book fair value for which the field "
                      "was parsed; the FV-weighted mean is taken over that "
                      "share only, so rows with a null rate or spread are "
                      f"dropped from both numerator and denominator "
                      f"({dbt['spread_bps'].notna().sum():,} of {len(dbt):,} "
                      "debt rows carry a spread). The spread peak falls in "
                      f"{os_['spread'].idxmax()}, the worst-covered quarter "
                      f"({yr.loc[os_['spread'].idxmax(), 'spread_cov']:.1f}% "
                      "of debt-book FV). Bars are drawn on a 0-100% scale "
                      "compressed into the lower quarter of the panel."),
             subtitle=(f"All-in rate troughs at {o['rate'].min():.2f}% in {rate_min_q} "
                       f"and peaks at {o['rate'].max():.2f}% in {rate_max_q}"),
             values=v_yield)

    # ================================================== (e) credit stress
    agg = inv.groupby("quarter").apply(
        lambda g: pd.Series({
            "fv": g["fair_value"].sum(),
            "cost": g["cost"].sum(),
            "na_fv": g.loc[g.is_non_accrual, "fair_value"].sum(),
            "na_cost": g.loc[g.is_non_accrual, "cost"].sum(),
            "na_n": int(g.is_non_accrual.sum()),
        }), include_groups=False).reindex(CAL)
    agg["na_fv_pct"] = agg["na_fv"] / agg["fv"] * 100
    agg["na_cost_pct"] = agg["na_cost"] / agg["cost"] * 100
    agg["fv_cost"] = agg["fv"] / agg["cost"] * 100

    # Data quality: three 10-K quarters (2022Q4, 2023Q4, 2024Q4) carry exactly
    # zero non-accrual flags while both neighbouring quarters carry 13 to 22.
    # An exact zero there is a parse miss on the non-accrual footnote marker,
    # not a quarter with no non-accruals, so those quarters are dropped from
    # the non-accrual series rather than plotted as 0%.  FV/cost is unaffected:
    # cost and fair_value are 0% null in every quarter.
    na_missing = [qq for qq in agg.dropna(subset=["fv"]).index
                  if agg.loc[qq, "na_n"] == 0]
    agg.loc[na_missing, ["na_fv_pct", "na_cost_pct"]] = np.nan
    print("non-accrual flag not parsed in:", na_missing)

    fig, (axa, axb) = plt.subplots(2, 1, figsize=(7.2, 5.2), sharex=True)
    axa.plot(x, agg["na_cost_pct"].values, color=RUST, lw=2.0,
             label="Non-accrual, % of cost")
    axa.plot(x, agg["na_fv_pct"].values, color=AMBER, lw=1.5,
             label="Non-accrual, % of fair value")
    axa.set_ylabel("Non-accrual share")
    pct_axis(axa, 1)
    axa.legend(loc="upper right")
    axb.plot(x, agg["fv_cost"].values, color=NAVY, lw=2.0,
             label="Aggregate fair value / cost")
    axb.axhline(100, color=SLATE, lw=0.8, ls=":")
    axb.set_ylabel("FV / cost")
    pct_axis(axb, 0)
    axb.legend(loc="lower right")
    quarter_ticks(axb, CAL, every=4)
    axb.set_xlim(-0.5, len(CAL) - 0.5)
    for ax_ in (axa, axb):
        mark_gaps(ax_)
    oc = agg.dropna(subset=["fv_cost"])
    trough_q = oc["fv_cost"].idxmin()
    v_stress = {
        "basis": "all in-window investment rows; cost and fair_value are 0% null",
        "fv_cost_2019Q4_pre_covid_pct": round(float(agg.loc["2019Q4", "fv_cost"]), 2),
        "fv_cost_2020Q1_pct": round(float(agg.loc["2020Q1", "fv_cost"]), 2),
        "fv_cost_2020Q2_pct": round(float(agg.loc["2020Q2", "fv_cost"]), 2),
        "fv_cost_trough_pct": round(float(oc["fv_cost"].min()), 2),
        "fv_cost_trough_quarter": trough_q,
        "fv_cost_drawdown_2019Q4_to_2020Q1_pp": round(
            float(agg.loc["2019Q4", "fv_cost"] - agg.loc["2020Q1", "fv_cost"]), 2),
        "fv_cost_recovery_quarter_first_above_100": oc[oc["fv_cost"] > 100].index[0],
        "fv_cost_2021Q2_pct": round(float(agg.loc["2021Q2", "fv_cost"]), 2),
        "fv_cost_2026Q2_pct": round(float(agg.loc["2026Q2", "fv_cost"]), 2),
        "unrealised_mark_2020Q1_usd_bn": round(
            float(agg.loc["2020Q1", "fv"] - agg.loc["2020Q1", "cost"]) / 1e9, 3),
        "non_accrual_cost_pct_2020Q2": round(float(agg.loc["2020Q2", "na_cost_pct"]), 2),
        "non_accrual_cost_pct_peak": round(float(agg["na_cost_pct"].max()), 2),
        "non_accrual_cost_pct_peak_quarter": agg["na_cost_pct"].idxmax(),
        # Reported separately because the cost-weighted and FV-weighted peaks
        # are easy to conflate: both land in 2020Q3, and 2020Q2 is NOT the
        # FV peak (2.58%).
        "non_accrual_fv_pct_peak": round(float(agg["na_fv_pct"].max()), 2),
        "non_accrual_fv_pct_peak_quarter": agg["na_fv_pct"].idxmax(),
        "non_accrual_fv_pct_2020Q2": round(float(agg.loc["2020Q2", "na_fv_pct"]), 2),
        "non_accrual_cost_pct_2026Q2": round(float(agg.loc["2026Q2", "na_cost_pct"]), 2),
        "non_accrual_fv_pct_2026Q2": round(float(agg.loc["2026Q2", "na_fv_pct"]), 2),
        "non_accrual_rows_in_window": int(inv["is_non_accrual"].sum()),
        "non_accrual_row_share_pct": round(100 * inv["is_non_accrual"].mean(), 2),
        "non_accrual_series_quarters_used": int(agg["na_cost_pct"].notna().sum()),
        "non_accrual_series_quarters_dropped": ", ".join(na_missing),
        "non_accrual_drop_reason": ("exactly zero non-accrual flags parsed in "
                                    "these 10-K quarters while neighbouring "
                                    "quarters carry 13 to 22 flagged positions"),
    }
    facts["ts_credit_stress"] = v_stress
    save_fig(fig, "ts_credit_stress",
             "Credit stress: non-accrual share and aggregate fair value to cost",
             PERIOD,
             Coverage("investment-panel", len(inv), I_TOTAL,
                      GAP_NOTE + " Non-accrual shares are FV- and cost-weighted, "
                      "not position counts. The non-accrual series is drawn on "
                      f"{int(agg['na_cost_pct'].notna().sum())} of the 30 "
                      f"quarters: {', '.join(na_missing)} carry "
                      "exactly zero parsed non-accrual flags while their "
                      "neighbours carry 13 to 22, so they are dropped rather "
                      "than shown as zero. FV/cost uses all 30 quarters."),
             subtitle=("FV/cost falls from "
                       f"{agg.loc['2019Q4','fv_cost']:.1f}% in 2019Q4 to "
                       f"{agg.loc['2020Q1','fv_cost']:.1f}% in 2020Q1 and first "
                       f"clears 100% again in {v_stress['fv_cost_recovery_quarter_first_above_100']}"),
             values=v_stress)

    stress_tab = agg.reset_index().rename(columns={"index": "quarter"})
    stress_tab = stress_tab[["quarter", "fv", "cost", "fv_cost",
                             "na_cost_pct", "na_fv_pct", "na_n"]]
    stress_tab["fv"] = (stress_tab["fv"] / 1e9).round(3)
    stress_tab["cost"] = (stress_tab["cost"] / 1e9).round(3)
    stress_tab.columns = ["quarter", "fair_value_usd_bn", "cost_usd_bn",
                          "fv_over_cost_pct", "non_accrual_pct_of_cost",
                          "non_accrual_pct_of_fv", "non_accrual_positions_n"]
    for c in ["fv_over_cost_pct", "non_accrual_pct_of_cost", "non_accrual_pct_of_fv"]:
        stress_tab[c] = stress_tab[c].round(2)
    stress_tab["status"] = np.where(
        stress_tab["quarter"].isin(MISSING), "no filing parsed",
        np.where(stress_tab["quarter"].isin(na_missing),
                 "reported; non-accrual flag not parsed", "reported"))
    save_table(stress_tab, "ts_credit_stress_table",
               "Marks and non-accruals by quarter",
               PERIOD,
               Coverage("investment-panel", len(inv), I_TOTAL, GAP_NOTE),
               note=("Position-level fair value sums to the reported balance-sheet "
                     "total_investments_fv in every one of the 30 quarters "
                     f"(max relative difference {max_rel:.1e}), which is the tie-out "
                     "used to validate mixing the two panels."),
               values=v_stress)

    # ================================================== (f) asset mix drift
    # TYPE_ORDER must cover every label, otherwise .reindex(columns=...) would
    # silently drop fair value from the denominator and the shares would still
    # sum to 100% while describing less than the whole portfolio.
    missing_types = set(inv["investment_type"].dropna().unique()) - set(TYPE_ORDER)
    assert not missing_types, f"investment_type labels not plotted: {missing_types}"
    assert inv["investment_type"].isna().sum() == 0, "null investment_type present"
    tmix = (inv.pivot_table(index="quarter", columns="investment_type",
                            values="fair_value", aggfunc="sum")
            .reindex(columns=TYPE_ORDER).fillna(0.0))
    tmix_pct = (tmix.div(tmix.sum(axis=1), axis=0) * 100).reindex(CAL)
    fig, ax = plt.subplots()
    have = tmix_pct.notna().all(axis=1).values
    blocks = contiguous_blocks(have)
    base = np.zeros(len(CAL))
    for t in TYPE_ORDER:
        top = base + np.nan_to_num(tmix_pct[t].values)
        for bi, blk in enumerate(blocks):
            ax.fill_between(x[blk], base[blk], top[blk], color=TYPE_COLOR[t],
                            lw=0, label=t if bi == 0 else None)
        base = top
    ax.set_ylim(0, 100)
    ax.set_ylabel("Share of portfolio fair value")
    pct_axis(ax, 0)
    quarter_ticks(ax, CAL, every=4)
    ax.set_xlim(-0.5, len(CAL) - 0.5)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.28), ncol=6, fontsize=7)
    mark_gaps(ax)
    ot = tmix_pct.dropna()
    v_mix = {
        "basis": "FV share of the whole investment panel, by investment_type",
        "first_lien_share_2018Q3_pct": round(float(ot.loc["2018Q3", "first lien"]), 1),
        "first_lien_share_2026Q2_pct": round(float(ot.loc["2026Q2", "first lien"]), 1),
        "first_lien_change_pp": round(
            float(ot.loc["2026Q2", "first lien"] - ot.loc["2018Q3", "first lien"]), 1),
        "second_lien_share_2018Q3_pct": round(float(ot.loc["2018Q3", "second lien"]), 1),
        "second_lien_share_2026Q2_pct": round(float(ot.loc["2026Q2", "second lien"]), 1),
        "subordinated_share_2018Q3_pct": round(float(ot.loc["2018Q3", "subordinated"]), 1),
        "subordinated_share_2026Q2_pct": round(float(ot.loc["2026Q2", "subordinated"]), 1),
        "equity_share_2018Q3_pct": round(float(ot.loc["2018Q3", "equity"]), 1),
        "equity_share_2026Q2_pct": round(float(ot.loc["2026Q2", "equity"]), 1),
        "senior_secured_first_plus_second_2018Q3_pct": round(
            float(ot.loc["2018Q3", "first lien"] + ot.loc["2018Q3", "second lien"]), 1),
        "senior_secured_first_plus_second_2026Q2_pct": round(
            float(ot.loc["2026Q2", "first lien"] + ot.loc["2026Q2", "second lien"]), 1),
        # Row counts, so a fair-value share is never quoted with the wrong
        # count beside it: 2026Q2 has 1,439 positions in total, of which 965
        # are first lien.  The 59.1% is a share of fair value, not of rows.
        "positions_2026Q2_total_n": int((inv["quarter"] == "2026Q2").sum()),
        "positions_2026Q2_first_lien_n": int(
            ((inv["quarter"] == "2026Q2") & (inv["investment_type"] == "first lien")).sum()),
        "first_lien_row_share_2026Q2_pct": round(100 * float(
            ((inv["quarter"] == "2026Q2") & (inv["investment_type"] == "first lien")).sum()
            / (inv["quarter"] == "2026Q2").sum()), 1),
        "investment_type_labels_covered": ", ".join(TYPE_ORDER),
    }
    facts["ts_asset_mix"] = v_mix
    save_fig(fig, "ts_asset_mix",
             "Asset mix drift: fair-value share by investment type",
             PERIOD,
             Coverage("investment-panel", len(inv), I_TOTAL,
                      GAP_NOTE + " Shares are FV-weighted, not position counts."),
             subtitle=("First lien rises from "
                       f"{ot.loc['2018Q3','first lien']:.0f}% to "
                       f"{ot.loc['2026Q2','first lien']:.0f}% of fair value while "
                       f"second lien falls from {ot.loc['2018Q3','second lien']:.0f}% "
                       f"to {ot.loc['2026Q2','second lien']:.0f}%"),
             values=v_mix)

    dump_exhibit_log("m3_time_series")
    print("\n== headline values ==")
    for k, v in facts.items():
        print(k, v)


if __name__ == "__main__":
    main()
