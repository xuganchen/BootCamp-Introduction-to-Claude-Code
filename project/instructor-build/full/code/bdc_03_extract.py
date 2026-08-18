"""Stage 03 - locate the balance sheet and every Schedule of Investments fragment.

The filing is a single ~25 MB inline-XBRL HTML document with ~275 <table>
elements.  Nothing about a table's own markup says what it is, but every
financial-statement table in an EDGAR filing is preceded by a *banner*: the
registrant name, the statement title, an "As of <date>" line and a scale line
such as "(dollar amounts in millions)".  This module walks the document once in
document order, attaches the banner text that precedes each table to that
table, and classifies tables from the banner.

Why this matters for correctness:

  * A 10-Q for a BDC contains TWO complete Schedules of Investments - one as of
    the quarter end and one as of the prior fiscal year end.  They are visually
    identical and use the same column layout.  Summing both would roughly
    double the portfolio and blow the tie-out.  The banner's "As of" line is
    the only reliable discriminator, so we read it per fragment and keep only
    the fragments whose as-of date equals `period_end`.
  * The scale ("in millions" / "in thousands") is declared per statement, in
    the banner, not once for the document.  We resolve it per table and record
    it, rather than assuming a document-wide scale.

Outputs `data/interim/extract.json` describing what was found.  Downstream
stages import `load_document()` / `find_sections()` rather than re-deriving.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import lxml.html

from bdc_09_utils import INTERIM, log, parse_date, write_json

# --------------------------------------------------------------------------
# banner / classification vocabulary
# --------------------------------------------------------------------------

BS_TITLE_RE = re.compile(
    r"CONSOLIDATED\s+(BALANCE\s+SHEETS?|STATEMENTS?\s+OF\s+ASSETS\s+AND\s+LIABILITIES)"
    r"|^\s*(BALANCE\s+SHEETS?|STATEMENTS?\s+OF\s+ASSETS\s+AND\s+LIABILITIES)\s*$",
    re.I,
)
SOI_TITLE_RE = re.compile(r"SCHEDULES?\s+OF\s+INVESTMENTS", re.I)

# "(dollar amounts in millions)", "(in thousands, except per share data)"
SCALE_RE = re.compile(r"\(\s*(?:dollar\s+amounts\s+)?in\s+(millions|thousands)\b", re.I)

SCALE_FACTOR = {"millions": 1e6, "thousands": 1e3, "units": 1.0}

# How many text blocks before a table are considered part of its banner.
BANNER_LOOKBACK = 10


# --------------------------------------------------------------------------
# data classes
# --------------------------------------------------------------------------


@dataclass
class TableRef:
    """One classified <table> in the filing."""

    index: int  # position in document order among all <table> elements
    kind: str  # "balance_sheet" | "soi" | "other"
    banner: list[str] = field(default_factory=list)
    as_of: str | None = None  # ISO date parsed from the banner, SOI only
    scale: str = "units"  # "millions" | "thousands" | "units"
    audited: bool | None = None  # None = not stated
    n_rows: int = 0
    continuation_of: int | None = None  # set when the banner was inherited


# --------------------------------------------------------------------------
# document loading and banner capture
# --------------------------------------------------------------------------


def load_document(doc_path: str | Path):
    """Parse the filing.  ~0.5 s for a 25 MB document; callers should cache."""
    root = lxml.html.parse(str(doc_path)).getroot()
    return root


# Older EDGAR documents are CP-1252 but are served without a usable charset
# declaration, so the parser decodes the 0x80-0x9F punctuation range as C1
# control characters instead of the punctuation the filer typed. The one that
# matters is 0x97, the em dash: it is how these filings write "zero", and left
# as U+0097 it reaches parse_number as an unrecognised character, so the cell
# reads as missing rather than 0.0. On ARCC's 2005 Q1 that was the difference
# between a null fair_value and a reported zero.
_CP1252_PUNCT = {
    0x82: ",", 0x84: '"', 0x85: "...", 0x91: "'", 0x92: "'",
    0x93: '"', 0x94: '"', 0x95: "-", 0x96: "–", 0x97: "—",
    0x99: "(TM)", 0xA0: " ",
}


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s.translate(_CP1252_PUNCT)).strip()


# Tags that render as their own line or box. Text on either side of one of
# these is separated visually, so it must be separated textually too.
_BLOCK_TAGS = frozenset(
    {"div", "p", "br", "li", "tr", "td", "th", "table", "ul", "ol",
     "h1", "h2", "h3", "h4", "h5", "h6"}
)


def _text_with_boundaries(el, out: list[str]) -> None:
    """Collect an element's text, inserting a space at every block boundary."""
    if el.tag in _BLOCK_TAGS:
        out.append(" ")
    if el.text:
        out.append(el.text)
    for child in el:
        _text_with_boundaries(child, out)
        if child.tag in _BLOCK_TAGS:
            out.append(" ")
        if child.tail:
            out.append(child.tail)


