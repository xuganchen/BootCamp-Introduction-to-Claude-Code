"""Module 4 - Deal terms: pricing, structure, maturity and terms-vs-risk.

Scope: the debt-like book (first lien, second lien, subordinated) of the ARCC
investment panel over 2018Q3-2026Q2, unless an exhibit says otherwise.

Coverage discipline is the binding constraint here.  spread_bps is 38.4% null
across the whole in-window investment panel, but the nulls are concentrated in
equity and preferred positions that carry no contractual spread at all.  Every
exhibit below therefore states (a) the debt-like rows it used, (b) the share of
the 31,067 in-window investment rows that represents, and (c) where relevant
the fair-value share of the debt book standing behind each cell.

Run standalone from the project root:

    python3 code/analysis/m4_deal_terms.py
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
    pct_axis, quarter_ticks,
    NAVY, TEAL, AMBER, RUST, SAGE, SLATE, LIGHT,
)

PERIOD = "2018Q3-2026Q2"
SENIORITY = ["first lien", "second lien", "subordinated"]
SEN_COLOR = {"first lien": NAVY, "second lien": AMBER, "subordinated": RUST}


# --------------------------------------------------------------- helpers

def wq(values: pd.Series, weights: pd.Series, qs) -> list[float]:
    """Weighted quantiles.  Returns NaN for any q when weights sum to zero."""
    m = values.notna() & weights.notna() & (weights > 0)
    v, w = values[m].to_numpy(float), weights[m].to_numpy(float)
    if len(v) == 0:
        return [float("nan")] * len(qs)
    o = np.argsort(v)
    v, w = v[o], w[o]
    cw = np.cumsum(w)
    # midpoint-of-mass convention: standard for weighted quantiles
    p = (cw - 0.5 * w) / cw[-1]
    return [float(np.interp(q, p, v)) for q in qs]


def runs(mask) -> list[tuple[int, int]]:
    """Contiguous [start, end) index runs where `mask` is True.

    Used to draw stacked areas in segments so that a quarter missing from
    the panel leaves a real hole instead of being spanned by a polygon.
    """
    out, start = [], None
    for k, ok in enumerate(mask):
        if ok and start is None:
            start = k
        elif not ok and start is not None:
            out.append((start, k))
            start = None
    if start is not None:
        out.append((start, len(mask)))
    return out


def mark_missing(ax, axis_quarters: list[str], missing: list[str]) -> None:
    """Shade the quarters that do not exist in the panel."""
    for qk in missing:
        k = axis_quarters.index(qk)
        ax.axvspan(k - 0.5, k + 0.5, color="#EDE7DA", alpha=0.85, lw=0, zorder=0)


def fv_share(sub: pd.DataFrame, field: str, base: pd.DataFrame) -> float:
    """Fair-value share of `base` for which `field` is populated."""
    denom = base.fair_value.sum()
    if denom <= 0:
        return float("nan")
    return 100.0 * sub.loc[sub[field].notna(), "fair_value"].sum() / denom


def main() -> None:
    qtr, inv = load_panels()
    N_INV = len(inv)                      # 31,067 in-window investment rows
    debt = inv[inv.debt_like].copy()
    N_DEBT = len(debt)
    quarters = sorted(debt.quarter.unique())
    latest = quarters[-1]
    first_q = quarters[0]

    # Calendar-continuous quarter axis.  The panel is missing 2019Q3 and
    # 2022Q1 entirely (ARCC filed, but those filings are not in the parsed
    # set).  Plotting on an ordinal index of the *observed* quarters would
    # place 2019Q2 next to 2019Q4 and silently bridge the hole, so every
    # time series below is reindexed onto QAXIS and the missing quarters
    # are drawn as shaded breaks.
    QAXIS = [str(p) for p in pd.period_range(first_q, latest, freq="Q")]
    MISSING_Q = [qk for qk in QAXIS if qk not in quarters]
    GAP_NOTE = (f"{', '.join(MISSING_Q)} are absent from the panel and are "
                "drawn as shaded breaks on a calendar-continuous axis; no "
                "value is interpolated across them.")

    debt["yrs_to_mat"] = (debt.maturity_date - debt.period_end).dt.days / 365.25
    # floating = a named reference rate other than the literal 'fixed' tag
    ref = debt.reference_rate
    debt["rate_class"] = np.where(
        ref.isna(), "undisclosed",
        np.where(ref.str.lower().eq("fixed"), "fixed", "floating"))

    values_master: dict = {}

    # ------------------------------------------------------------------
    # (a) Spread distribution by seniority, pooled and latest quarter
    # ------------------------------------------------------------------
    rows = []
    for scope, sub in (("pooled 2018Q3-2026Q2", debt),
                       (f"latest quarter ({latest})", debt[debt.quarter == latest])):
        for sen in SENIORITY:
            s = sub[sub.investment_type == sen]
            p25, p50, p75 = wq(s.spread_bps, s.fair_value, [0.25, 0.50, 0.75])
            rows.append({
                "scope": scope,
                "seniority": sen,
                "positions": len(s),
                "positions_with_spread": int(s.spread_bps.notna().sum()),
                "median_spread_bps": p50,
                "p25_spread_bps": p25,
                "p75_spread_bps": p75,
                "iqr_bps": p75 - p25,
                "fv_with_spread_usd_mm": s.loc[s.spread_bps.notna(),
                                               "fair_value"].sum() / 1e6,
                "fv_coverage_pct_of_cell": fv_share(s, "spread_bps", s),
                "fv_coverage_pct_of_debt_book": fv_share(s, "spread_bps", sub),
            })
    spread_tab = pd.DataFrame(rows)

    n_spread = int(debt.spread_bps.notna().sum())
    cov_a = Coverage(
        basis="investment-panel",
        rows_used=n_spread,
        rows_total=N_INV,
        note=(f"Debt-like positions only ({N_DEBT:,} rows); of those "
              f"{n_spread:,} carry a parsed spread_bps. Quantiles are "
              "fair-value weighted. Equity and preferred positions are "
              "excluded by construction, which is why they do not appear "
              "as missing spreads here."))
    pooled = spread_tab[spread_tab.scope.str.startswith("pooled")].set_index("seniority")
    late = spread_tab[spread_tab.scope.str.startswith("latest")].set_index("seniority")

    v_a = {
        "pooled_first_lien_median_spread_bps": round(pooled.loc["first lien", "median_spread_bps"], 1),
        "pooled_first_lien_p25_p75_bps": [round(pooled.loc["first lien", "p25_spread_bps"], 1),
                                          round(pooled.loc["first lien", "p75_spread_bps"], 1)],
        "pooled_second_lien_median_spread_bps": round(pooled.loc["second lien", "median_spread_bps"], 1),
        "pooled_subordinated_median_spread_bps": round(pooled.loc["subordinated", "median_spread_bps"], 1),
        f"{latest}_first_lien_median_spread_bps": round(late.loc["first lien", "median_spread_bps"], 1),
        f"{latest}_second_lien_median_spread_bps": round(late.loc["second lien", "median_spread_bps"], 1),
        f"{latest}_subordinated_median_spread_bps": round(late.loc["subordinated", "median_spread_bps"], 1),
        "pooled_first_lien_fv_spread_coverage_pct": round(pooled.loc["first lien", "fv_coverage_pct_of_cell"], 1),
        "pooled_subordinated_fv_spread_coverage_pct": round(pooled.loc["subordinated", "fv_coverage_pct_of_cell"], 1),
        "units": "spreads in basis points over the stated reference rate; "
                 "coverage in percent of the fair value of the cell",
        "denominator_note": "fv_coverage_pct_of_cell = FV of positions with a "
                            "parsed spread / FV of that seniority bucket in that scope",
    }
    values_master |= v_a
    save_table(
        spread_tab.round(2), "m4_spread_distribution_by_seniority",
        "Fair-value weighted spread distribution by seniority",
        PERIOD, cov_a,
        note=("Quantiles are fair-value weighted over positions with a parsed "
              "spread. 'fv_coverage_pct_of_cell' is the share of that "
              "seniority bucket's fair value that carries a spread; the "
              "subordinated bucket is the weak cell and its median should be "
              "read as indicative only."),
        values=v_a)

    # Figure: pooled vs latest, p25-p75 range bars with median marker
    fig, axes = plt.subplots(1, 2, figsize=(7.6, 3.4), sharex=True)
    for ax, (scope, sub) in zip(axes, [
            ("Pooled 2018Q3-2026Q2", spread_tab[spread_tab.scope.str.startswith("pooled")]),
            (f"Latest quarter ({latest})", spread_tab[spread_tab.scope.str.startswith("latest")])]):
        sub = sub.set_index("seniority").loc[SENIORITY]
        y = np.arange(len(SENIORITY))
        for k, sen in enumerate(SENIORITY):
            r = sub.loc[sen]
            ax.barh(y[k], r.p75_spread_bps - r.p25_spread_bps, left=r.p25_spread_bps,
                    height=0.42, color=SEN_COLOR[sen], alpha=0.32)
            ax.plot([r.median_spread_bps], [y[k]], marker="D", ms=6,
                    color=SEN_COLOR[sen])
            ax.text(r.p75_spread_bps + 22, y[k], f"{r.median_spread_bps:,.0f}",
                    va="center", fontsize=7.2, color=SEN_COLOR[sen])
            ax.text(r.p25_spread_bps - 22, y[k],
                    f"{r.fv_coverage_pct_of_cell:.0f}% FV cov.",
                    va="center", ha="right", fontsize=6.4, color=SLATE)
        ax.set_yticks(y)
        ax.set_yticklabels([s.title() for s in SENIORITY])
        ax.set_title(scope, fontsize=8.5)
        ax.set_xlabel("Spread over reference rate (bps)")
        ax.set_xlim(0, 1250)
        ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.subplots_adjust(top=0.80)
    save_fig(fig, "m4_spread_distribution_by_seniority",
             "Spread by seniority: interquartile range and median",
             PERIOD, cov_a,
             subtitle=("Bars span the fair-value weighted p25-p75; diamond is the "
                       "FV-weighted median. Left label is the share of that "
                       "bucket's fair value carrying a parsed spread."),
             values=v_a)

    # ------------------------------------------------------------------
    # (b) Spread through time by seniority + first/second lien differential
    # ------------------------------------------------------------------
    ts = []
    for qk in quarters:
        sub = debt[debt.quarter == qk]
        rec = {"quarter": qk}
        for sen in SENIORITY:
            s = sub[sub.investment_type == sen]
            med = wq(s.spread_bps, s.fair_value, [0.5])[0]
            cov = fv_share(s, "spread_bps", s)
            # drop a cell rather than print a median resting on <40% of FV
            if cov < 40 or s.spread_bps.notna().sum() < 5:
                med = float("nan")
            rec[sen] = med
            rec[f"{sen}_fv_cov_pct"] = cov
            rec[f"{sen}_n_with_spread"] = int(s.spread_bps.notna().sum())
        rows_used = sub.spread_bps.notna().sum()
        rec["n_debt_with_spread"] = int(rows_used)
        ts.append(rec)
    ts = pd.DataFrame(ts)
    ts["fl_sl_diff_bps"] = ts["second lien"] - ts["first lien"]

    dropped_sub = ts.loc[ts["subordinated"].isna(), "quarter"].tolist()
    cov_b = Coverage(
        basis="investment-panel",
        rows_used=n_spread,
        rows_total=N_INV,
        note=("Quarterly FV-weighted median spread per seniority. A cell is "
              "dropped, not interpolated, when fewer than 5 positions carry a "
              f"spread or under 40% of the cell's fair value does; that drops "
              f"the subordinated series in {len(dropped_sub)} of "
              f"{len(quarters)} observed quarters. " + GAP_NOTE))

    d0 = ts.loc[ts.quarter == first_q, "fl_sl_diff_bps"].iloc[0]
    d1 = ts.loc[ts.quarter == latest, "fl_sl_diff_bps"].iloc[0]
    v_b = {
        "first_lien_median_spread_bps_2018Q3": round(ts.loc[ts.quarter == first_q, "first lien"].iloc[0], 1),
        "first_lien_median_spread_bps_2026Q2": round(ts.loc[ts.quarter == latest, "first lien"].iloc[0], 1),
        "second_lien_median_spread_bps_2018Q3": round(ts.loc[ts.quarter == first_q, "second lien"].iloc[0], 1),
        "second_lien_median_spread_bps_2026Q2": round(ts.loc[ts.quarter == latest, "second lien"].iloc[0], 1),
        "second_minus_first_lien_bps_2018Q3": round(d0, 1),
        "second_minus_first_lien_bps_2026Q2": round(d1, 1),
        "second_minus_first_lien_change_bps": round(d1 - d0, 1),
        "first_lien_peak_median_spread_bps": round(ts["first lien"].max(), 1),
        "first_lien_peak_quarter": ts.loc[ts["first lien"].idxmax(), "quarter"],
        "first_lien_trough_median_spread_bps": round(ts["first lien"].min(), 1),
        "first_lien_trough_quarter": ts.loc[ts["first lien"].idxmin(), "quarter"],
        "units": "basis points, fair-value weighted medians",
        "denominator_note": "each quarterly median is weighted by the fair "
                            "value of that seniority's spread-bearing positions "
                            "in that quarter",
    }
    values_master |= v_b

    # Reindex onto the calendar-continuous axis so the missing quarters
    # break the lines instead of being bridged.
    ts_ax = ts.set_index("quarter").reindex(QAXIS)
    fig, ax = plt.subplots(figsize=(7.4, 3.6))
    x = np.arange(len(QAXIS))
    mark_missing(ax, QAXIS, MISSING_Q)
    for sen in SENIORITY:
        ax.plot(x, ts_ax[sen], color=SEN_COLOR[sen], label=sen.title(),
                marker="o", ms=2.6)
    ax2 = ax.twinx()
    ax2.bar(x, ts_ax.fl_sl_diff_bps, color=SLATE, alpha=0.18, width=0.6,
            label="Second minus first lien (right)")
    ax2.set_ylabel("Differential (bps)", color=SLATE)
    ax2.grid(False)
    ax2.set_ylim(0, max(600, float(np.nanmax(ts.fl_sl_diff_bps)) * 1.6))
    ax.set_ylabel("FV-weighted median spread (bps)")
    quarter_ticks(ax, QAXIS, every=4)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, ncol=4, loc="lower center",
              bbox_to_anchor=(0.5, 1.02))
    fig.tight_layout()
    fig.subplots_adjust(top=0.80)
    save_fig(fig, "m4_spread_by_seniority_over_time",
             "Spread by seniority through time, and the second-to-first lien differential",
             PERIOD, cov_b,
             subtitle=("Lines are FV-weighted median spreads; bars are second "
                       "lien minus first lien. Breaks are dropped cells; "
                       "shaded columns are quarters missing from the panel. "
                       "Nothing is interpolated."),
             values=v_b)

    save_table(ts.round(2), "m4_spread_by_seniority_over_time",
               "Quarterly fair-value weighted median spread by seniority",
               PERIOD, cov_b,
               note=("One row per observed quarter: NaN entries are deliberate "
                     "drops (thin or poorly covered cells), and " + GAP_NOTE
                     + " They have no row in this table."),
               values=v_b)

    # ------------------------------------------------------------------
    # (c) All-in rate decomposition and implied base rate
    # ------------------------------------------------------------------
    fl = debt[debt.rate_class == "floating"].copy()
    both = fl.dropna(subset=["spread_bps", "all_in_rate_pct"]).copy()
    both["implied_base_pct"] = both.all_in_rate_pct - both.spread_bps / 100.0

    dec = []
    for qk in quarters:
        s = both[both.quarter == qk]
        w = s.fair_value
        dq = debt[debt.quarter == qk]
        dec.append({
            "quarter": qk,
            "fv_wtd_all_in_pct": float((s.all_in_rate_pct * w).sum() / w.sum()),
            "fv_wtd_spread_pct": float((s.spread_bps / 100.0 * w).sum() / w.sum()),
            "implied_base_pct": float((s.implied_base_pct * w).sum() / w.sum()),
            "n_positions": len(s),
            "fv_coverage_pct_of_debt_book": 100.0 * w.sum() / dq.fair_value.sum(),
        })
    dec = pd.DataFrame(dec)

    cov_c = Coverage(
        basis="investment-panel",
        rows_used=len(both),
        rows_total=N_INV,
        note=("Floating-rate debt-like positions where BOTH all_in_rate_pct "
              "and spread_bps are parsed. Implied base rate = all-in minus "
              "spread, fair-value weighted. No external rate series is used "
              "anywhere in this exhibit. " + GAP_NOTE))

    v_c = {
        "implied_base_rate_pct_2018Q3": round(dec.iloc[0].implied_base_pct, 2),
        "implied_base_rate_pct_trough": round(dec.implied_base_pct.min(), 2),
        "implied_base_rate_trough_quarter": dec.loc[dec.implied_base_pct.idxmin(), "quarter"],
        "implied_base_rate_pct_peak": round(dec.implied_base_pct.max(), 2),
        "implied_base_rate_peak_quarter": dec.loc[dec.implied_base_pct.idxmax(), "quarter"],
        "implied_base_rate_pct_2026Q2": round(dec.iloc[-1].implied_base_pct, 2),
        "fv_wtd_all_in_pct_2026Q2": round(dec.iloc[-1].fv_wtd_all_in_pct, 2),
        "fv_wtd_all_in_pct_trough": round(dec.fv_wtd_all_in_pct.min(), 2),
        "fv_wtd_all_in_trough_quarter": dec.loc[dec.fv_wtd_all_in_pct.idxmin(), "quarter"],
        "fv_wtd_all_in_pct_peak": round(dec.fv_wtd_all_in_pct.max(), 2),
        "fv_wtd_all_in_peak_quarter": dec.loc[dec.fv_wtd_all_in_pct.idxmax(), "quarter"],
        "fv_wtd_spread_pct_2026Q2": round(dec.iloc[-1].fv_wtd_spread_pct, 2),
        "min_quarterly_fv_coverage_pct_of_debt_book": round(dec.fv_coverage_pct_of_debt_book.min(), 1),
        "units": "percent per annum; coverage in percent of the quarter's debt-book fair value",
        "inference_label": ("INFERENCE, not measurement: the implied base rate "
                            "falls from " f"{dec.iloc[0].implied_base_pct:.2f}% in 2018Q3 to "
                            f"{dec.implied_base_pct.min():.2f}% in "
                            f"{dec.loc[dec.implied_base_pct.idxmin(), 'quarter']} and rises to "
                            f"{dec.implied_base_pct.max():.2f}% in "
                            f"{dec.loc[dec.implied_base_pct.idxmax(), 'quarter']}, a shape "
                            "consistent with the 2020 easing and the 2022-2023 "
                            "tightening cycle. It is derived purely from the "
                            "filings; no SOFR or LIBOR series is in this dataset."),
    }
    values_master |= v_c

    dec_ax = dec.set_index("quarter").reindex(QAXIS)
    fig, ax = plt.subplots(figsize=(7.4, 3.6))
    mark_missing(ax, QAXIS, MISSING_Q)
    base_v = dec_ax.implied_base_pct.to_numpy(float)
    spr_v = dec_ax.fv_wtd_spread_pct.to_numpy(float)
    # Draw the stack in contiguous segments; a single stackplot over the
    # full axis would fill straight across the missing quarters.
    for j, (a, b) in enumerate(runs(~np.isnan(base_v))):
        ax.stackplot(x[a:b], base_v[a:b], spr_v[a:b],
                     colors=[TEAL, NAVY], alpha=0.85,
                     labels=(["Implied base rate (all-in minus spread)",
                              "Contractual spread"] if j == 0 else ()))
    ax.plot(x, dec_ax.fv_wtd_all_in_pct, color=AMBER, lw=1.8,
            label="All-in rate (FV weighted)")
    ax.set_ylabel("Percent per annum")
    pct_axis(ax, decimals=0)
    quarter_ticks(ax, QAXIS, every=4)
    ax.legend(ncol=3, loc="lower center", bbox_to_anchor=(0.5, 1.02))
    fig.tight_layout()
    fig.subplots_adjust(top=0.80)
    save_fig(fig, "m4_all_in_rate_decomposition",
             "All-in yield decomposed into spread and implied base rate",
             PERIOD, cov_c,
             subtitle=("Floating-rate debt positions with both fields parsed. "
                       "The base rate is implied by subtraction, not sourced "
                       "from a rate series. Shaded columns are quarters "
                       "missing from the panel."),
             values=v_c)

    save_table(dec.round(3), "m4_all_in_rate_decomposition",
               "All-in rate, contractual spread and implied base rate by quarter",
               PERIOD, cov_c,
               note=("Implied base = FV-weighted (all_in_rate_pct - "
                     "spread_bps/100) on floating positions with both fields "
                     "present. Reading its path as the policy cycle is an "
                     "inference from the filings, not an external measurement."),
               values=v_c)

    # ------------------------------------------------------------------
    # (d) Maturity structure
    # ------------------------------------------------------------------
    n_no_mat = int(debt.yrs_to_mat.isna().sum())
    mat = debt.dropna(subset=["yrs_to_mat"]).copy()
    n_past_due = int((mat.yrs_to_mat < 0).sum())
    mat = mat[mat.yrs_to_mat >= 0]

    wam = []
    for qk in quarters:
        s = mat[mat.quarter == qk]
        dq = debt[debt.quarter == qk]
        w = s.fair_value
        wam.append({
            "quarter": qk,
            "wa_years_to_maturity": float((s.yrs_to_mat * w).sum() / w.sum()),
            "pct_fv_maturing_le_1y": 100.0 * w[s.yrs_to_mat <= 1].sum() / w.sum(),
            "pct_fv_maturing_le_3y": 100.0 * w[s.yrs_to_mat <= 3].sum() / w.sum(),
            "pct_fv_maturing_le_5y": 100.0 * w[s.yrs_to_mat <= 5].sum() / w.sum(),
            "n_positions": len(s),
            "fv_coverage_pct_of_debt_book": 100.0 * w.sum() / dq.fair_value.sum(),
        })
    wam = pd.DataFrame(wam)

    cov_d = Coverage(
        basis="investment-panel",
        rows_used=len(mat),
        rows_total=N_INV,
        note=(f"Debt-like positions with a parsed forward maturity_date: of "
              f"{N_DEBT:,} debt rows, {n_no_mat:,} carry no parsable "
              f"maturity_date and a further {n_past_due:,} carry a maturity "
              "before the period end and were excluded as stale or "
              "mis-parsed rather than reported as negative tenor. Years to "
              "maturity = (maturity_date - period_end)/365.25, fair-value "
              "weighted; every share in this exhibit is a share of the DATED "
              "debt book, not of the whole debt book. " + GAP_NOTE))

    lat = mat[mat.quarter == latest]
    latest_year = int(lat.period_end.dt.year.iloc[0])
    lat = lat.assign(mat_year=lat.maturity_date.dt.year)
    lat_bucket = lat.mat_year.clip(upper=latest_year + 6)
    ladder = (lat.assign(bucket=lat_bucket)
                 .groupby("bucket").fair_value.sum() / 1e9)
    ladder_lbl = [(f"{int(b)}" if b < latest_year + 6
                   else f"{latest_year + 6}+") for b in ladder.index]
    lat_fv = float(lat.fair_value.sum())

    v_d = {
        "wa_years_to_maturity_2018Q3": round(wam.iloc[0].wa_years_to_maturity, 2),
        "wa_years_to_maturity_2026Q2": round(wam.iloc[-1].wa_years_to_maturity, 2),
        "wa_years_to_maturity_max": round(wam.wa_years_to_maturity.max(), 2),
        "wa_years_to_maturity_max_quarter": wam.loc[wam.wa_years_to_maturity.idxmax(), "quarter"],
        "wa_years_to_maturity_min": round(wam.wa_years_to_maturity.min(), 2),
        "wa_years_to_maturity_min_quarter": wam.loc[wam.wa_years_to_maturity.idxmin(), "quarter"],
        f"pct_fv_maturing_within_1y_{latest}": round(wam.iloc[-1].pct_fv_maturing_le_1y, 1),
        f"pct_fv_maturing_within_3y_{latest}": round(wam.iloc[-1].pct_fv_maturing_le_3y, 1),
        f"pct_fv_maturing_within_5y_{latest}": round(wam.iloc[-1].pct_fv_maturing_le_5y, 1),
        f"debt_book_fv_usd_bn_{latest}": round(debt[debt.quarter == latest].fair_value.sum() / 1e9, 2),
        f"dated_debt_book_fv_usd_bn_{latest}": round(lat_fv / 1e9, 3),
        # 2 decimals on purpose: at 1 decimal this rounds to 100.0 and reads
        # as "the whole book is dated", which is not true.
        f"maturity_fv_coverage_pct_{latest}": round(wam.iloc[-1].fv_coverage_pct_of_debt_book, 2),
        "positions_excluded_no_maturity_date": n_no_mat,
        "positions_excluded_past_maturity": n_past_due,
        "units": "years; percent of the dated debt-book fair value in that quarter; USD bn",
        "denominator_note": ("maturity shares are computed on the fair value of "
                             "debt-like positions with a parsed, non-negative "
                             "tenor in that quarter, not on the whole book"),
    }
    values_master |= v_d

    fig, axes = plt.subplots(1, 2, figsize=(7.8, 3.4),
                             gridspec_kw={"width_ratios": [1.35, 1]})
    ax = axes[0]
    wam_ax = wam.set_index("quarter").reindex(QAXIS)
    mark_missing(ax, QAXIS, MISSING_Q)
    ax.plot(x, wam_ax.wa_years_to_maturity, color=NAVY, marker="o", ms=2.6)
    ax.set_ylabel("Weighted-average years to maturity")
    ax.set_title("Portfolio tenor by quarter", fontsize=8.5)
    quarter_ticks(ax, QAXIS, every=6)
    ax.set_ylim(0, max(6.5, wam.wa_years_to_maturity.max() * 1.15))
    ax = axes[1]
    ax.bar(range(len(ladder)), ladder.to_numpy(), color=TEAL, width=0.68)
    ax.set_xticks(range(len(ladder)))
    ax.set_xticklabels(ladder_lbl, rotation=45, ha="right")
    ax.set_ylabel("Fair value (USD bn)")
    ax.set_title(f"Maturity ladder, {latest}", fontsize=8.5)
    fig.tight_layout()
    fig.subplots_adjust(top=0.80)
    save_fig(fig, "m4_maturity_structure",
             "Maturity structure of the debt book",
             PERIOD, cov_d,
             subtitle=(f"Left: FV-weighted years to maturity per quarter; "
                       f"shaded columns are quarters missing from the panel. "
                       f"Right: {latest} fair value by maturity year on the "
                       f"dated debt book (${lat_fv/1e9:,.2f}bn), "
                       f"{latest_year + 6} and later grouped."),
             values=v_d)

    lad_tab = pd.DataFrame({
        "maturity_year": ladder_lbl,
        "fair_value_usd_bn": ladder.to_numpy(),
        "pct_of_dated_debt_fv": 100.0 * ladder.to_numpy() / ladder.sum(),
    })
    cov_d_lad = Coverage(
        basis="investment-panel",
        rows_used=len(lat),
        rows_total=N_INV,
        note=(f"{latest} debt-like positions with a parsed forward maturity "
              f"date only ({len(lat):,} positions, ${lat_fv/1e9:,.3f}bn, "
              f"{wam.iloc[-1].fv_coverage_pct_of_debt_book:.2f}% of that "
              f"quarter's ${debt[debt.quarter == latest].fair_value.sum()/1e9:,.3f}bn "
              "debt-book fair value)."))
    save_table(lad_tab.round(3), "m4_maturity_ladder_latest",
               f"Maturity ladder of the debt book, {latest}",
               f"{latest}", cov_d_lad,
               note=("Fair value by calendar maturity year; final bucket is "
                     "open-ended. Shares are of the dated debt book "
                     f"(${lat_fv/1e9:,.3f}bn), which is "
                     f"{wam.iloc[-1].fv_coverage_pct_of_debt_book:.2f}% of the "
                     f"{latest} debt book, not 100% of it."),
               values=v_d)

    save_table(wam.round(3), "m4_maturity_profile_by_quarter",
               "Weighted-average tenor and near-dated maturity shares by quarter",
               PERIOD, cov_d,
               note=("Shares are cumulative: 'le_3y' includes everything in "
                     "'le_1y'. Denominator is the dated debt-book fair value "
                     "of that quarter."),
               values=v_d)

    # ------------------------------------------------------------------
    # (e) Fixed vs floating
    # ------------------------------------------------------------------
    ff = (debt.pivot_table(index="quarter", columns="rate_class",
                           values="fair_value", aggfunc="sum")
              .reindex(quarters).fillna(0.0))
    for c in ("floating", "fixed", "undisclosed"):
        if c not in ff.columns:
            ff[c] = 0.0
    ff_pct = 100.0 * ff[["floating", "fixed", "undisclosed"]].div(ff.sum(axis=1), axis=0)

    cov_e = Coverage(
        basis="investment-panel",
        rows_used=N_DEBT,
        rows_total=N_INV,
        note=("All debt-like positions. 'floating' = a named reference rate "
              "other than 'fixed'; 'undisclosed' = reference_rate null, which "
              "is a parse gap and not an economic category. Shares are "
              "fair-value weighted and sum to 100% of the debt book. "
              + GAP_NOTE))

    v_e = {
        "floating_fv_share_pct_2018Q3": round(ff_pct.loc[first_q, "floating"], 1),
        "floating_fv_share_pct_2026Q2": round(ff_pct.loc[latest, "floating"], 1),
        "fixed_fv_share_pct_2018Q3": round(ff_pct.loc[first_q, "fixed"], 1),
        "fixed_fv_share_pct_2026Q2": round(ff_pct.loc[latest, "fixed"], 1),
        "undisclosed_fv_share_pct_2026Q2": round(ff_pct.loc[latest, "undisclosed"], 1),
        "floating_fv_share_pct_min": round(ff_pct.floating.min(), 1),
        "floating_fv_share_pct_min_quarter": ff_pct.floating.idxmin(),
        "floating_fv_share_pct_mean": round(ff_pct.floating.mean(), 1),
        "units": "percent of debt-book fair value",
        "denominator_note": "denominator is total fair value of debt-like "
                            "positions in that quarter",
    }
    values_master |= v_e

    ff_ax = ff_pct.reindex(QAXIS)
    fig, ax = plt.subplots(figsize=(7.4, 3.4))
    mark_missing(ax, QAXIS, MISSING_Q)
    flo = ff_ax.floating.to_numpy(float)
    for j, (a, b) in enumerate(runs(~np.isnan(flo))):
        ax.stackplot(x[a:b], flo[a:b],
                     ff_ax.fixed.to_numpy(float)[a:b],
                     ff_ax.undisclosed.to_numpy(float)[a:b],
                     colors=[NAVY, AMBER, LIGHT], alpha=0.9,
                     labels=(["Floating", "Fixed",
                              "Rate undisclosed (parse gap)"]
                             if j == 0 else ()))
    ax.set_ylim(0, 100)
    ax.set_xlim(-0.5, len(QAXIS) - 0.5)
    pct_axis(ax)
    ax.set_ylabel("Share of debt-book fair value")
    quarter_ticks(ax, QAXIS, every=4)
    ax.legend(ncol=3, loc="lower center", bbox_to_anchor=(0.5, 1.02))
    fig.tight_layout()
    fig.subplots_adjust(top=0.80)
    save_fig(fig, "m4_fixed_vs_floating",
             "Fixed versus floating share of the debt book",
             PERIOD, cov_e,
             subtitle=("Fair-value weighted. The pale band is missing "
                       "reference-rate data, shown rather than reallocated; "
                       "shaded columns are quarters missing from the panel."),
             values=v_e)

    # ------------------------------------------------------------------
    # (f) Terms and risk: spread buckets versus marks and accrual status
    # ------------------------------------------------------------------
    last8 = quarters[-8:]
    rk = debt[(debt.quarter.isin(last8)) & debt.spread_bps.notna()
              & (debt.cost > 0)].copy()
    # Spreads cluster hard on round levels (500, 525, 550, ...), so a 10-way
    # qcut collapses: we report the number of buckets actually produced rather
    # than mislabelling them as deciles.
    rk["bucket"] = pd.qcut(rk.spread_bps, 10, labels=False, duplicates="drop") + 1
    n_buckets = int(rk.bucket.nunique())

    risk = (rk.groupby("bucket")
              .apply(lambda g: pd.Series({
                  "positions": len(g),
                  "spread_bps_min": g.spread_bps.min(),
                  "spread_bps_max": g.spread_bps.max(),
                  "median_spread_bps": g.spread_bps.median(),
                  "fair_value_usd_mm": g.fair_value.sum() / 1e6,
                  "fv_over_cost": g.fair_value.sum() / g.cost.sum(),
                  "pct_marked_below_cost_by_fv":
                      100.0 * g.loc[g.fair_value < g.cost, "fair_value"].sum() / g.fair_value.sum(),
                  "non_accrual_positions": int(g.is_non_accrual.sum()),
              }), include_groups=False)
              .reset_index())
    risk.insert(1, "spread_range_bps",
                risk.apply(lambda r: f"{r.spread_bps_min:.0f}-{r.spread_bps_max:.0f}",
                           axis=1))

    # Structural data fact, found while building this exhibit: a position that
    # is on non-accrual almost never carries a parsed spread, because ARCC
    # replaces the rate footnote with the non-accrual marker.  The spread
    # buckets therefore CANNOT show a non-accrual gradient - every bucket is
    # mechanically 0%.  We report that rather than presenting a flat line as
    # if it were an economic result, and answer the terms-vs-risk question
    # with an accrual-status split instead.
    na_debt_all = debt[debt.is_non_accrual]
    na_spread_all = int(na_debt_all.spread_bps.notna().sum())
    rk8 = debt[debt.quarter.isin(last8) & (debt.cost > 0)]
    na8 = rk8[rk8.is_non_accrual]
    na8_with_spread = int(na8.spread_bps.notna().sum())

    acc_stat = (rk8.groupby("is_non_accrual")
                   .apply(lambda g: pd.Series({
                       "positions": len(g),
                       "fair_value_usd_mm": g.fair_value.sum() / 1e6,
                       "cost_usd_mm": g.cost.sum() / 1e6,
                       "fv_over_cost": g.fair_value.sum() / g.cost.sum(),
                       "positions_with_parsed_spread": int(g.spread_bps.notna().sum()),
                   }), include_groups=False)
                   .reset_index()
                   .rename(columns={"is_non_accrual": "non_accrual"}))

    cov_f = Coverage(
        basis="investment-panel",
        rows_used=len(rk),
        rows_total=N_INV,
        note=(f"Debt-like positions in the latest 8 quarters "
              f"({last8[0]}-{last8[-1]}) with a parsed spread and positive "
              "cost. Buckets are equal-count quantile cuts on spread_bps; ties "
              "at round spread levels collapse the requested 10 cuts into "
              f"{n_buckets} buckets, each holding roughly a tenth of positions "
              "and NOT a tenth of fair value. FV/cost inside each bucket is "
              "fair-value weighted. Fair-value sums are pooled over 8 quarter "
              "ends, so a position held throughout is counted 8 times. "
              "Non-accrual positions are absent here by "
              f"construction: only {na8_with_spread} of {len(na8):,} "
              "non-accrual debt positions in this window carry a parsed "
              "spread, so a bucket cut on spread cannot contain them."))

    lo, hi = risk.iloc[0], risk.iloc[-1]
    v_f = {
        "risk_window_quarters": f"{last8[0]}-{last8[-1]}",
        "tightest_bucket_spread_range_bps": [float(lo.spread_bps_min), float(lo.spread_bps_max)],
        "widest_bucket_spread_range_bps": [float(hi.spread_bps_min), float(hi.spread_bps_max)],
        "tightest_bucket_fv_over_cost": round(lo.fv_over_cost, 4),
        "widest_bucket_fv_over_cost": round(hi.fv_over_cost, 4),
        "fv_over_cost_gap_tightest_minus_widest_pp":
            round(100.0 * (lo.fv_over_cost - hi.fv_over_cost), 2),
        "n_spread_buckets": n_buckets,
        "worst_marked_bucket": int(risk.loc[risk.fv_over_cost.idxmin(), "bucket"]),
        "worst_marked_bucket_spread_range_bps": risk.loc[risk.fv_over_cost.idxmin(), "spread_range_bps"],
        "worst_marked_bucket_fv_over_cost": round(risk.fv_over_cost.min(), 4),
        "best_marked_bucket": int(risk.loc[risk.fv_over_cost.idxmax(), "bucket"]),
        "best_marked_bucket_fv_over_cost": round(risk.fv_over_cost.max(), 4),
        "spread_vs_fv_over_cost_rank_corr":
            round(float(risk.bucket.corr(risk.fv_over_cost, method="spearman")), 3),
        "non_accrual_debt_positions_last8q": len(na8),
        "non_accrual_debt_positions_last8q_with_parsed_spread": na8_with_spread,
        "non_accrual_debt_positions_window": len(na_debt_all),
        "non_accrual_debt_positions_window_with_parsed_spread": na_spread_all,
        "accruing_fv_over_cost_last8q":
            round(float(acc_stat.loc[~acc_stat.non_accrual, "fv_over_cost"].iloc[0]), 4),
        "non_accrual_fv_over_cost_last8q":
            round(float(acc_stat.loc[acc_stat.non_accrual, "fv_over_cost"].iloc[0]), 4),
        "non_accrual_fv_usd_mm_last8q":
            round(float(acc_stat.loc[acc_stat.non_accrual, "fair_value_usd_mm"].iloc[0]), 1),
        "units": "bps; FV/cost as a ratio (1.00 = marked at cost); counts in positions; USD mm",
        "denominator_note": ("each bucket's FV/cost = sum(fair_value)/sum(cost) "
                             "within that bucket, pooled over the 8 quarters"),
        "non_accrual_data_caveat": (
            f"Only {na_spread_all} of {len(na_debt_all):,} non-accrual debt "
            f"positions across 2018Q3-2026Q2 ({na8_with_spread} of {len(na8):,} "
            "in the latest 8 quarters) carry a parsed spread, because the "
            "filing replaces the rate footnote with the non-accrual marker. "
            "A non-accrual share computed inside spread buckets is therefore "
            "mechanically zero and is not reported as an economic result."),
        "causality_caveat": ("Descriptive association only. Spread is set at "
                            "origination and marks are set later, so this is "
                            "not evidence that spread causes impairment; "
                            "credit quality drives both."),
    }
    values_master |= v_f

    save_table(risk.round(4), "m4_spread_bucket_vs_marks",
               "Marks by spread bucket, latest 8 quarters",
               f"{last8[0]}-{last8[-1]}", cov_f,
               note=(f"Equal-count spread buckets ({n_buckets} of a requested "
                     "10; ties at round spread levels collapse the cuts). "
                     "FV/cost below 1.00 means the bucket is marked below "
                     "cost. Read as "
                     "association, not causation."),
               values=v_f)

    cov_f2 = Coverage(
        basis="investment-panel",
        rows_used=len(rk8),
        rows_total=N_INV,
        note=(f"All debt-like positions with positive cost in {last8[0]}-"
              f"{last8[-1]}, split by accrual status. This is the terms-vs-risk "
              "cut the spread buckets cannot deliver, because non-accrual "
              "positions lose their parsed spread in the filing."))
    v_f2 = {k: v_f[k] for k in (
        "risk_window_quarters", "accruing_fv_over_cost_last8q",
        "non_accrual_fv_over_cost_last8q", "non_accrual_fv_usd_mm_last8q",
        "non_accrual_debt_positions_last8q",
        "non_accrual_debt_positions_last8q_with_parsed_spread",
        "non_accrual_data_caveat")}
    v_f2["units"] = "FV/cost ratio; positions; USD mm"
    v_f2["denominator_note"] = ("FV/cost = sum(fair_value)/sum(cost) within each "
                                "accrual-status group, pooled over the 8 quarters")
    values_master |= {"accrual_split_" + k: v for k, v in v_f2.items()}
    save_table(acc_stat.round(4), "m4_accrual_status_vs_marks",
               "Marks by accrual status, latest 8 quarters",
               f"{last8[0]}-{last8[-1]}", cov_f2,
               note=("'positions_with_parsed_spread' is shown to document why "
                     "non-accrual positions cannot appear in the spread-bucket "
                     "table above."),
               values=v_f2)

    fig, axes = plt.subplots(1, 2, figsize=(7.8, 3.5),
                             gridspec_kw={"width_ratios": [1.7, 1]})
    ax = axes[0]
    xb = risk.bucket.to_numpy()
    ax.bar(xb, 100.0 * (risk.fv_over_cost - 1.0), color=NAVY, width=0.62)
    ax.axhline(0, color=SLATE, lw=0.8)
    ax.set_ylabel("FV/cost minus 1 (pp)")
    ax.set_xlabel(f"Spread bucket (1 = tightest, {n_buckets} = widest)")
    ax.set_xticks(xb)
    ax.set_title("Marks by spread bucket", fontsize=8.5)
    ax = axes[1]
    ratios = [float(acc_stat.loc[~acc_stat.non_accrual, "fv_over_cost"].iloc[0]),
              float(acc_stat.loc[acc_stat.non_accrual, "fv_over_cost"].iloc[0])]
    ax.bar([0, 1], ratios, color=[SAGE, RUST], width=0.55)
    ax.axhline(1.0, color=SLATE, lw=0.8, ls="--")
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["Accruing", "Non-accrual"])
    ax.set_ylabel("Fair value / cost")
    ax.set_ylim(0, 1.15)
    for k, r in enumerate(ratios):
        ax.text(k, r + 0.03, f"{r:.2f}x", ha="center", fontsize=7.5)
    ax.set_title("Marks by accrual status", fontsize=8.5)
    fig.tight_layout()
    fig.subplots_adjust(top=0.80)
    save_fig(fig, "m4_spread_bucket_vs_marks",
             "Do wider spreads carry worse marks?",
             f"{last8[0]}-{last8[-1]}", cov_f,
             subtitle=("Left: debt positions with a parsed spread, pooled over "
                       "the latest 8 quarters. Right: the same book split by "
                       "accrual status, which is where the mark differential "
                       "actually sits. Association only."),
             values=v_f)

    dump_exhibit_log("m4_deal_terms")

    # ---------------------------------------------- independent recompute
    # Recompute the 2026Q2 first-lien FV-weighted median spread from the raw
    # CSV, without load_panels or the wq helper, as a cross-check.
    raw = pd.read_csv(Path(__file__).resolve().parents[2]
                      / "output" / "panel" / "bdc_quarter_investment.csv",
                      low_memory=False)
    raw = raw[(raw.period_end == "2026-06-30") & (raw.investment_type == "first lien")]
    raw = raw.dropna(subset=["spread_bps"]).sort_values("spread_bps")
    cum = raw.fair_value.cumsum() / raw.fair_value.sum()
    check = float(raw.loc[cum >= 0.5, "spread_bps"].iloc[0])
    reported = v_b["first_lien_median_spread_bps_2026Q2"]
    print(f"[check] 2026Q2 first-lien FV-wtd median spread: "
          f"module={reported} bps, independent recompute={check} bps")
    assert abs(check - reported) <= 12.5, "median cross-check failed"

    print(f"[check] debt-like rows {N_DEBT:,} of {N_INV:,} in-window "
          f"investment rows ({100*N_DEBT/N_INV:.1f}%)")
    print("m4_deal_terms: 6 figures and 7 tables written to output/analysis")


if __name__ == "__main__":
    main()
