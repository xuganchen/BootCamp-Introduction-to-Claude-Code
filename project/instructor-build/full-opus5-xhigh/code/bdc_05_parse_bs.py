"""Stage 05 - balance-sheet fields -> data/interim/balance_sheet.json

Both dated columns are extracted (plan section 3.1).  A 10-Q balance sheet
prints the quarter end next to the prior fiscal year end; the comparative
column is internally consistent, so every accounting identity check would pass
on it too.  Reading only one column and labelling it with `periodOfReport` is
therefore an error no downstream check could catch - which is why both are
extracted and the choice is made explicit.

Column alignment (trap 11)
--------------------------
The two dated headers sit in merged cells spanning several physical columns,
with an empty spacer column and a stray dollar-sign column between them.  The
map from header date to physical column range is built ONCE from the header
row, asserted, and reused for every data row.  It is never re-derived per row,
because a per-row guess is silent when it is wrong.

`period_end_prior` is read from the comparative column's own header text.  It
is never computed as `period_end` minus a quarter or a year: for a 10-Q the
comparative is normally the prior fiscal year end, so an inferred date would
usually be wrong.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date

from bdc_03_extract import load_document, table_grid
from bdc_06_normalize import clean_name, parse_number, scale_factor
from bdc_09_utils import INTERIM, log, parse_date, write_json

OUT_PATH = INTERIM / "balance_sheet.json"

# Row-label patterns for each schema field, matched against the normalised
# leading label.  Ordered; first match wins per field, and a field is only
# taken once (the first occurrence in statement order).
LABEL_RULES: list[tuple[str, re.Pattern]] = [
    ("total_investments_fv", re.compile(r"^total investments(?: at fair value)?\b", re.I)),
    ("total_assets", re.compile(r"^total assets$", re.I)),
    ("total_liabilities", re.compile(r"^total liabilities$", re.I)),
    ("net_assets", re.compile(r"^(?:total )?(?:net assets|stockholders.? equity|shareholders.? equity|members.? equity|partners.? capital)$", re.I)),
    ("nav_per_share", re.compile(r"^net asset value per share\b|^net assets? value per (?:common )?share\b", re.I)),
    ("total_debt_outstanding", re.compile(r"^(?:total )?debt$|^debt, net\b|^total borrowings$|^borrowings$", re.I)),
]

# Share count is printed inside the common-stock caption, not in a value cell:
#   "... 1,000 common shares authorized; 718 common shares issued and outstanding"
# When the filer prints two figures ("718 and 717 ... respectively") the first
# is the current column and the second the comparative.
SHARES_RE = re.compile(
    r"([\d,\.]+)(?:\s+and\s+([\d,\.]+))?\s+(?:common\s+)?shares?\s+issued\s+and\s+outstanding",
    re.I,
)


class BalanceSheetError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# the header -> column map, built once
# --------------------------------------------------------------------------


# A header split across two rows: a shared month-and-day caption above, one
# bare year per column below.
#
#     row 1:  col 3  "As of December 31,"
#     row 2:  col 3  "2025"          col 9  "2024"
#
# ARCC's 10-K uses this for every year sampled, while its 10-Q writes the full
# date in one cell. Neither row alone carries a parseable date, so a scan that
# only reads single cells finds no header at all and the run aborts.
_MONTH_DAY_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+(\d{1,2})\s*,?\s*$",
    re.I,
)
_BARE_YEAR_RE = re.compile(r"^(19|20)\d{2}$")
HEADER_LOOKBACK = 4  # rows above a year row that may carry the month-and-day


def _month_day_above(grid: list[list[str]], row_i: int) -> str | None:
    """The nearest month-and-day caption above `row_i`, if there is one."""
    for back in range(1, HEADER_LOOKBACK + 1):
        j = row_i - back
        if j < 0:
            break
        for cell in grid[j]:
            if not cell or len(cell) > 40:
                continue
            text = re.sub(r"^\s*as\s+of\s+", "", cell, flags=re.I).strip()
            m = _MONTH_DAY_RE.search(text)
            if m:
                return f"{m.group(1)} {m.group(2)}"
    return None


def _dated_columns(grid: list[list[str]], row_i: int) -> list[tuple[int, date]]:
    """Dated columns declared by row `row_i`, whole-date or year-only."""
    row = grid[row_i]
    dated: list[tuple[int, date]] = []
    for col_i, cell in enumerate(row):
        if not cell:
            continue
        text = re.sub(r"\((?:un)?audited\)", "", cell, flags=re.I).strip()
        if len(text) > 40:
            continue
        d = parse_date(text)
        if d is not None:
            dated.append((col_i, d))
    if len(dated) >= 2:
        return dated

    # Year-only header row: compose with the caption above. The month and day
    # come from the filing's own text, never from `periodOfReport` - composing
    # against the period end would make the "current column equals
    # periodOfReport" assertion circular and unable to fail.
    years = [
        (col_i, cell.strip())
        for col_i, cell in enumerate(row)
        if cell and _BARE_YEAR_RE.match(cell.strip())
    ]
    if len(years) < 2:
        return dated
    month_day = _month_day_above(grid, row_i)
    if month_day is None:
        return dated
    composed: list[tuple[int, date]] = []
    for col_i, year in years:
        d = parse_date(f"{month_day}, {year}")
        if d is not None:
            composed.append((col_i, d))
    return composed if len(composed) >= 2 else dated


def build_column_map(grid: list[list[str]]) -> tuple[int, list[tuple[date, int, int]]]:
    """Return (header_row_index, [(header_date, start_col, end_col), ...]).

    Fails when the statement presents anything other than exactly two dated
    columns: guessing which of three columns is comparative is exactly the
    silent error this map exists to prevent.
    """
    for row_i, row in enumerate(grid[:8]):
        dated = _dated_columns(grid, row_i)
        if len(dated) < 2:
            continue
        if len(dated) > 2:
            raise BalanceSheetError(
                f"balance sheet presents {len(dated)} dated columns "
                f"({[(c, d.isoformat()) for c, d in dated]}); refusing to guess which is comparative"
            )
        width = len(row)
        spans = []
        for k, (col_i, d) in enumerate(dated):
            end = dated[k + 1][0] if k + 1 < len(dated) else width
            spans.append((d, col_i, end))
        return row_i, spans
    raise BalanceSheetError("no balance-sheet header row with two parseable dates found")


def column_value(row: list[str], span: tuple[int, int]) -> float | None:
    """First parseable number inside a column's physical range."""
    start, end = span
    for tok in row[start:end]:
        if not tok or tok == "$":
            continue
        v = parse_number(tok)
        if v is not None:
            return v
    return None