def cell_text(el) -> str:
    """Visible text of a cell, with word boundaries preserved.

    `lxml`'s `text_content()` concatenates descendant text with no separator,
    which is right for inline markup ("<b>SO</b>FR" -> "SOFR") and wrong at a
    block boundary. Filers stack a two-line header as two sibling <div>s:

        <td><div>Amortized</div><div>Cost</div></td>

    `text_content()` returns "AmortizedCost", so the header no longer matches
    "amortized cost", and "Percentage" + "of Net Assets" becomes
    "Percentageof Net Assets". The damage is not limited to headers - any
    stacked cell (a borrower name wrapped onto two lines, an investment
    description) loses the same space.

    Fixing this here rather than by loosening the header patterns is the point:
    a pattern that matched "AmortizedCost" would accept the corrupted text
    everywhere else too.
    """
    parts: list[str] = []
    _text_with_boundaries(el, parts)
    return _clean("".join(parts))


def table_grid(table) -> list[list[str]]:
    """Expand a <table> into a rectangular grid of strings, honouring colspan.

    Colspan expansion is what makes column identity stable: in these filings a
    reported number is split across several physical cells ("$" in one cell,
    "1,234" in the next, a footnote marker "(2)(9)" in a third), and the number
    of physical <td>s per row therefore varies row to row.  After expansion,
    every row has the same width and a header cell's start index is a fixed
    coordinate that data rows can be read against.

    rowspan is deliberately NOT expanded: these filings do not use it for
    numeric data, and honouring it would silently duplicate values.
    """
    out: list[list[str]] = []
    for tr in table.xpath(".//tr"):
        row: list[str] = []
        for cell in tr.xpath("./td|./th"):
            try:
                span = int(cell.get("colspan", 1) or 1)
            except ValueError:
                span = 1
            span = max(1, min(span, 64))
            row.append(cell_text(cell))
            row.extend([""] * (span - 1))
        out.append(row)
    if not out:
        return out
    width = max(len(r) for r in out)
    for r in out:
        r.extend([""] * (width - len(r)))
    return out


def _iter_tables_with_banners(root) -> list[tuple[int, object, list[str]]]:
    """Yield (index, table_element, banner_lines) in document order.

    banner_lines are the non-empty text blocks that appear between the previous
    table and this one, outside of any table.
    """
    tables = root.xpath("//table")
    table_ids = {id(t): i for i, t in enumerate(tables)}
    result: list[tuple[int, object, list[str]]] = []
    buf: list[str] = []
    for el in root.iter():
        tid = table_ids.get(id(el))
        if tid is not None and el.tag == "table":
            result.append((tid, el, buf[-BANNER_LOOKBACK:]))
            buf = []
            continue
        text = (el.text or "").strip()
        if not text:
            continue
        # skip text that lives inside a table (it belongs to that table)
        if any(a.tag == "table" for a in el.iterancestors()):
            continue
        buf.append(_clean(text))
    # tables reached by iter() are in document order already
    assert [r[0] for r in result] == sorted(r[0] for r in result), "table order broken"
    return result


# --------------------------------------------------------------------------
# banner interpretation
# --------------------------------------------------------------------------


# A statement title is a standalone heading line, not a phrase buried in prose.
# Without this guard "...included in the accompanying consolidated balance
# sheets." inside a footnote would classify the next unrelated table as the
# balance sheet.
MAX_TITLE_LINE = 80
MIN_TITLE_COVERAGE = 0.6


def _banner_title_pos(banner: list[str], pattern: re.Pattern) -> int | None:
    for i, line in enumerate(banner):
        if len(line) > MAX_TITLE_LINE:
            continue
        m = pattern.search(line)
        if m and (m.end() - m.start()) >= MIN_TITLE_COVERAGE * len(line.strip()):
            return i
    return None


def _scale_from(lines: list[str]) -> str:
    for line in lines:
        m = SCALE_RE.search(line)
        if m:
            return m.group(1).lower()
    return "units"


