"""Stage 11 - turn note/coverage.json into the human-readable note/coverage.md.

Kept separate from the backfill driver so the note can be regenerated from a
saved coverage.json without re-running 88 filings.

The grouping rule matters more than the formatting: exclusions are grouped by
*reason family*, not by period. One representation difference normally explains
a contiguous run of filings, and that run is the test set for the extension that
fixes it. A list sorted by date hides exactly that structure.

Usage
-----
    python3 code/bdc_11_coverage.py                       # note/coverage.json -> note/coverage.md
    python3 code/bdc_11_coverage.py --baseline old.json   # also report what changed
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bdc_09_utils import NOTE, log  # noqa: E402

COVERAGE_JSON = NOTE / "coverage.json"
COVERAGE_MD = NOTE / "coverage.md"

# Ordered: the first pattern that matches a reason names the family. Ordering
# matters because a gate FAIL line also contains the word "check".
REASON_FAMILIES: list[tuple[str, str]] = [
    ("no SOI header row found", "SOI header row not recognised"),
    ("no principal_amount", "debt rows with no principal_amount"),
    ("no fair_value", "position rows with no fair_value"),
    ("no balance-sheet header row", "balance-sheet header dates not found"),
    ("balance sheet presents", "balance sheet has more than two dated columns"),
    ("expected exactly 1 balance-sheet", "more than one table classified as the balance sheet"),
    ("no balance sheet found", "no balance sheet located"),
    ("no SOI fragment dated", "no SOI fragment carries the period end"),
    ("SOI fragments with no parseable", "an SOI fragment has no parseable as-of date"),
    ("no Schedule of Investments", "no SOI located"),
    ("disagree on scale", "SOI fragments disagree on scale"),
    ("unmapped investment_type_raw", "instrument type outside the controlled vocabulary"),
    ("duplicate header", "duplicate SOI header label"),
    ("gate FAIL on check(s)", "verification gate failed"),
    ("timed out", "timed out"),
]


def family_of(reason: str) -> str:
    for needle, label in REASON_FAMILIES:
        if needle in reason:
            return label
    return "other: " + reason.split(":")[0][:60]


def _span(periods: list[str]) -> str:
    return f"{min(periods)} to {max(periods)}" if periods else "-"


def build(cov: dict, baseline: dict | None = None) -> str:
    filings = cov["filings"]
    passed = [f for f in filings if f["ok"]]
    failed = [f for f in filings if not f["ok"]]

    L: list[str] = []
    A = L.append

    A(f"# Coverage - {cov['bdc_name']} ({cov['ticker']}), CIK {cov['cik']}")
    A("")
    A("Produced by `code/bdc_10_backfill.py`, rendered by `code/bdc_11_coverage.py`.")
    A("Every filing below was parsed in isolation by the full single-filing")
    A("pipeline and gated by the 16 checks. **A filing that failed contributes")
    A("nothing to the panel** - no partial rows, no interpolation, no values")
    A("borrowed from another filing's comparative column.")
    A("")

    A("## Summary")
    A("")
    A("| | Count |")
    A("|---|---|")
    A(f"| 10-K / 10-Q on EDGAR | {cov['n_filings_on_edgar']} |")
    A(f"| Targeted this run | {cov['n_targeted']} |")
    A(f"| **In the panel (gate green)** | **{len(passed)}** |")
    A(f"| Excluded (gate failed or stage raised) | {len(failed)} |")
    A(f"| Positions in the investment panel | {cov['n_positions_in_panel']:,} |")
    A(f"| Panel span | {cov['period_end_min']} to {cov['period_end_max']} |")
    A("")
    pct = 100.0 * len(passed) / len(filings) if filings else 0.0
    A(f"Coverage: **{len(passed)} of {len(filings)} filings ({pct:.0f}%)**.")
    A("")

    if baseline:
        b_pass = {f["accession"] for f in baseline["filings"] if f["ok"]}
        n_pass = {f["accession"] for f in passed}
        gained, lost = sorted(n_pass - b_pass), sorted(b_pass - n_pass)
        A(f"Against the baseline run: **{len(b_pass)} -> {len(n_pass)}** filings in the panel, "
          f"{len(gained)} gained, {len(lost)} lost.")
        if lost:
            A("")
            A("**Regression - filings that used to pass and no longer do:**")
            for f in filings:
                if f["accession"] in set(lost):
                    A(f"- {f['form_type']} {f['period_end']}: {f['reason']}")
        A("")

    A("## Cross-filing checks")
    A("")
    A("Checks no single filing can perform. A check that evaluated nothing")
    A("reports SKIP, never PASS.")
    A("")
    A("| # | Status | Check | Detail |")
    A("|---|---|---|---|")
    for c in cov["cross_checks"]:
        A(f"| C{c['id']} | {c['status']} | {c['name']} | {c['message']} |")
    A("")
    for c in cov["cross_checks"]:
        if c["details"]:
            A(f"C{c['id']} details:")
            A("")
            for d in c["details"]:
                A(f"- {d}")
            A("")

    A("## Coverage by year")
    A("")
    by_year_total: Counter = Counter()
    by_year_pass: Counter = Counter()
    for f in filings:
        y = f["period_end"][:4]
        by_year_total[y] += 1
        if f["ok"]:
            by_year_pass[y] += 1
    A("| Year | Filings | In panel | |")
    A("|---|---|---|---|")
    for y in sorted(by_year_total, reverse=True):
        t, p = by_year_total[y], by_year_pass[y]
        bar = "#" * p + "." * (t - p)
        A(f"| {y} | {t} | {p} | `{bar}` |")
    A("")

    A("## Field completeness inside the panel")
    A("")
    A("Row coverage is not field coverage. A filing can pass every check and")
    A("still leave a nullable field empty, because the filing does not print it")
    A("in a form this parser reads. Nullable fields are listed here so the gap")
    A("is visible rather than discovered later in analysis.")
    A("")
    try:
        import pandas as pd  # local import: the note can be built without pandas

        qp = Path("output/panel/bdc_quarter.csv")
        ip = Path("output/panel/bdc_quarter_investment.csv")
        if qp.exists() and ip.exists():
            q, i = pd.read_csv(qp), pd.read_csv(ip)
            A("| Panel | Field | Non-null | Of | % |")
            A("|---|---|---|---|---|")
            for name, df, cols in (
                ("quarter", q, ["nav_per_share", "shares_outstanding",
                                "total_debt_outstanding", "total_investments_fv",
                                "net_assets"]),
                ("investment", i, ["principal_amount", "cost", "maturity_date",
                                   "reference_rate", "spread_bps", "all_in_rate_pct",
                                   "industry", "pct_of_net_assets"]),
            ):
                for c in cols:
                    if c not in df.columns:
                        continue
                    nn = int(df[c].notna().sum())
                    A(f"| {name} | `{c}` | {nn:,} | {len(df):,} | {100.0*nn/len(df):.0f}% |")
            A("")
    except Exception as exc:  # pragma: no cover
        A(f"(field completeness unavailable: {exc})")
        A("")

    A("## Exclusions, grouped by reason")
    A("")
    A("One representation difference normally explains a contiguous block of")
    A("filings. The block is the test set for the extension that fixes it.")
    A("")
    fam: dict[str, list[dict]] = defaultdict(list)
    for f in failed:
        fam[family_of(f["reason"])].append(f)
    A("| Failure family | Filings | Period span | Stage |")
    A("|---|---|---|---|")
    for label, rows in sorted(fam.items(), key=lambda kv: -len(kv[1])):
        periods = [r["period_end"] for r in rows]
        stage = "gate" if "gate" in label else "parse"
        A(f"| {label} | {len(rows)} | {_span(periods)} | {stage} |")
    A("")
    for label, rows in sorted(fam.items(), key=lambda kv: -len(kv[1])):
        A(f"### {label} ({len(rows)} filings)")
        A("")
        A(f"Periods: {_span([r['period_end'] for r in rows])}")
        A("")
        A("Representative message:")
        A("")
        A("```")
        A(rows[0]["reason"][:400])
        A("```")
        A("")

    A("## Every filing")
    A("")
    A("| Form | Period end | Accession | Status | Positions | Tie-out | Note |")
    A("|---|---|---|---|---|---|---|")
    for f in sorted(filings, key=lambda r: r["period_end"], reverse=True):
        if f["ok"]:
            warn = f" ({f['n_warn']}W/{f['n_skip']}S)" if (f["n_warn"] or f["n_skip"]) else ""
            A(f"| {f['form_type']} | {f['period_end']} | {f['accession']} | IN PANEL{warn} | "
              f"{f.get('n_positions', 0):,} | {f.get('tieout_pct', 0.0):.6f}% | |")
        else:
            A(f"| {f['form_type']} | {f['period_end']} | {f['accession']} | excluded | - | - | "
              f"{family_of(f['reason'])} |")
    A("")

    A("## What this panel is not")
    A("")
    A("- Not a complete history. Excluded periods are absent, not estimated.")
    A("- The `_prior` columns are comparative reads from a filing, not filed")
    A("  observations of that period. They are never used to fill a gap.")
    A("- Positions are current-period only for each filing; no comparative SOI")
    A("  is parsed (plan section 8).")
    A("- Cross-check C2 only evaluates where a filing's comparative period is")
    A("  itself in the panel, so a panel with gaps leaves it partly unevaluated.")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coverage", type=Path, default=COVERAGE_JSON)
    ap.add_argument("--baseline", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=COVERAGE_MD)
    args = ap.parse_args(argv)

    cov = json.loads(args.coverage.read_text())
    baseline = json.loads(args.baseline.read_text()) if args.baseline else None
    args.out.write_text(build(cov, baseline))
    log.info("wrote %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
