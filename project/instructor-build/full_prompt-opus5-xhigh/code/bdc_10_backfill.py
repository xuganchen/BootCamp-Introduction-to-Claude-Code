"""Stage 10 - assemble every filing of one filer into two full panels.

The pipeline (stages 01-08) parses exactly one filing and holds exactly one
filing in `data/interim/` and `output/`. That is deliberate and unchanged here:
this driver does not touch the stages, it *runs* them, once per filing, and
accumulates the panels that the verification gate promoted.

Why a driver and not a mode inside the stages
---------------------------------------------
Every stage reads what the previous stage wrote to a fixed path. Making the
stages multi-filing would mean threading a filing identity through all of them
and re-testing all 16 checks against a multi-row panel, which is how a
single-filing tie-out quietly becomes a cross-filing average. Instead each
filing is parsed in full isolation and gated on its own, exactly as before, and
only a filing whose gate came back green contributes a row.

Fail-closed, per filing
-----------------------
A filing that fails the gate, or that raises anywhere in stages 01-07,
contributes NOTHING to the assembled panels. It is recorded in the coverage
report with its failure reason. The panel therefore always states its own
coverage rather than silently omitting periods: `note/coverage.json` lists every
filing the filer has on EDGAR and what happened to it.

Cross-filing checks (C1-C5) run after assembly. They are checks that no single
filing can perform - most importantly C2, which ties each filing's comparative
column to the panel row built independently from the filing that reported that
period as its current column.

Usage
-----
    python3 code/bdc_10_backfill.py --ticker ARCC
    python3 code/bdc_10_backfill.py --ticker ARCC --from 2013-01-01
    python3 code/bdc_10_backfill.py --ticker ARCC --force        # ignore resume state
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bdc_01_resolve import filing_history, resolve_cik  # noqa: E402
from bdc_09_utils import INTERIM, NOTE, OUTPUT, ROOT, log  # noqa: E402

PANEL_DIR = OUTPUT / "panel"
QUARTER_PANEL = PANEL_DIR / "bdc_quarter.csv"
INVESTMENT_PANEL = PANEL_DIR / "bdc_quarter_investment.csv"
COVERAGE_JSON = NOTE / "coverage.json"

RUN_ALL = ROOT / "code" / "run_all.py"
PER_FILING_TIMEOUT = 900  # seconds


# ---------------------------------------------------------------------------
# running one filing
# ---------------------------------------------------------------------------


def parse_gate_report(stdout: str) -> tuple[dict[int, str], list[str]]:
    """Pull the per-check statuses and the FAIL detail lines out of the report."""
    statuses: dict[int, str] = {}
    fails: list[str] = []
    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].isdigit() and parts[1] in ("PASS", "FAIL", "WARN", "SKIP"):
            cid, status = int(parts[0]), parts[1]
            statuses[cid] = status
            if status == "FAIL":
                fails.append(line.strip())
    return statuses, fails


def failure_reason(stdout: str, stderr: str, statuses: dict[int, str]) -> str:
    """One line saying why this filing did not make it into the panel."""
    failed = sorted(c for c, s in statuses.items() if s == "FAIL")
    if failed:
        return f"gate FAIL on check(s) {failed}"
    # A stage raised before the gate ever ran. The last exception line is the
    # most specific thing we have.
    for blob in (stderr, stdout):
        lines = [ln.strip() for ln in blob.splitlines() if ln.strip()]
        for ln in reversed(lines):
            if any(
                k in ln
                for k in ("Error", "error:", "Exception", "SystemExit", "raise",
                          "ExtractionError", "BalanceSheetError", "SOIParseError",
                          "VocabularyError")
            ):
                return ln[:300]
    return "unknown failure (no gate table and no exception line)"


def run_one(ticker: str, row: dict) -> dict:
    """Run stages 01-08 for one filing in a subprocess. Never raises."""
    cmd = [
        sys.executable, str(RUN_ALL),
        "--ticker", ticker,
        "--period-end", row["period_end"],
        "--form", row["form_type"],
    ]
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=PER_FILING_TIMEOUT
        )
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        rc, out, err = 124, "", f"timed out after {PER_FILING_TIMEOUT}s"

    statuses, fails = parse_gate_report(out)
    result = {
        "form_type": row["form_type"],
        "period_end": row["period_end"],
        "filing_date": row["filing_date"],
        "accession": row["accession"],
        "primary_doc": row["primary_doc"],
        "returncode": rc,
        "ok": rc == 0,
        "elapsed_s": round(time.monotonic() - started, 1),
        "check_status": {str(k): v for k, v in sorted(statuses.items())},
        "n_pass": sum(1 for s in statuses.values() if s == "PASS"),
        "n_fail": sum(1 for s in statuses.values() if s == "FAIL"),
        "n_warn": sum(1 for s in statuses.values() if s == "WARN"),
        "n_skip": sum(1 for s in statuses.values() if s == "SKIP"),
        "fail_lines": fails[:6],
        "reason": "" if rc == 0 else failure_reason(out, err, statuses),
    }
    if rc == 0:
        # Provenance and the tie-out residual, straight from the promoted panel.
        try:
            q = pd.read_csv(OUTPUT / "bdc_quarter.csv")
            i = pd.read_csv(OUTPUT / "bdc_quarter_investment.csv")
            fv, rep = float(i["fair_value"].sum()), float(q["total_investments_fv"].iloc[0])
            result.update(
                {
                    "n_positions": len(i),
                    "n_borrowers": int(i["borrower"].nunique()),
                    "total_investments_fv": rep,
                    "soi_fair_value_sum": fv,
                    "tieout_abs_usd": fv - rep,
                    "tieout_pct": (100.0 * (fv - rep) / rep) if rep else None,
                    "source_scale": str(q["source_scale"].iloc[0]),
                }
            )
        except Exception as exc:  # promoted files unreadable: treat as a failure
            result["ok"] = False
            result["reason"] = f"promoted panels unreadable: {exc}"
    return result


def snapshot_promoted() -> tuple[pd.DataFrame, pd.DataFrame]:
    return (
        pd.read_csv(OUTPUT / "bdc_quarter.csv"),
        pd.read_csv(OUTPUT / "bdc_quarter_investment.csv"),
    )


# ---------------------------------------------------------------------------
# cross-filing checks: only possible once the panel exists
# ---------------------------------------------------------------------------


def cross_checks(q: pd.DataFrame, inv: pd.DataFrame) -> list[dict]:
    """C1-C5. Same fail-closed spirit as the per-filing gate."""
    out: list[dict] = []

    def add(cid, name, ok, msg, details=None, evaluated=True):
        # A check that evaluated nothing is not a pass. It is a stated gap, the
        # same way the per-filing gate reports SKIP with its condition.
        status = ("PASS" if ok else "FAIL") if evaluated else "SKIP"
        out.append({"id": cid, "name": name, "status": status,
                    "message": msg, "details": details or []})

    # C1 - the assembled quarter panel is still one row per BDC-quarter.
    dupes = q.duplicated(subset=["cik", "period_end"], keep=False)
    add(1, "assembled bdc_quarter unique on (cik, period_end)", not dupes.any(),
        f"{len(q)} row(s), {int(dupes.sum())} duplicated",
        q.loc[dupes, "period_end"].astype(str).tolist()[:10])

    # C2 - the chain check. Each filing reports a comparative column; when the
    # period it names was itself parsed from its own filing, the two independent
    # reads must agree. This is the cross-filing analogue of check 13.
    by_pe = {str(r["period_end"]): r for _, r in q.iterrows()}
    fields = ["total_assets", "total_liabilities", "net_assets", "total_investments_fv"]
    mismatches, compared, linked = [], 0, 0
    for _, r in q.iterrows():
        prior_pe = str(r.get("period_end_prior") or "")
        target = by_pe.get(prior_pe)
        if target is None:
            continue
        linked += 1
        for f in fields:
            a, b = r.get(f"{f}_prior"), target.get(f)
            if pd.isna(a) or pd.isna(b):
                continue
            compared += 1
            scale = max(abs(float(a)), abs(float(b)))
            if scale and abs(float(a) - float(b)) / scale > 0.001:
                mismatches.append(
                    f"{r['period_end']} reports {f}_prior={float(a):,.0f} for {prior_pe}, "
                    f"but the {prior_pe} filing parsed {f}={float(b):,.0f}"
                )
    add(2, "comparative column ties to the independently parsed prior filing",
        not mismatches,
        f"{compared} comparison(s) across {linked} linked filing pair(s), "
        f"{len(mismatches)} mismatch(es)"
        + ("" if compared else " - CONDITION NOT MET: no filing's comparative "
                               "period is itself in the panel, so nothing was compared"),
        mismatches[:10], evaluated=compared > 0)

    # C3 - every position-panel period exists in the quarter panel.
    q_pe = set(q["period_end"].astype(str))
    i_pe = set(inv["period_end"].astype(str))
    orphan = sorted(i_pe - q_pe)
    add(3, "every investment-panel period has a quarter-panel row", not orphan,
        f"{len(i_pe)} period(s) in the investment panel, {len(orphan)} orphaned", orphan[:10])

    # C4 - period-over-period plausibility on the assembled series. The
    # single-filing check 11 compares a filing against its own comparative
    # column; this compares consecutive filings, which catches a scale error
    # confined to one filing.
    # Adjacent ROWS are not adjacent PERIODS when the panel has gaps, and the
    # panel is expected to have gaps: an excluded filing leaves its period out
    # by design. Comparing across a two-year hole and calling the filer's real
    # growth implausible would be the check blaming the data for the coverage
    # report's contents. So the bound depends on the actual elapsed time:
    #   * consecutive quarters (<= 120 days apart): 60%, as before;
    #   * across a gap: a 10x band, which still catches the thing this check
    #     exists for - a scale error confined to one filing is 1000x, never 60%.
    qq = q.sort_values("period_end").reset_index(drop=True)
    pe = pd.to_datetime(qq["period_end"], errors="coerce")
    jumps, n_gap_pairs = [], 0
    for f in ("total_assets", "net_assets"):
        s = pd.to_numeric(qq[f], errors="coerce")
        for k in range(1, len(qq)):
            a, b = s.iloc[k - 1], s.iloc[k]
            if pd.isna(a) or pd.isna(b) or max(abs(a), abs(b)) == 0:
                continue
            gap_days = (pe.iloc[k] - pe.iloc[k - 1]).days
            rel = abs(b - a) / max(abs(a), abs(b))
            if gap_days <= 120:
                bad, bound = rel >= 0.60, "60% (consecutive quarters)"
            else:
                if f == "total_assets":
                    n_gap_pairs += 1
                ratio = max(a, b) / min(a, b) if min(a, b) > 0 else float("inf")
                bad, bound = ratio >= 10.0, f"10x (gap of {gap_days} days)"
            if bad:
                jumps.append(
                    f"{f}: {qq['period_end'].iloc[k-1]} {a:,.0f} -> "
                    f"{qq['period_end'].iloc[k]} {b:,.0f} ({rel*100:.1f}%, bound {bound})"
                )
    add(4, "consecutive periods plausible (60% adjacent, 10x across a gap)", not jumps,
        f"{len(qq)} period(s) in sequence, {n_gap_pairs} pair(s) span a coverage gap, "
        f"{len(jumps)} implausible jump(s)",
        jumps[:10], evaluated=len(qq) > 1)

    # C5 - units are consistent across the whole panel (plan_v0: "units
    # consistent across rows and tables"). Every money field is USD dollars, so
    # a filing parsed at the wrong scale shows up as an outlier in the ratio of
    # total assets to the number of positions... but the direct statement is
    # simply that source_scale was recorded and money is in dollars, which we
    # assert by requiring the assembled NAV per share to stay in a sane band.
    nav = pd.to_numeric(qq.get("nav_per_share"), errors="coerce").dropna()
    bad_nav = nav[(nav <= 0) | (nav > 1000)]
    add(5, "nav_per_share within [0, 1000] across every period", bad_nav.empty,
        f"{len(nav)} non-null nav_per_share value(s), {len(bad_nav)} outside the band",
        [f"{v}" for v in bad_nav.tolist()[:10]], evaluated=len(nav) > 0)
    return out


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Assemble every filing of one filer into two panels.")
    ap.add_argument("--ticker", default="ARCC")
    ap.add_argument("--from", dest="date_from", default=None, help="earliest period end (YYYY-MM-DD)")
    ap.add_argument("--to", dest="date_to", default=None, help="latest period end (YYYY-MM-DD)")
    ap.add_argument("--limit", type=int, default=None,
                    help="stop after N filings, in the chosen order")
    ap.add_argument("--order", choices=["newest", "oldest"], default="newest",
                    help="processing order. 'oldest' walks forward in time, which "
                         "makes an era's failures arrive as one contiguous block "
                         "instead of interleaved with the eras around it")
    ap.add_argument("--force", action="store_true", help="re-run filings already in the panel")
    args = ap.parse_args(argv)

    cik, title = resolve_cik(args.ticker)
    history, meta = filing_history(cik)
    log.info("%s (CIK %d): %d periodic filings on EDGAR across %d submissions page(s)",
             title, cik, len(history), meta["n_pages"])

    targets = history
    if args.date_from:
        targets = [r for r in targets if r["period_end"] >= args.date_from]
    if args.date_to:
        targets = [r for r in targets if r["period_end"] <= args.date_to]
    # filing_history returns newest first; reverse before limiting so --limit
    # takes the first N in the order actually requested.
    if args.order == "oldest":
        targets = list(reversed(targets))
    if args.limit:
        targets = targets[: args.limit]
    if targets:
        log.info("targeting %d filing(s), %s first: %s -> %s",
                 len(targets), args.order, targets[0]["period_end"], targets[-1]["period_end"])

    PANEL_DIR.mkdir(parents=True, exist_ok=True)

    # Resume: keep whatever already assembled cleanly unless --force.
    quarters: list[pd.DataFrame] = []
    investments: list[pd.DataFrame] = []
    done: set[str] = set()
    if not args.force and QUARTER_PANEL.exists() and INVESTMENT_PANEL.exists():
        q0, i0 = pd.read_csv(QUARTER_PANEL), pd.read_csv(INVESTMENT_PANEL)
        if len(q0):
            quarters.append(q0)
            investments.append(i0)
            done = set(q0["accession"].astype(str))
            log.info("resuming: %d filing(s) already assembled", len(done))

    # Per-filing records survive a resumed run. Without this, a run that skips
    # everything already assembled would write a coverage report listing no
    # filings at all - and a coverage report that under-reports its own contents
    # is worse than none, because a missing row reads as "never attempted".
    prior_records: dict[str, dict] = {}
    if COVERAGE_JSON.exists():
        try:
            for r in json.loads(COVERAGE_JSON.read_text()).get("filings", []):
                prior_records[str(r.get("accession"))] = r
        except (json.JSONDecodeError, KeyError):
            pass

    records: list[dict] = []
    for n, row in enumerate(targets, 1):
        if row["accession"] in done and not args.force:
            log.info("[%d/%d] %s %s already assembled, skipping",
                     n, len(targets), row["form_type"], row["period_end"])
            continue
        log.info("[%d/%d] %s %s (%s)", n, len(targets),
                 row["form_type"], row["period_end"], row["accession"])
        res = run_one(args.ticker, row)
        records.append(res)
        if res["ok"]:
            q, i = snapshot_promoted()
            quarters.append(q)
            investments.append(i)
            log.info("    OK  %d positions, tie-out %.6f%%, %d pass / %d warn / %d skip (%.0fs)",
                     res["n_positions"], res["tieout_pct"] or 0.0,
                     res["n_pass"], res["n_warn"], res["n_skip"], res["elapsed_s"])
        else:
            log.warning("    EXCLUDED  %s", res["reason"])

        # Write through after every filing so a long run is restartable.
        if quarters:
            pd.concat(quarters, ignore_index=True).drop_duplicates(
                subset=["cik", "period_end"], keep="last"
            ).sort_values("period_end").to_csv(QUARTER_PANEL, index=False)
            pd.concat(investments, ignore_index=True).drop_duplicates(
                subset=["position_id"], keep="last"
            ).sort_values(["period_end", "borrower"]).to_csv(INVESTMENT_PANEL, index=False)

    if not quarters:
        log.error("no filing passed the gate; no panel written")
        return 1

    q = pd.read_csv(QUARTER_PANEL)
    inv = pd.read_csv(INVESTMENT_PANEL)
    for df, path in ((q, QUARTER_PANEL), (inv, INVESTMENT_PANEL)):
        try:
            df.to_parquet(path.with_suffix(".parquet"), index=False)
        except Exception as exc:  # pragma: no cover
            log.info("parquet twin for %s skipped (%s)", path.name, exc)

    cc = cross_checks(q, inv)
    log.info("=" * 72)
    for c in cc:
        log.info("C%-2d %-6s %-62s %s", c["id"], c["status"], c["name"], c["message"])
        for d in c["details"]:
            log.info("        -> %s", d)

    # Merge this run's records over anything carried forward from a prior run.
    by_acc = dict(prior_records)
    for r in records:
        by_acc[str(r["accession"])] = r
    all_records = [by_acc[str(t["accession"])] for t in targets if str(t["accession"]) in by_acc]
    attempted = {str(t["accession"]) for t in targets}
    coverage = {
        "ticker": args.ticker.upper(),
        "cik": cik,
        "bdc_name": title,
        "fiscal_year_end": meta["fiscal_year_end"],
        "n_filings_on_edgar": len(history),
        "n_targeted": len(targets),
        "n_attempted_this_run": len(records),
        "n_with_a_record": len(all_records),
        "n_in_panel": len(q),
        "n_positions_in_panel": len(inv),
        "period_end_min": str(q["period_end"].min()),
        "period_end_max": str(q["period_end"].max()),
        "cross_checks": cc,
        "cross_checks_passed": all(c["status"] != "FAIL" for c in cc),
        "cross_checks_skipped": [c["id"] for c in cc if c["status"] == "SKIP"],
        "filings": all_records,
        "not_attempted": [
            {k: r[k] for k in ("form_type", "period_end", "accession")}
            for r in targets if str(r["accession"]) not in by_acc
        ],
    }
    NOTE.mkdir(parents=True, exist_ok=True)
    COVERAGE_JSON.write_text(json.dumps(coverage, indent=2, default=str))
    log.info("panel: %d quarter row(s), %d position(s), %s -> %s",
             len(q), len(inv), coverage["period_end_min"], coverage["period_end_max"])
    log.info("coverage written to %s", COVERAGE_JSON)
    return 0 if coverage["cross_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