# --------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------


def parse_balance_sheet(root, table_index: int, scale: str, period_end: date,
                        fiscal_year_end: str) -> dict:
    grid = table_grid(root.xpath("//table")[table_index])
    header_i, spans = build_column_map(grid)
    factor = scale_factor(scale)

    dates = [d for d, _, _ in spans]
    log.info("balance sheet: header dates %s, column ranges %s, scale=%s",
             [d.isoformat() for d in dates], [(s, e) for _, s, e in spans], scale)

    # ---- assert the map, once, before reading any row --------------------
    if period_end not in dates:
        raise BalanceSheetError(
            f"neither balance-sheet header date {[d.isoformat() for d in dates]} equals "
            f"periodOfReport {period_end.isoformat()}"
        )
    if dates[0] == dates[1]:
        raise BalanceSheetError(f"both balance-sheet header dates are {dates[0].isoformat()}")

    cur_i = dates.index(period_end)
    pri_i = 1 - cur_i
    period_end_prior = dates[pri_i]
    if period_end_prior >= period_end:
        raise BalanceSheetError(
            f"comparative header date {period_end_prior.isoformat()} is not before "
            f"period_end {period_end.isoformat()}"
        )
    cur_span = (spans[cur_i][1], spans[cur_i][2])
    pri_span = (spans[pri_i][1], spans[pri_i][2])

    # ---- period_end_prior_kind, from the filer's own fiscal year end -----
    fye_month, fye_day = int(fiscal_year_end[:2]), int(fiscal_year_end[2:])
    is_fye = (period_end_prior.month, period_end_prior.day) == (fye_month, fye_day)
    kind = "prior_fiscal_year_end" if is_fye else "prior_quarter_end"
    if not is_fye:
        log.warning(
            "comparative column %s is not the fiscal year end %s/%s; recording kind=prior_quarter_end",
            period_end_prior.isoformat(), fye_month, fye_day,
        )

    # ---- read every row against the same map -----------------------------
    out: dict = {
        "period_end": period_end.isoformat(),
        "period_end_prior": period_end_prior.isoformat(),
        "period_end_prior_kind": kind,
        "source_scale": scale,
        "header_dates": [d.isoformat() for d in dates],
        "column_map": {
            "current": {"header_date": period_end.isoformat(), "cols": list(cur_span)},
            "prior": {"header_date": period_end_prior.isoformat(), "cols": list(pri_span)},
        },
        "n_dated_columns": len(dates),
    }
    seen: set[str] = set()
    matched_labels: dict[str, str] = {}
    shares_caption: str | None = None

    for row in grid[header_i + 1 :]:
        label = clean_name(row[0]) if row else ""
        if not label:
            continue
        if shares_caption is None and SHARES_RE.search(label):
            shares_caption = label
        for field, pattern in LABEL_RULES:
            if field in seen or not pattern.match(label):
                continue
            cur = column_value(row, cur_span)
            pri = column_value(row, pri_span)
            if cur is None and pri is None:
                continue
            per_share = field == "nav_per_share"
            mult = 1.0 if per_share else factor
            out[field] = None if cur is None else cur * mult
            out[f"{field}_prior"] = None if pri is None else pri * mult
            seen.add(field)
            matched_labels[field] = label
            break

    # ---- shares outstanding, from the common-stock caption ---------------
    out["shares_outstanding"] = None
    out["shares_outstanding_prior"] = None
    if shares_caption:
        m = SHARES_RE.search(shares_caption)
        cur_sh = parse_number(m.group(1))
        pri_sh = parse_number(m.group(2)) if m.group(2) else cur_sh
        # Share counts in these captions carry the statement's own scale
        # ("in millions, except per share data" -> 718 means 718,000,000).
        out["shares_outstanding"] = None if cur_sh is None else cur_sh * factor
        out["shares_outstanding_prior"] = None if pri_sh is None else pri_sh * factor
        out["shares_caption"] = shares_caption
        if m.group(2) is None:
            log.info("balance sheet: one share figure in the caption; applied to both columns")

    # ---- reported total amortized cost, for tie-out check 14 -------------
    # Printed inside the total-investments caption, not as its own row:
    #   "Total investments at fair value (amortized cost of $29,675 and $29,250, respectively)"
    cost_caption = matched_labels.get("total_investments_fv", "")
    mc = re.search(
        r"amortized cost of \$?\s*([\d,\.]+)(?:\s+and\s+\$?\s*([\d,\.]+))?",
        cost_caption, re.I,
    )
    out["total_investments_cost"] = None
    out["total_investments_cost_prior"] = None
    if mc:
        c1 = parse_number(mc.group(1))
        c2 = parse_number(mc.group(2)) if mc.group(2) else None
        out["total_investments_cost"] = None if c1 is None else c1 * factor
        out["total_investments_cost_prior"] = None if c2 is None else c2 * factor

    out["matched_labels"] = matched_labels

    required = ["total_investments_fv", "total_assets", "total_liabilities", "net_assets"]
    missing = [f for f in required if out.get(f) is None]
    if missing:
        raise BalanceSheetError(
            f"never-null balance-sheet fields not found: {missing}; labels matched: {matched_labels}"
        )
    missing_prior = [f"{f}_prior" for f in required if out.get(f"{f}_prior") is None]
    if missing_prior:
        raise BalanceSheetError(f"never-null comparative fields not found: {missing_prior}")
    return out


def main() -> int:
    manifest = json.loads((INTERIM / "manifest.json").read_text())
    extract = json.loads((INTERIM / "extract.json").read_text())
    root = load_document(manifest["doc_path"])
    result = parse_balance_sheet(
        root,
        extract["balance_sheet"]["index"],
        extract["balance_sheet_scale"],
        parse_date(manifest["period_end"]),
        str(manifest["fiscal_year_end"]),
    )
    write_json(OUT_PATH, result)
    log.info(
        "balance sheet: current %s total_assets=%.0f net_assets=%.0f investments=%.0f | "
        "prior %s (%s) total_assets=%.0f",
        result["period_end"], result["total_assets"], result["net_assets"],
        result["total_investments_fv"], result["period_end_prior"],
        result["period_end_prior_kind"], result["total_assets_prior"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
