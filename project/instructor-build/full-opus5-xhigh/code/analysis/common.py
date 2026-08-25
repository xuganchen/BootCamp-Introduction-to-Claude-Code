"""Shared scaffolding for the ARCC private-credit portfolio report.

Every analysis module imports from here so that figures, tables and the
provenance metadata that accompanies them are produced the same way.

Design rules enforced here (they are report requirements, not preferences):

1. One analysis window.  ``WINDOW_START`` / ``WINDOW_END`` define the
   2018-2026 window.  ``load_panels()`` is the only entry point and it
   always returns the window-filtered panels.
2. Every figure and every table carries (a) the period it covers and
   (b) the share of panel rows it was computed on.  ``save_fig`` and
   ``save_table`` require a ``period`` string and a ``Coverage`` object;
   they refuse to write output without them.
3. Every saved artifact also writes a JSON sidecar into
   ``output/analysis/facts`` so the report text can quote exact numbers
   instead of re-deriving them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd

# ---------------------------------------------------------------- paths

ROOT = Path(__file__).resolve().parents[2]
PANEL_DIR = ROOT / "output" / "panel"
OUT_DIR = ROOT / "output" / "analysis"
FIG_DIR = OUT_DIR / "figures"
TAB_DIR = OUT_DIR / "tables"
FACT_DIR = OUT_DIR / "facts"
for _d in (FIG_DIR, TAB_DIR, FACT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------- window

WINDOW_START = "2018-01-01"
WINDOW_END = "2026-12-31"
WINDOW_LABEL = "2018Q3-2026Q2"

# ---------------------------------------------------------------- style
# Muted institutional palette, close to the reference private-market
# research decks: one dominant navy, one accent teal, warm tones for
# risk/stress series, grey for anything contextual.

NAVY = "#1F3B63"
TEAL = "#2E8B8B"
AMBER = "#C8842B"
RUST = "#A6462F"
SLATE = "#7A8794"
SAGE = "#6E8B5A"
PLUM = "#6B4C7A"
LIGHT = "#C9D2DC"

SERIES = [NAVY, TEAL, AMBER, RUST, SAGE, PLUM, SLATE, LIGHT]

plt.rcParams.update({
    "figure.figsize": (7.2, 3.9),
    "figure.dpi": 200,
    "savefig.dpi": 200,
    "savefig.bbox": "tight",
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
    "font.size": 8.5,
    "axes.titlesize": 9.5,
    "axes.titleweight": "bold",
    "axes.labelsize": 8.5,
    "axes.edgecolor": "#BFC7D0",
    "axes.linewidth": 0.7,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "axes.axisbelow": True,
    "grid.color": "#E3E8ED",
    "grid.linewidth": 0.6,
    "legend.frameon": False,
    "legend.fontsize": 7.5,
    "xtick.labelsize": 7.5,
    "ytick.labelsize": 7.5,
    "xtick.color": "#42505E",
    "ytick.color": "#42505E",
    "lines.linewidth": 1.6,
})

# --------------------------------------------------------- data loading


@dataclass
class Coverage:
    """How much of the panel an exhibit was computed on.

    ``rows_used`` / ``rows_total`` are row counts in the *window* panel
    that the exhibit draws from; ``basis`` names that panel and any
    filter applied.  ``share_pct`` is what gets printed under the
    exhibit.
    """

    basis: str
    rows_used: int
    rows_total: int
    note: str = ""

    @property
    def share_pct(self) -> float:
        return 100.0 * self.rows_used / self.rows_total if self.rows_total else 0.0

    def sentence(self) -> str:
        s = (f"Computed on {self.rows_used:,} of {self.rows_total:,} "
             f"{self.basis} rows ({self.share_pct:.1f}% of the window panel).")
        return f"{s} {self.note}".strip()


def load_panels(window: bool = True):
    """Return (quarter, investment) panels, window-filtered by default."""
    q = pd.read_csv(PANEL_DIR / "bdc_quarter.csv")
    i = pd.read_csv(PANEL_DIR / "bdc_quarter_investment.csv", low_memory=False)
    for df in (q, i):
        df["period_end"] = pd.to_datetime(df["period_end"])
    q["filing_date"] = pd.to_datetime(q["filing_date"])
    i["maturity_date"] = pd.to_datetime(i["maturity_date"], errors="coerce")
    if window:
        lo, hi = pd.Timestamp(WINDOW_START), pd.Timestamp(WINDOW_END)
        q = q[(q.period_end >= lo) & (q.period_end <= hi)].copy()
        i = i[(i.period_end >= lo) & (i.period_end <= hi)].copy()
    q = q.sort_values("period_end").reset_index(drop=True)
    i = i.sort_values(["period_end", "borrower"]).reset_index(drop=True)
    i["is_non_accrual"] = i["is_non_accrual"].astype(str).str.lower().eq("true")
    i["quarter"] = i["period_end"].dt.to_period("Q").astype(str)
    q["quarter"] = q["period_end"].dt.to_period("Q").astype(str)
    i["debt_like"] = i["investment_type"].isin(
        ["first lien", "second lien", "subordinated"])
    i["industry_norm"] = i["industry"].map(normalize_industry)
    return q, i


_AMP = re.compile(r"\s*&\s*")
_WS = re.compile(r"\s+")


def normalize_industry(x) -> str:
    """Collapse the '&' / 'and' and casing variants EDGAR filings mix.

    ARCC's Schedule of Investments switched industry taxonomies and
    punctuation over the window ("Software & Services" vs "Software and
    Services"), so raw ``industry`` over-counts distinct sectors.
    """
    if not isinstance(x, str) or not x.strip():
        return "Unclassified"
    s = _AMP.sub(" and ", x.strip())
    s = _WS.sub(" ", s)
    s = s.replace("Health Care", "Healthcare")
    return s.title().replace(" And ", " and ").replace(" Of ", " of ")


# ------------------------------------------------------------- exhibits

_EXHIBIT_LOG: list[dict] = []


def _sidecar(kind: str, slug: str, title: str, period: str,
             cov: Coverage, source: str, extra: dict | None = None) -> None:
    rec = {
        "kind": kind,
        "slug": slug,
        "title": title,
        "period": period,
        "coverage": asdict(cov) | {"share_pct": round(cov.share_pct, 2),
                                   "sentence": cov.sentence()},
        "source": source,
    }
    if extra:
        rec["values"] = extra
    (FACT_DIR / f"{kind}_{slug}.json").write_text(json.dumps(rec, indent=2, default=str))
    _EXHIBIT_LOG.append(rec)


def _esc(text: str) -> str:
    """Escape '$' so matplotlib draws dollar amounts literally."""
    return text.replace("$", r"\$")


SOURCE_LINE = ("Source: author's calculations on the ARCC BDC panel built from "
               "SEC EDGAR 10-K/10-Q filings.")


def save_fig(fig, slug: str, title: str, period: str, cov: Coverage,
             subtitle: str = "", source: str = SOURCE_LINE,
             values: dict | None = None) -> Path:
    """Write a figure with its period and coverage stamped into the image."""
    if not period or cov is None:
        raise ValueError("save_fig requires an explicit period and Coverage")
    # A pair of unescaped '$' in a title or a coverage note (dollar amounts
    # are everywhere in this report) is read by matplotlib as mathtext and
    # the text between them is silently reflowed, e.g. "$11.2bn to $29.3bn"
    # rendering as "11.2bnto29.3bn". Escape before drawing.
    head = title if not subtitle else f"{title}\n{subtitle}"
    head = _esc(head)
    fig.suptitle(head, x=0.0, ha="left", fontsize=9.5, fontweight="bold", y=1.02)
    foot = _esc(f"Period covered: {period}. {cov.sentence()}\n{source}")
    fig.text(0.0, -0.10, foot, ha="left", va="top", fontsize=6.4, color="#5A6774",
             wrap=True)
    path = FIG_DIR / f"{slug}.png"
    fig.savefig(path)
    plt.close(fig)
    _sidecar("fig", slug, title, period, cov, source, values)
    return path


def save_table(df: pd.DataFrame, slug: str, title: str, period: str,
               cov: Coverage, note: str = "", source: str = SOURCE_LINE,
               values: dict | None = None) -> Path:
    """Write a table as CSV plus a markdown fragment carrying its stamps."""
    if not period or cov is None:
        raise ValueError("save_table requires an explicit period and Coverage")
    csv_path = TAB_DIR / f"{slug}.csv"
    df.to_csv(csv_path, index=False)
    md = df.to_markdown(index=False, floatfmt=",.2f")
    lines = [f"**{title}**", "",
             f"*Period covered: {period}. {cov.sentence()}*", "", md, ""]
    if note:
        lines += [f"*Note: {note}*", ""]
    lines += [f"*{source}*", ""]
    (TAB_DIR / f"{slug}.md").write_text("\n".join(lines))
    _sidecar("tab", slug, title, period, cov, source,
             values or {"rows": len(df)})
    return csv_path


def pct_axis(ax, decimals: int = 0):
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=100, decimals=decimals))


def usd_axis(ax, unit: str = "bn", decimals: int = 0):
    div = {"bn": 1e9, "mm": 1e6, "k": 1e3}[unit]
    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v, _: f"${v/div:,.{decimals}f}{unit}"))


def quarter_ticks(ax, quarters, every: int = 4):
    """Label a quarter axis sparsely so it stays readable."""
    idx = list(range(len(quarters)))
    ax.set_xticks(idx[::every])
    ax.set_xticklabels([quarters[i] for i in idx[::every]], rotation=0)


def dump_exhibit_log(module: str) -> None:
    (FACT_DIR / f"_log_{module}.json").write_text(
        json.dumps(_EXHIBIT_LOG, indent=2, default=str))