def _as_of_from(lines: list[str]) -> date | None:
    """Read the statement's as-of date from the lines below the title.

    Trap 12: the line is prose ("As of June 30, 2026", "December 31, 2025
    (audited)").  parse_date strips the qualifiers.  We only look at lines that
    are essentially just a date, so a sentence that merely mentions a date
    (a footnote spilling over from the previous page) cannot win.
    """
    for line in lines:
        stripped = re.sub(r"^\s*as\s+of\s+", "", line, flags=re.I)
        stripped = re.sub(r"\((?:un)?audited\)", "", stripped, flags=re.I).strip(" .,")
        if len(stripped) > 40:
            continue
        d = parse_date(stripped)
        if d is not None:
            return d
    return None


def _audited_from(lines: list[str]) -> bool | None:
    joined = " ".join(lines).lower()
    if "(unaudited)" in joined:
        return False
    if "(audited)" in joined:
        return True
    return None


def _attach_soi_continuations(root, refs: list[TableRef]) -> int:
    """Adopt SOI continuation pages that carry no banner of their own.

    Modern filings repeat the whole banner - title, "As of <date>", scale - on
    every printed page of the Schedule of Investments, so every fragment
    classifies itself. Older filings print the banner once and let the table
    run on across pages; the continuation tables repeat only the *column
    header* row.

    Those continuations were being classified "other" and silently dropped. On
    ARCC's 2005 Q1 that lost half the portfolio: the SOI is 4 tables (current,
    its continuation, comparative, its continuation) and only the two banner
    carrying ones were parsed, leaving the tie-out 36.3% short.

    A table is adopted only when all of these hold:
      * it is currently classified "other";
      * the table immediately before it in document order is an SOI fragment
        or an already-adopted continuation (an unbroken chain);
      * its own grid contains a full SOI column header row.

    The chain breaks at the first table that fails the header test, so a note
    table after the schedule cannot pull the rest of the document in. A
    continuation inherits the as-of date, scale and audited flag of its chain
    head, which keeps the current/comparative split intact: a comparative
    fragment's continuations inherit the comparative date and are dropped with
    it.
    """
    # Deferred import: bdc_04 imports this module, so importing it at module
    # level would be circular.
    from bdc_04_parse_soi import SOIParseError, find_header_row

    tables = root.xpath("//table")
    adopted = 0
    head: TableRef | None = None
    for ref in refs:
        if ref.kind == "soi":
            head = ref
            continue
        if ref.kind != "other" or head is None:
            head = None
            continue
        try:
            find_header_row(table_grid(tables[ref.index]))
        except SOIParseError:
            head = None  # chain broken: this is not part of the schedule
            continue
        ref.kind = "soi"
        ref.as_of = head.as_of
        ref.scale = head.scale
        ref.audited = head.audited
        ref.continuation_of = head.index
        adopted += 1
        head = ref
    return adopted


def classify(root) -> list[TableRef]:
    """Classify every table in the document from its banner."""
    refs: list[TableRef] = []
    for idx, table, banner in _iter_tables_with_banners(root):
        n_rows = len(table.xpath(".//tr"))
        soi_pos = _banner_title_pos(banner, SOI_TITLE_RE)
        bs_pos = _banner_title_pos(banner, BS_TITLE_RE)
        if soi_pos is not None:
            tail = banner[soi_pos + 1 :]
            refs.append(
                TableRef(
                    index=idx,
                    kind="soi",
                    banner=banner,
                    as_of=(_as_of_from(tail).isoformat() if _as_of_from(tail) else None),
                    scale=_scale_from(tail) or "units",
                    audited=_audited_from(tail),
                    n_rows=n_rows,
                )
            )
        elif bs_pos is not None:
            tail = banner[bs_pos + 1 :]
            refs.append(
                TableRef(
                    index=idx,
                    kind="balance_sheet",
                    banner=banner,
                    as_of=None,  # BS dates come from the table header, not the banner
                    scale=_scale_from(tail) or "units",
                    audited=_audited_from(tail),
                    n_rows=n_rows,
                )
            )
        else:
            refs.append(TableRef(index=idx, kind="other", banner=banner, n_rows=n_rows))
    adopted = _attach_soi_continuations(root, refs)
    if adopted:
        log.info("classify: adopted %d SOI continuation page(s) that carry no banner "
                 "of their own", adopted)
    return refs


# --------------------------------------------------------------------------
# section selection
# --------------------------------------------------------------------------


class ExtractionError(RuntimeError):
    pass


