"""bdc_08_checks.py - the verification gate.

Implements checks 1-16 of plan_v1.md section 4 against the two panels.

Design rules this module follows, deliberately:

* It never imports, reads, or trusts anything the parser produced other than
  the two panels themselves. Every expected value it needs is derived here,
  from the filing and from the XBRL, by code that lives in this file.
* A check that cannot be evaluated is reported as SKIP or WARN with an explicit
  reason and is printed in the table. It is never silently dropped.
* The gate is fail-closed: FAIL on any check, or an unhandled error, means
  nothing is written to output/ and the process exits non-zero.

Two entry points:

    from bdc_08_checks import run_all_checks, build_context
    results = run_all_checks(quarter_df, investment_df, context)

    python3 code/bdc_08_checks.py            # CLI, promotes on green
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd

try:  # allow both `python3 code/bdc_08_checks.py` and `import code.bdc_08_checks`
    from bdc_09_utils import INTERIM, NOTE, OUTPUT, ROOT, log, parse_date
except ImportError:  # pragma: no cover - import shim
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from bdc_09_utils import INTERIM, NOTE, OUTPUT, ROOT, log, parse_date


# ---------------------------------------------------------------------------
# Result plumbing
# ---------------------------------------------------------------------------

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"
SKIP = "SKIP"


@dataclass
class CheckResult:
    """One check outcome. `details` carries the numeric diff for failures."""

    id: int
    name: str
    status: str
    message: str = ""
    details: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """WARN and SKIP do not block promotion; only FAIL does."""
        return self.status != FAIL


def _res(cid, name, ok, msg="", details=None, warn=False):
    status = WARN if (ok and warn) else (PASS if ok else FAIL)
    return CheckResult(cid, name, status, msg, list(details or []))


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------

CONTROLLED_INVESTMENT_TYPES = {
    "first lien",
    "second lien",
    "subordinated",
    "equity",
    "preferred",
    "other",
}

# Types for which plan section 3.2 requires a principal amount.
DEBT_INVESTMENT_TYPES = {"first lien", "second lien", "subordinated"}


def _isnull(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _num(v) -> float | None:
    if _isnull(v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _as_date(v) -> date | None:
    if _isnull(v):
        return None
    if isinstance(v, date) and not isinstance(v, pd.Timestamp):
        return v
    if isinstance(v, pd.Timestamp):
        return v.date()
    return parse_date(str(v))


def _rel_diff(a: float, b: float) -> float:
    """Relative difference against the larger magnitude. 0.0 when both are 0."""
    scale = max(abs(a), abs(b))
    return 0.0 if scale == 0 else abs(a - b) / scale


def _close(a: float, b: float, rel_tol: float, abs_floor: float = 0.0) -> bool:
    """|a-b| within max(rel_tol * max(|a|,|b|), abs_floor)."""
    return abs(a - b) <= max(rel_tol * max(abs(a), abs(b)), abs_floor)


def _fmt(v) -> str:
    if v is None:
        return "None"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)


def _diff_line(label: str, actual, expected, tol_note: str = "") -> str:
    a, e = _num(actual), _num(expected)
    piece = f"{label}: actual={_fmt(a)} expected={_fmt(e)}"
    if a is not None and e is not None:
        piece += f" abs_diff={_fmt(abs(a - e))} rel_diff={_rel_diff(a, e) * 100:.6f}%"
    if tol_note:
        piece += f" (tol {tol_note})"
    return piece


# ---------------------------------------------------------------------------
# Independent ground truth: inline XBRL read straight out of the filing.
#
# This is NOT the parser's balance-sheet extraction. It reads the ix: facts
# that the filer tagged, keyed by XBRL context, which is a different physical
# path through the document than reading the rendered table cells. That is
# exactly what makes it usable as an external reference for checks 5 and 15.
# ---------------------------------------------------------------------------

IX_NS = "http://www.xbrl.org/2013/inlineXBRL"
XBRLI_NS = "http://www.xbrl.org/2003/instance"
XBRLDI_NS = "http://xbrl.org/2006/xbrldi"

# Tags read out of the filing. Each is the undimensioned (entity-level) fact.
IX_TAGS = (
    "us-gaap:Assets",
    "us-gaap:Liabilities",
    "us-gaap:StockholdersEquity",
    "us-gaap:LiabilitiesAndStockholdersEquity",
    "us-gaap:NetAssetValuePerShare",
    "us-gaap:CommonStockSharesOutstanding",
    "us-gaap:InvestmentOwnedAtFairValue",
    "us-gaap:InvestmentOwnedAtCost",
    "us-gaap:LongTermDebt",
)

_XBRL_CACHE = NOTE / "gate_xbrl_ground_truth.json"


def _ix_number(el) -> float | None:
    """Value of an ix:nonFraction element, with scale and sign applied."""
    import re

    txt = "".join(el.itertext()).replace("\xa0", " ")
    txt = txt.replace(",", "").replace("$", "").strip()
    txt = re.sub(r"[()]", "", txt)
    if txt in ("", "-", "—", "–"):
        return None
    try:
        val = float(txt)
    except ValueError:
        return None
    scale = el.get("scale")
    if scale not in (None, ""):
        val *= 10 ** int(scale)
    if el.get("sign") == "-":
        val = -val
    return val


def _read_inline_xbrl(doc_path: Path) -> dict[str, list[dict]]:
    """Undimensioned ix facts for IX_TAGS, in document order, keyed by tag."""
    from lxml import etree

    contexts: dict[str, dict] = {}
    parser_kw = dict(huge_tree=True, recover=True, resolve_entities=False)

    ctx_iter = etree.iterparse(
        str(doc_path), events=("end",), tag=f"{{{XBRLI_NS}}}context", **parser_kw
    )
    for _, el in ctx_iter:
        period = el.find(f"{{{XBRLI_NS}}}period")
        instant = period.find(f"{{{XBRLI_NS}}}instant") if period is not None else None
        dims = [m.get("dimension") for m in el.iter(f"{{{XBRLDI_NS}}}explicitMember")]
        contexts[el.get("id")] = {
            "instant": instant.text if instant is not None else None,
            "ndims": len(dims),
        }
        el.clear()

    wanted = set(IX_TAGS)
    out: dict[str, list[dict]] = {t: [] for t in IX_TAGS}
    fact_iter = etree.iterparse(
        str(doc_path), events=("end",), tag=f"{{{IX_NS}}}nonFraction", **parser_kw
    )
    for _, el in fact_iter:
        name = el.get("name")
        if name in wanted:
            ctx = contexts.get(el.get("contextRef"), {})
            # Dimensioned facts are segment / member breakdowns, not the
            # entity-level statement lines. Keep only the undimensioned ones.
            if ctx.get("ndims", 1) == 0 and ctx.get("instant"):
                out[name].append({"instant": ctx["instant"], "val": _ix_number(el)})
        el.clear()
    return out


@lru_cache(maxsize=4)
def inline_xbrl_facts(doc_path_str: str) -> dict[str, list[dict]]:
    """Cached wrapper. Persists to note/ so repeated gate runs stay fast."""
    doc_path = Path(doc_path_str)
    if _XBRL_CACHE.exists():
        try:
            blob = json.loads(_XBRL_CACHE.read_text())
            if blob.get("doc_path") == doc_path_str:
                return blob["facts"]
        except (json.JSONDecodeError, KeyError):
            pass
    facts = _read_inline_xbrl(doc_path)
    NOTE.mkdir(parents=True, exist_ok=True)
    _XBRL_CACHE.write_text(json.dumps({"doc_path": doc_path_str, "facts": facts}, indent=1))
    return facts


def ix_first(facts: dict[str, list[dict]], tag: str, on: date | str) -> float | None:
    """First undimensioned fact for `tag` at instant `on`, in document order.

    Document order matters: the balance sheet is the first statement in the
    filing, so its lines are the first occurrence of each tag. Later
    occurrences of the same tag are notes and schedule rows.
    """
    key = on.isoformat() if isinstance(on, date) else str(on)
    for f in facts.get(tag, []):
        if f["instant"] == key and f["val"] is not None:
            return float(f["val"])
    return None


def bs_column_dates_from_filing(doc_path: Path) -> list[date]:
    """The dated columns of the balance sheet, derived from XBRL contexts.

    us-gaap:Assets is reported once per balance-sheet column and, at the
    entity level, nowhere else in the document. The set of instants carrying
    an undimensioned Assets fact therefore is the set of dated columns.
    """
    facts = inline_xbrl_facts(str(doc_path))
    seen: list[date] = []
    for f in facts.get("us-gaap:Assets", []):
        d = parse_date(f["instant"])
        if d and d not in seen:
            seen.append(d)
    return seen


# ---------------------------------------------------------------------------
# Independent ground truth: XBRL companyfacts
# ---------------------------------------------------------------------------


def companyfacts_value(facts_json: dict, tag: str, on: date, taxonomy: str = "us-gaap"):
    """(value, provenance) for `tag` at `on`, or (None, reason)."""
    # companyfacts keys tags without the taxonomy prefix; the inline XBRL uses
    # "us-gaap:Assets". Accept either spelling.
    if ":" in tag:
        taxonomy, tag = tag.split(":", 1)
    body = (facts_json.get("facts", {}).get(taxonomy, {}) or {}).get(tag)
    if not body:
        return None, f"companyfacts has no {taxonomy}:{tag}"
    key = on.isoformat()
    best = None
    for unit, rows in body.get("units", {}).items():
        for r in rows:
            if r.get("end") != key or "start" in r:
                continue
            # Prefer the latest-filed observation for the date.
            if best is None or (r.get("filed", "") > best[0].get("filed", "")):
                best = (r, unit)
    if best is None:
        return None, f"companyfacts has no {tag} instant at {key}"
    row, unit = best
    return float(row["val"]), f"{taxonomy}:{tag} [{unit}] end={key} accn={row.get('accn')}"


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------


def build_context(
    target_filing: dict | None = None,
    manifest: dict | None = None,
    extra: dict | None = None,
) -> dict:
    """Build the check context from the shared infrastructure artifacts."""
    if target_filing is None:
        p = INTERIM / "target_filing.json"
        target_filing = json.loads(p.read_text()) if p.exists() else {}
    if manifest is None:
        p = INTERIM / "manifest.json"
        manifest = json.loads(p.read_text()) if p.exists() else {}

    ctx: dict[str, Any] = {
        "cik": target_filing.get("cik") or manifest.get("cik"),
        "form_type": target_filing.get("form_type") or manifest.get("form_type"),
        "period_end": parse_date(
            str(target_filing.get("period_end") or manifest.get("period_end") or "")
        ),
        "fiscal_year_end": str(
            target_filing.get("fiscal_year_end") or manifest.get("fiscal_year_end") or ""
        ),
        "doc_path": manifest.get("doc_path"),
        "facts_path": manifest.get("facts_path"),
        # Optional, supplied by the pipeline when it knows them. Left absent
        # here on purpose: the gate derives its own values instead.
        "bs_column_dates": None,
        "reported_total_cost": None,
        "unmapped_investment_types": None,
    }
    if extra:
        ctx.update(extra)
    return ctx


# ---------------------------------------------------------------------------
# The 16 checks
# ---------------------------------------------------------------------------

# Never-null per plan section 3.1 / 3.2.
QUARTER_REQUIRED = [
    "bdc_name", "cik", "period_end", "filing_date", "form_type", "accession",
    "source_scale", "source_url",
    "total_investments_fv", "total_assets", "total_liabilities", "net_assets",
    "period_end_prior", "period_end_prior_kind",
    "total_investments_fv_prior", "total_assets_prior",
    "total_liabilities_prior", "net_assets_prior",
]
QUARTER_NULLABLE = [
    "ticker", "nav_per_share", "shares_outstanding", "total_debt_outstanding",
    "nav_per_share_prior", "shares_outstanding_prior", "total_debt_outstanding_prior",
]
INVESTMENT_REQUIRED = [
    "cik", "bdc_name", "period_end", "accession", "position_id", "borrower",
    "investment_type", "investment_type_raw", "fair_value", "is_non_accrual",
    "source_scale", "source_url",
]


def _one_row(quarter_df: pd.DataFrame) -> pd.Series:
    return quarter_df.iloc[0]


def check_01_quarter_unique(q: pd.DataFrame, inv, ctx) -> CheckResult:
    name = "bdc_quarter unique on (cik, period_end)"
    if q.empty:
        return _res(1, name, False, "bdc_quarter is empty")
    missing = [c for c in ("cik", "period_end") if c not in q.columns]
    if missing:
        return _res(1, name, False, f"missing key column(s): {missing}")
    dupes = q.duplicated(subset=["cik", "period_end"], keep=False)
    if dupes.any():
        rows = q.loc[dupes, ["cik", "period_end"]].astype(str).agg(" / ".join, axis=1).tolist()
        return _res(1, name, False, f"{int(dupes.sum())} duplicated key rows",
                    [f"duplicate key: {r}" for r in rows[:10]])
    return _res(1, name, True, f"{len(q)} row(s), keys unique")


def check_02_never_null(q: pd.DataFrame, inv: pd.DataFrame, ctx) -> CheckResult:
    name = "never-null fields populated"
    details: list[str] = []
    for col in QUARTER_REQUIRED:
        if col not in q.columns:
            details.append(f"bdc_quarter missing column {col}")
        else:
            n = int(q[col].map(_isnull).sum())
            if n:
                details.append(f"bdc_quarter.{col}: {n} null of {len(q)}")
    for col in INVESTMENT_REQUIRED:
        if col not in inv.columns:
            details.append(f"investment missing column {col}")
        else:
            n = int(inv[col].map(_isnull).sum())
            if n:
                details.append(f"investment.{col}: {n} null of {len(inv)}")
    # Relaxed rule from plan 3.2: principal is required for debt-type rows only.
    if {"investment_type", "principal_amount"} <= set(inv.columns):
        debt = inv[inv["investment_type"].astype(str).str.strip().str.lower().isin(DEBT_INVESTMENT_TYPES)]
        missing = debt["principal_amount"].map(_isnull)
        # Unit-denominated debt (CLO subordinated notes) states its size as a
        # Shares/Units count and carries no principal. The gate reads that from
        # the panel itself rather than taking the parser's word for it; a row
        # with neither field is still a violation.
        if "shares_units" in debt.columns:
            missing &= ~pd.to_numeric(debt["shares_units"], errors="coerce").gt(0)
        n = int(missing.sum())
        if n:
            details.append(
                f"investment.principal_amount: {n} null of {len(debt)} debt-type rows "
                f"(nullable for equity/preferred/other only)"
            )
    if details:
        return _res(2, name, False, f"{len(details)} null-rule violation(s)", details)
    return _res(2, name, True, "all never-null fields populated")


def check_03_rows_exceed_borrowers(q, inv: pd.DataFrame, ctx) -> CheckResult:
    name = "investment rows > unique borrowers"
    if "borrower" not in inv.columns:
        return _res(3, name, False, "investment panel has no borrower column")
    rows, uniq = len(inv), int(inv["borrower"].nunique(dropna=False))
    ok = rows > uniq
    return _res(3, name, ok,
                f"rows={rows} unique_borrowers={uniq}",
                [] if ok else [f"rows ({rows}) <= unique borrowers ({uniq}): "
                               f"one row per borrower means tranches were collapsed or "
                               f"only subtotal rows survived"])


def check_04_investment_type_vocab(q, inv: pd.DataFrame, ctx) -> CheckResult:
    name = "investment_type in controlled vocabulary"
    details: list[str] = []
    if "investment_type" not in inv.columns:
        return _res(4, name, False, "investment panel has no investment_type column")
    vals = inv["investment_type"].dropna().astype(str).str.strip().str.lower()
    bad = sorted(set(vals) - CONTROLLED_INVESTMENT_TYPES)
    if bad:
        details.append(f"unmapped investment_type value(s): {bad}")
    # Guard the other direction: raw strings the normalizer could not map must
    # be reported by the pipeline, not silently bucketed into "other".
    unmapped = ctx.get("unmapped_investment_types")
    if unmapped:
        details.append(
            f"{len(unmapped)} raw investment_type string(s) fell through to 'other' "
            f"without an explicit mapping: {sorted(unmapped)[:10]}"
        )
    if details:
        return _res(4, name, False, "controlled vocabulary violated", details)
    return _res(4, name, True, f"{len(set(vals))} distinct type(s), all mapped")


def _bs_dates(ctx) -> tuple[list[date] | None, str]:
    if ctx.get("bs_column_dates"):
        return [d for d in (_as_date(x) for x in ctx["bs_column_dates"]) if d], "context"
    doc = ctx.get("doc_path")
    if doc and Path(doc).exists():
        dates = bs_column_dates_from_filing(Path(doc))
        if dates:
            return dates, "inline XBRL (derived by the gate)"
        # No dates because the document carries no inline XBRL at all. Inline
        # XBRL became mandatory only for fiscal periods ending on or after
        # 2019-06-15 for large filers, so every earlier filing lands here.
        # "The gate has no data" is a SKIP with a stated condition, not a
        # finding that the balance sheet has the wrong number of columns -
        # reporting it as FAIL would blame the filing for the gate's blind spot.
        return None, "the filing carries no inline XBRL facts (pre-inline-XBRL filing)"
    return None, "unavailable"


def check_05_two_dated_columns(q, inv, ctx) -> CheckResult:
    name = "balance sheet has exactly two parseable dated columns"
    dates, src = _bs_dates(ctx)
    if dates is None:
        return CheckResult(5, name, SKIP, f"CONDITION NOT MET: {src}; cannot evaluate")
    if len(dates) != 2:
        return _res(5, name, False,
                    f"{len(dates)} dated column(s) found via {src}, expected exactly 2",
                    [f"dates: {[d.isoformat() for d in dates]}",
                     "plan 3.1: more than two dated columns must fail, not guess"])
    return _res(5, name, True,
                f"2 dated columns via {src}: {[d.isoformat() for d in dates]}")


def check_06_current_column_equals_period(q: pd.DataFrame, inv, ctx) -> CheckResult:
    name = "current column header date == periodOfReport"
    if q.empty:
        return _res(6, name, False, "bdc_quarter is empty")
    row = _one_row(q)
    panel_pe = _as_date(row.get("period_end"))
    filing_pe = _as_date(ctx.get("period_end"))
    details = []
    ok = True
    if filing_pe is None:
        return CheckResult(6, name, SKIP, "ctx['period_end'] (periodOfReport) unknown")
    if panel_pe != filing_pe:
        ok = False
        details.append(f"panel period_end={panel_pe} != periodOfReport={filing_pe}")
    dates, src = _bs_dates(ctx)
    if dates:
        if filing_pe not in dates:
            ok = False
            details.append(
                f"periodOfReport {filing_pe} is not among the balance-sheet column "
                f"dates {[d.isoformat() for d in dates]} ({src})"
            )
        prior = _as_date(row.get("period_end_prior"))
        if prior is not None and prior == filing_pe:
            ok = False
            details.append("period_end_prior equals periodOfReport: columns were swapped")
    return _res(6, name, ok,
                f"period_end={panel_pe} periodOfReport={filing_pe}" if ok else "mismatch",
                details)


def check_07_prior_gap(q: pd.DataFrame, inv, ctx) -> CheckResult:
    name = "period_end_prior < period_end, gap in [80, 380] days"
    if q.empty:
        return _res(7, name, False, "bdc_quarter is empty")
    row = _one_row(q)
    pe, pp = _as_date(row.get("period_end")), _as_date(row.get("period_end_prior"))
    if pe is None or pp is None:
        return _res(7, name, False, f"unparseable dates: period_end={pe} period_end_prior={pp}")
    gap = (pe - pp).days
    if pp >= pe:
        return _res(7, name, False, f"period_end_prior {pp} is not before period_end {pe}",
                    [f"gap={gap} days"])
    ok = 80 <= gap <= 380
    return _res(7, name, ok, f"gap={gap} days ({pp} -> {pe})",
                [] if ok else [f"gap={gap} days outside [80, 380]"])


def check_08_prior_kind(q: pd.DataFrame, inv, ctx) -> CheckResult:
    name = "period_end_prior_kind consistent with fiscal year end"
    if q.empty:
        return _res(8, name, False, "bdc_quarter is empty")
    row = _one_row(q)
    kind = row.get("period_end_prior_kind")
    pp = _as_date(row.get("period_end_prior"))
    fye = str(ctx.get("fiscal_year_end") or "").strip()
    if _isnull(kind):
        return _res(8, name, False, "period_end_prior_kind is null")
    kind = str(kind).strip()
    if kind not in ("prior_fiscal_year_end", "prior_quarter_end"):
        return _res(8, name, False, f"unknown period_end_prior_kind {kind!r}",
                    ["allowed: prior_fiscal_year_end, prior_quarter_end"])
    if pp is None:
        return _res(8, name, False, "period_end_prior unparseable, cannot classify")
    if len(fye) == 4 and fye.isdigit():
        is_fye_date = f"{pp.month:02d}{pp.day:02d}" == fye
        if kind == "prior_fiscal_year_end" and not is_fye_date:
            return _res(8, name, False,
                        f"labelled prior_fiscal_year_end but {pp} is not fiscal year end {fye}",
                        [f"period_end_prior MMDD={pp.month:02d}{pp.day:02d} vs fiscal_year_end={fye}"])
        if kind == "prior_quarter_end" and is_fye_date:
            return _res(8, name, False,
                        f"labelled prior_quarter_end but {pp} IS the fiscal year end {fye}",
                        ["the label contradicts the date; the column map is suspect"])
    if kind == "prior_quarter_end":
        # Plan check 8: allowed, but unusual for a 10-Q. Warn, do not block.
        return _res(8, name, True,
                    f"period_end_prior_kind=prior_quarter_end for a "
                    f"{ctx.get('form_type')} - non-standard comparative, logged as unusual",
                    ["UNUSUAL: most 10-Q filers present the prior fiscal year end"],
                    warn=True)
    return _res(8, name, True, f"prior_fiscal_year_end at {pp}, fiscal_year_end={fye or 'unknown'}")


def _accounting_pair(row, suffix: str):
    return (
        _num(row.get(f"total_assets{suffix}")),
        _num(row.get(f"total_liabilities{suffix}")),
        _num(row.get(f"net_assets{suffix}")),
    )


def check_09_balance_sheet_identity(q: pd.DataFrame, inv, ctx) -> CheckResult:
    name = "liabilities + net assets == total assets (both columns)"
    if q.empty:
        return _res(9, name, False, "bdc_quarter is empty")
    row = _one_row(q)
    details, ok = [], True
    for label, suffix in (("current", ""), ("prior", "_prior")):
        ta, tl, na = _accounting_pair(row, suffix)
        if None in (ta, tl, na):
            ok = False
            details.append(f"{label}: missing value(s) total_assets={ta} "
                           f"total_liabilities={tl} net_assets={na}")
            continue
        tol = max(0.0005 * abs(ta), 1.0)
        if abs((tl + na) - ta) > tol:
            ok = False
            details.append(_diff_line(f"{label} liabilities+net_assets vs total_assets",
                                      tl + na, ta, f"max(0.05%, 1 USD) = {_fmt(tol)}"))
    return _res(9, name, ok, "identity holds on both columns" if ok else "identity broken",
                details)


def check_10_nav_per_share(q: pd.DataFrame, inv, ctx) -> CheckResult:
    name = "nav_per_share * shares_outstanding == net_assets (both columns)"
    if q.empty:
        return _res(10, name, False, "bdc_quarter is empty")
    row = _one_row(q)
    details, ok, skipped = [], True, []
    for label, suffix in (("current", ""), ("prior", "_prior")):
        nav = _num(row.get(f"nav_per_share{suffix}"))
        sh = _num(row.get(f"shares_outstanding{suffix}"))
        na = _num(row.get(f"net_assets{suffix}"))
        if nav is None or sh is None:
            # Both fields are nullable per plan 3.1; report, do not fail.
            skipped.append(f"{label}: nav_per_share={nav} shares_outstanding={sh} (nullable, not evaluated)")
            continue
        if na is None:
            ok = False
            details.append(f"{label}: net_assets is null")
            continue
        if not _close(nav * sh, na, 0.005):
            ok = False
            details.append(_diff_line(f"{label} nav*shares vs net_assets", nav * sh, na, "0.5%"))
    if not ok:
        return _res(10, name, False, "per-share identity broken", details + skipped)
    if skipped and len(skipped) == 2:
        return CheckResult(10, name, SKIP, "nav_per_share / shares_outstanding null on both columns",
                           skipped)
    return _res(10, name, True, "per-share identity holds" + (" (partially skipped)" if skipped else ""),
                skipped, warn=bool(skipped))


def check_11_columns_comparable(q: pd.DataFrame, inv, ctx) -> CheckResult:
    name = "current vs prior column differ by < 60%"
    if q.empty:
        return _res(11, name, False, "bdc_quarter is empty")
    row = _one_row(q)
    details, ok = [], True
    for base in ("total_assets", "net_assets"):
        cur, prior = _num(row.get(base)), _num(row.get(f"{base}_prior"))
        if cur is None or prior is None:
            ok = False
            details.append(f"{base}: missing value(s) current={cur} prior={prior}")
            continue
        rel = _rel_diff(cur, prior)
        if rel >= 0.60:
            ok = False
            details.append(f"{base}: current={_fmt(cur)} prior={_fmt(prior)} "
                           f"rel_diff={rel * 100:.4f}% (bound 60%)")
    return _res(11, name, ok, "columns are the same order of magnitude" if ok
                else "columns are implausibly different", details)


def check_12_columns_not_identical(q: pd.DataFrame, inv, ctx) -> CheckResult:
    name = "total_assets != total_assets_prior"
    if q.empty:
        return _res(12, name, False, "bdc_quarter is empty")
    row = _one_row(q)
    cur, prior = _num(row.get("total_assets")), _num(row.get("total_assets_prior"))
    if cur is None or prior is None:
        return _res(12, name, False, f"missing value(s) current={cur} prior={prior}")
    if cur == prior:
        return _res(12, name, False, "the two columns carry identical total_assets",
                    [f"total_assets == total_assets_prior == {_fmt(cur)}",
                     "almost always means the same column was read twice"])
    return _res(12, name, True, f"current={_fmt(cur)} prior={_fmt(prior)}")


def check_13_soi_tieout(q: pd.DataFrame, inv: pd.DataFrame, ctx) -> CheckResult:
    name = "sum(investment.fair_value) == total_investments_fv (current column)"
    if q.empty:
        return _res(13, name, False, "bdc_quarter is empty")
    if "fair_value" not in inv.columns:
        return _res(13, name, False, "investment panel has no fair_value column")
    row = _one_row(q)
    reported = _num(row.get("total_investments_fv"))
    if reported is None:
        return _res(13, name, False, "total_investments_fv is null")
    soi = float(pd.to_numeric(inv["fair_value"], errors="coerce").fillna(0).sum())
    ok = _close(soi, reported, 0.001)
    details = [] if ok else [
        _diff_line("SOI sum vs balance sheet", soi, reported, "0.1%"),
        f"rows summed: {len(inv)}",
    ]
    if not ok:
        prior = _num(row.get("total_investments_fv_prior"))
        if prior is not None and _close(soi, prior, 0.001):
            details.append("NOTE: the SOI sum ties to the PRIOR column instead. "
                           "The current/prior column map is inverted.")
    return _res(13, name, ok,
                f"soi_sum={_fmt(soi)} reported={_fmt(reported)} "
                f"rel_diff={_rel_diff(soi, reported) * 100:.6f}%", details)


def _reported_total_cost(ctx) -> tuple[float | None, str]:
    if ctx.get("reported_total_cost") is not None:
        return float(ctx["reported_total_cost"]), "supplied in context"
    doc, pe = ctx.get("doc_path"), _as_date(ctx.get("period_end"))
    if doc and pe and Path(doc).exists():
        facts = inline_xbrl_facts(str(doc))
        v = ix_first(facts, "us-gaap:InvestmentOwnedAtCost", pe)
        if v is not None:
            return v, f"inline XBRL us-gaap:InvestmentOwnedAtCost @ {pe} (first, undimensioned)"
    return None, "the filing reports no total cost figure this gate can locate"


def check_14_cost_tieout(q: pd.DataFrame, inv: pd.DataFrame, ctx) -> CheckResult:
    name = "sum(investment.cost) == reported total cost (conditional)"
    reported, provenance = _reported_total_cost(ctx)
    if reported is None:
        # Plan check 14 is conditional on the filing reporting a total cost.
        # The condition is stated, not silently swallowed.
        return CheckResult(14, name, SKIP,
                           f"CONDITION NOT MET: {provenance}. Check 14 applies only when "
                           f"the filing reports a total cost figure.")
    if "cost" not in inv.columns:
        return _res(14, name, False,
                    f"CONDITION MET ({provenance}) but investment panel has no cost column")
    cost_col = pd.to_numeric(inv["cost"], errors="coerce")
    n_null = int(cost_col.isna().sum())
    soi = float(cost_col.fillna(0).sum())
    ok = _close(soi, reported, 0.001)
    details = [f"condition met: {provenance}"]
    if not ok:
        details.append(_diff_line("SOI cost sum vs reported total cost", soi, reported, "0.1%"))
        if n_null:
            details.append(f"{n_null} of {len(inv)} rows have a null cost and were summed as 0")
    return _res(14, name, ok,
                f"cost_sum={_fmt(soi)} reported={_fmt(reported)} "
                f"rel_diff={_rel_diff(soi, reported) * 100:.6f}%", details)


XBRL_CROSSCHECK = [
    ("total_assets", "us-gaap:Assets"),
    ("total_liabilities", "us-gaap:Liabilities"),
    ("net_assets", "us-gaap:StockholdersEquity"),
]


def check_15_xbrl_crosscheck(q: pd.DataFrame, inv, ctx) -> CheckResult:
    name = "both columns tie to XBRL facts for their own dates"
    if q.empty:
        return _res(15, name, False, "bdc_quarter is empty")
    row = _one_row(q)

    facts_json = None
    fp = ctx.get("facts_path")
    if fp and Path(fp).exists():
        facts_json = json.loads(Path(fp).read_text())
    ix_facts = None
    doc = ctx.get("doc_path")
    if doc and Path(doc).exists():
        ix_facts = inline_xbrl_facts(str(doc))

    if facts_json is None and ix_facts is None:
        return CheckResult(15, name, SKIP, "neither companyfacts nor the filing is readable")

    details, ok, compared, unavailable = [], True, 0, []
    for label, suffix in (("current", ""), ("prior", "_prior")):
        d = _as_date(row.get(f"period_end{suffix}"))
        if d is None:
            ok = False
            details.append(f"{label}: period_end{suffix} unparseable")
            continue
        for field_name, tag in XBRL_CROSSCHECK:
            panel_val = _num(row.get(f"{field_name}{suffix}"))
            ref, prov = (None, "")
            if facts_json is not None:
                ref, prov = companyfacts_value(facts_json, tag, d)
            if ref is None and ix_facts is not None:
                ref = ix_first(ix_facts, tag, d)
                prov = f"inline XBRL {tag} @ {d} (companyfacts had no fact for this date)"
            if ref is None:
                unavailable.append(f"{label} {field_name}: no XBRL fact for {tag} @ {d}")
                continue
            compared += 1
            if panel_val is None:
                ok = False
                details.append(f"{label} {field_name} is null but XBRL reports {_fmt(ref)} ({prov})")
                continue
            if not _close(panel_val, ref, 0.001):
                ok = False
                details.append(_diff_line(f"{label} {field_name} vs {prov}", panel_val, ref, "0.1%"))

    if compared == 0:
        return CheckResult(15, name, SKIP, "no XBRL facts available for either date", unavailable)
    if not ok:
        return _res(15, name, False, f"{len(details)} XBRL mismatch(es) over {compared} comparison(s)",
                    details + unavailable)
    if unavailable:
        return _res(15, name, True,
                    f"{compared} comparison(s) tie; {len(unavailable)} fact(s) unavailable",
                    unavailable, warn=True)
    return _res(15, name, True, f"{compared} comparison(s) tie within 0.1%")


# One printed digit in the filing's own units. A filing reporting "in millions"
# to one decimal moves in steps of 0.1M; one reporting in whole dollars moves in
# steps of well under a dollar. Read from the panel's recorded source_scale, so
# the gate derives it from the filing rather than assuming a scale.
_SCALE_UNIT = {"millions": 1e6, "thousands": 1e3, "units": 1.0}


def _presentation_granule(q: pd.DataFrame) -> float:
    scale = ""
    if "source_scale" in q.columns and len(q):
        scale = str(q["source_scale"].iloc[0]).strip().lower()
    return _SCALE_UNIT.get(scale, 1.0) / 10.0


def check_16_sanity_bounds(q: pd.DataFrame, inv: pd.DataFrame, ctx) -> CheckResult:
    name = "fair_value >= 0; fv/cost in [0,3] for debt; maturity in window"
    if q.empty:
        return _res(16, name, False, "bdc_quarter is empty")
    pe = _as_date(_one_row(q).get("period_end")) or _as_date(ctx.get("period_end"))
    details: list[str] = []
    skipped_notes: list[str] = []

    if "fair_value" not in inv.columns:
        details.append("investment panel has no fair_value column")
    else:
        fv = pd.to_numeric(inv["fair_value"], errors="coerce")
        neg = inv[fv < 0]
        if len(neg):
            worst = float(fv.min())
            details.append(f"{len(neg)} row(s) with fair_value < 0 (min {_fmt(worst)})")

    if {"fair_value", "cost", "investment_type"} <= set(inv.columns):
        types = inv["investment_type"].astype(str).str.strip().str.lower()
        fv = pd.to_numeric(inv["fair_value"], errors="coerce")
        cost = pd.to_numeric(inv["cost"], errors="coerce")
        # Materiality floor, from the filing's own presentation granularity.
        # A filing reporting in millions to one decimal prints cost in steps of
        # 0.1M, so a position printed as "0.1" carries +/-50% of rounding on its
        # own. The fv/cost ratio of such a row is dominated by that rounding and
        # says nothing about whether the columns were read correctly:
        # ARCC 2023 Q1 shows a revolver printed as principal 0.7, cost 0.1,
        # fair value 0.6 - a ratio of 6.0 built entirely out of one printed
        # digit each.
        #
        # This is safe because a genuine column misread is not confined to tiny
        # positions, and because the columns are already verified in aggregate
        # by three independent checks on the same run: 13 ties the fair-value
        # column to the balance sheet, 14 ties the cost column to the reported
        # total, and 15 ties both to the XBRL. On the filing above all three
        # passed (13 at 0.000000%, 14 at 0.001867%).
        granule = _presentation_granule(q)
        floor = 10.0 * granule
        material = cost >= floor
        debt = types.isin(DEBT_INVESTMENT_TYPES) & cost.notna() & (cost > 0) & fv.notna()
        ratio = (fv / cost).where(debt & material)
        bad = debt & material & ((ratio < 0) | (ratio > 3))
        if bad.any():
            worst = ratio[bad].abs().idxmax()
            details.append(
                f"{int(bad.sum())} debt row(s) with fair_value/cost outside [0, 3]; "
                f"worst ratio={_fmt(float(ratio[worst]))} "
                f"(fv={_fmt(float(fv[worst]))} cost={_fmt(float(cost[worst]))})"
            )
        n_immaterial = int((debt & ~material).sum())
        if n_immaterial:
            # Never a silent exemption.
            skipped_notes.append(
                f"fv/cost ratio not evaluated for {n_immaterial} debt row(s) with cost "
                f"below {_fmt(floor)} (10 presentation granules of {_fmt(granule)})"
            )

    if "maturity_date" in inv.columns and pe is not None:
        # Window widened from [-2y, +30y] after ARCC's 2020 Q1 filing showed
        # both ends are real rather than parse errors:
        #   * past due: NECCO ("due 1/2018"), Javlin ("due 6/2017") - a BDC
        #     holds defaulted paper years past its stated maturity;
        #   * long dated: Sunrun solar securitizations ("due 2/2055") - 35-year
        #     project finance.
        # Both were verified against the filing text before the bound moved.
        # The bound still catches a mangled date (year 1900, year 2199), which
        # is what it exists for. It is a plausibility bound, not a tolerance:
        # no tie-out, identity or XBRL tolerance has ever been widened.
        #
        # Split by instrument type. A loan maturing in 2100 is a parse error; a
        # warrant expiring in 2100 is a filer convention for "effectively no
        # expiry" - ARCC's 2022 10-K prints "8/2100" for a McLaren warrant, and
        # the parse is faithful to the page. Debt therefore keeps the tight
        # window; everything else keeps only a bound loose enough to catch a
        # mangled year while still admitting a nominal far-future expiry.
        lo, hi = pe - timedelta(days=10 * 366), pe + timedelta(days=40 * 366)
        lo_other, hi_other = date(1980, 1, 1), date(2200, 1, 1)
        types_all = (
            inv["investment_type"].astype(str).str.strip().str.lower()
            if "investment_type" in inv.columns
            else pd.Series(["" for _ in range(len(inv))], index=inv.index)
        )
        mats = inv["maturity_date"].map(_as_date)
        bad_debt, bad_other = [], []
        for idx, m in mats.items():
            if m is None:
                continue
            if types_all.get(idx, "") in DEBT_INVESTMENT_TYPES:
                if not (lo <= m <= hi):
                    bad_debt.append(m)
            elif not (lo_other <= m <= hi_other):
                bad_other.append(m)
        if bad_debt:
            details.append(
                f"{len(bad_debt)} DEBT maturity_date(s) outside [{lo}, {hi}]; "
                f"examples: {[b.isoformat() for b in sorted(bad_debt)[:5]]}"
            )
        if bad_other:
            details.append(
                f"{len(bad_other)} non-debt maturity_date(s) outside "
                f"[{lo_other}, {hi_other}]; "
                f"examples: {[b.isoformat() for b in sorted(bad_other)[:5]]}"
            )
    elif "maturity_date" not in inv.columns:
        details.append("investment panel has no maturity_date column")

    if details:
        return _res(16, name, False, f"{len(details)} sanity-bound violation(s)",
                    details + skipped_notes)
    return _res(16, name, True, f"{len(inv)} row(s) within bounds",
                skipped_notes, warn=bool(skipped_notes))


ALL_CHECKS = [
    check_01_quarter_unique,
    check_02_never_null,
    check_03_rows_exceed_borrowers,
    check_04_investment_type_vocab,
    check_05_two_dated_columns,
    check_06_current_column_equals_period,
    check_07_prior_gap,
    check_08_prior_kind,
    check_09_balance_sheet_identity,
    check_10_nav_per_share,
    check_11_columns_comparable,
    check_12_columns_not_identical,
    check_13_soi_tieout,
    check_14_cost_tieout,
    check_15_xbrl_crosscheck,
    check_16_sanity_bounds,
]


def run_all_checks(
    quarter_df: pd.DataFrame,
    investment_df: pd.DataFrame,
    context: dict | None = None,
) -> list[CheckResult]:
    """Run checks 1-16. An exception inside a check becomes a FAIL, never a pass."""
    ctx = dict(context or {})
    results: list[CheckResult] = []
    for fn in ALL_CHECKS:
        cid = int(fn.__name__.split("_")[1])
        try:
            results.append(fn(quarter_df, investment_df, ctx))
        except Exception as exc:  # fail closed
            results.append(CheckResult(cid, fn.__name__, FAIL,
                                       f"check raised {type(exc).__name__}: {exc}"))
    return results


def gate_passed(results: Sequence[CheckResult]) -> bool:
    return all(r.ok for r in results)


def format_report(results: Iterable[CheckResult]) -> str:
    results = list(results)
    width = max((len(r.name) for r in results), default=10)
    lines = ["", "=" * (width + 60),
             f"{'#':>3}  {'STATUS':<6}  {'CHECK':<{width}}  DETAIL",
             "-" * (width + 60)]
    for r in results:
        lines.append(f"{r.id:>3}  {r.status:<6}  {r.name:<{width}}  {r.message}")
        for d in r.details:
            lines.append(f"{'':>3}  {'':<6}  {'':<{width}}    -> {d}")
    lines.append("-" * (width + 60))
    counts = {s: sum(1 for r in results if r.status == s) for s in (PASS, FAIL, WARN, SKIP)}
    lines.append(f"     {counts[PASS]} pass, {counts[FAIL]} fail, "
                 f"{counts[WARN]} warn, {counts[SKIP]} skip")
    lines.append("=" * (width + 60))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Promotion
# ---------------------------------------------------------------------------

PANELS = ("bdc_quarter", "bdc_quarter_investment")


def promote(interim: Path = INTERIM, output: Path = OUTPUT) -> list[Path]:
    """Copy both panels to output/ as CSV plus a Parquet twin (plan section 1)."""
    output.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for stem in PANELS:
        src = interim / f"{stem}.csv"
        dst = output / f"{stem}.csv"
        shutil.copyfile(src, dst)
        written.append(dst)
        try:
            pq = output / f"{stem}.parquet"
            pd.read_csv(src).to_parquet(pq, index=False)
            written.append(pq)
        except ImportError as exc:  # pyarrow missing
            log.error("Parquet twin NOT written for %s: %s. Install pyarrow.", stem, exc)
    return written


def load_panels(interim: Path = INTERIM) -> tuple[pd.DataFrame, pd.DataFrame]:
    q = pd.read_csv(interim / "bdc_quarter.csv")
    i = pd.read_csv(interim / "bdc_quarter_investment.csv")
    return q, i


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="BDC panel verification gate (checks 1-16).")
    ap.add_argument("--interim", type=Path, default=INTERIM)
    ap.add_argument("--output", type=Path, default=OUTPUT)
    ap.add_argument("--no-promote", action="store_true",
                    help="run the checks but never write to output/")
    args = ap.parse_args(argv)

    for stem in PANELS:
        p = args.interim / f"{stem}.csv"
        if not p.exists():
            print(f"FATAL: {p} does not exist. Run the parser first.", file=sys.stderr)
            return 2

    quarter_df, investment_df = load_panels(args.interim)
    ctx = build_context()
    results = run_all_checks(quarter_df, investment_df, ctx)
    print(format_report(results))

    if not gate_passed(results):
        failed = [r.id for r in results if r.status == FAIL]
        print(f"\nGATE FAILED on check(s) {failed}. Nothing written to {args.output}.",
              file=sys.stderr)
        return 1

    if args.no_promote:
        print("\nGATE PASSED. --no-promote given, nothing written.")
        return 0

    written = promote(args.interim, args.output)
    print("\nGATE PASSED. Promoted:")
    for p in written:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