def find_sections(root, period_end: date) -> dict:
    """Pick the balance sheet and the current-period SOI fragments.

    Fails loudly rather than guessing:
      * no balance sheet, or more than one distinct balance-sheet statement;
      * no SOI fragment dated `period_end`;
      * an SOI fragment whose banner carries no parseable as-of date.
    """
    refs = classify(root)

    bs = [r for r in refs if r.kind == "balance_sheet"]
    if not bs:
        raise ExtractionError("no balance sheet found (looked for CONSOLIDATED BALANCE SHEET(S) / STATEMENTS OF ASSETS AND LIABILITIES)")
    if len(bs) > 1:
        # A 10-Q prints the balance sheet once; more than one means the banner
        # matched something else and we should not guess.
        raise ExtractionError(f"expected exactly 1 balance-sheet table, found {len(bs)} at indices {[r.index for r in bs]}")
    balance_sheet = bs[0]

    soi_all = [r for r in refs if r.kind == "soi"]
    if not soi_all:
        raise ExtractionError("no Schedule of Investments fragments found")
    undated = [r.index for r in soi_all if r.as_of is None]
    if undated:
        raise ExtractionError(f"SOI fragments with no parseable as-of date: {undated}")

    target = period_end.isoformat()
    soi_current = [r for r in soi_all if r.as_of == target]
    if not soi_current:
        raise ExtractionError(
            f"no SOI fragment dated {target}; fragment dates seen: {sorted({r.as_of for r in soi_all})}"
        )

    scales = sorted({r.scale for r in soi_current})
    if len(scales) > 1:
        raise ExtractionError(f"current-period SOI fragments disagree on scale: {scales}")

    dropped = sorted({r.as_of for r in soi_all if r.as_of != target})
    if dropped:
        log.info("dropping %d comparative SOI fragments dated %s",
                 len(soi_all) - len(soi_current), dropped)

    return {
        "balance_sheet": balance_sheet,
        "soi_current": soi_current,
        "soi_all_dates": sorted({r.as_of for r in soi_all}),
        "n_soi_dropped": len(soi_all) - len(soi_current),
    }


def find_non_accrual_footnote(root, period_end: date) -> int | None:
    """Discover which SOI footnote number marks non-accrual status (trap 7).

    The number is not stable across filers or across years, so it is read from
    the footnote legend rather than hardcoded.  The legend is period-specific
    ("Loan was on non-accrual status as of June 30, 2026."), and the comparative
    SOI carries its own legend with the prior date, so we anchor on the date to
    make sure we pick up the current period's marker.
    """
    text = _clean(root.body.text_content() if root.body is not None else root.text_content())
    long_date = f"{period_end.strftime('%B')} {period_end.day}, {period_end.year}"
    m = re.search(
        r"\((\d{1,2})\)\s*[^()]{0,120}?non-accrual[^()]{0,120}?" + re.escape(long_date),
        text,
        re.I,
    )
    if m:
        return int(m.group(1))
    m = re.search(r"\((\d{1,2})\)\s*[^()]{0,120}?non-accrual", text, re.I)
    if m:
        log.warning("non-accrual footnote legend found but not tied to %s; using (%s)", long_date, m.group(1))
        return int(m.group(1))
    log.warning("no non-accrual footnote legend found; is_non_accrual will be False for every row")
    return None


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def main() -> int:
    manifest = json.loads((INTERIM / "manifest.json").read_text())
    period_end = parse_date(manifest["period_end"])
    root = load_document(manifest["doc_path"])
    sections = find_sections(root, period_end)
    na_fn = find_non_accrual_footnote(root, period_end)

    payload = {
        "period_end": period_end.isoformat(),
        "balance_sheet": asdict(sections["balance_sheet"]),
        "soi_current_indices": [r.index for r in sections["soi_current"]],
        "soi_scale": sections["soi_current"][0].scale,
        "soi_as_of": sections["soi_current"][0].as_of,
        "soi_audited": sections["soi_current"][0].audited,
        "soi_all_dates": sections["soi_all_dates"],
        "n_soi_fragments_current": len(sections["soi_current"]),
        "n_soi_fragments_dropped": sections["n_soi_dropped"],
        "balance_sheet_scale": sections["balance_sheet"].scale,
        "balance_sheet_audited": sections["balance_sheet"].audited,
        "non_accrual_footnote": na_fn,
    }
    write_json(INTERIM / "extract.json", payload)
    log.info(
        "extract: balance sheet at table %d (scale=%s); %d current SOI fragments (scale=%s, as of %s); "
        "%d comparative fragments dropped; non-accrual footnote=(%s)",
        sections["balance_sheet"].index,
        sections["balance_sheet"].scale,
        len(sections["soi_current"]),
        sections["soi_current"][0].scale,
        sections["soi_current"][0].as_of,
        sections["n_soi_dropped"],
        na_fn,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
