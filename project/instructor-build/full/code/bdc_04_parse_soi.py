"""Stage 04 - Schedule of Investments position rows -> data/interim/soi_rows.csv

The SOI is one logical table printed across ~67 HTML tables (one per printed
page).  Every fragment repeats the column header, and state - the industry
heading and the borrower name - runs *across* fragment boundaries, because a
borrower's tranches can straddle a page break.  So the fragments are walked in
document order as a single stream with carried state.

Column identity
---------------
Physical <td> counts vary row to row (a "$" sits in its own cell, footnote
markers sit in another), so cells are first expanded by colspan into a
rectangular grid (`bdc_03_extract.table_grid`).  In the expanded grid a header
label occupies a fixed start index, and each header defines a *region* running
from its own start index to the next header's start index.  A data value is
then "the numeric token somewhere in this region", which is robust to the
dollar-sign and footnote cells drifting within the region.

Row classification (trap 1 - the tie-out killer)
------------------------------------------------
Subtotals are detected structurally, never by row index:

  * a row carrying money but no investment description is a subtotal
    (per-borrower subtotals print only Amortized Cost / Fair Value / % of Net
    Assets, with the borrower and investment columns blank);
  * a row whose leading label matches /^Total\\b/ is a total row;
  * a row with a label and nothing else is a section heading (industry);
  * a row with no text at all is a spacer (trap 9).

Every row is written out with `is_subtotal_row` so the exclusion is auditable;
stage 06 drops the flagged rows and they never reach the panel.
"""

from __future__ import annotations

import json
import re
import sys

import pandas as pd

from bdc_03_extract import load_document, table_grid
from bdc_06_normalize import (
    clean_name,
    footnote_numbers,
    parse_all_in_rate_pct,
    parse_combined_spread_bps,
    parse_due_from_description,
    parse_money,
    parse_number,
    parse_par_from_description,
    parse_pik_rate_pct,
    parse_reference_rate,
    parse_soi_date,
    parse_spread_bps,
    scale_factor,
    strip_footnotes,
)
from bdc_09_utils import INTERIM, log, parse_date

OUT_PATH = INTERIM / "soi_rows.csv"

# Header labels -> canonical field name.  Matched against the header row of each
# fragment; the label carries its own footnote marker ("Company (1)"), which is
# stripped before matching.
HEADER_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^company$|^portfolio company$|^issuer$", re.I), "company"),
    (re.compile(r"^business description$|^industry$", re.I), "business_description"),
    (re.compile(r"^investment$|^type of investment$", re.I), "investment"),
    (re.compile(r"^coupon$|^interest rate$|^rate$|^interest$|^stated interest rate$", re.I), "coupon"),
    (re.compile(r"^reference$|^reference rate$|^index$", re.I), "reference"),
    (re.compile(r"^spread$", re.I), "spread"),
    (re.compile(r"^acquisition date$|^initial acquisition date$", re.I), "acquisition_date"),
    (re.compile(r"^maturity date$|^maturity$", re.I), "maturity_date"),
    (re.compile(r"^shares?/units?$|^shares$|^units$|^number of shares", re.I), "shares_units"),
    (re.compile(r"^principal", re.I), "principal"),
    (re.compile(r"^amortized cost$|^cost$", re.I), "cost"),
    # Must precede the fair_value entry. This column is a per-unit price, not a
    # position value. It is not carried into the panel, but it has to be mapped:
    # a region runs from its own header to the NEXT MAPPED header, so leaving
    # this unmapped extends the fair-value region across it and lets a per-unit
    # price be read as a position's fair value whenever the real cell is blank.
    (re.compile(r"^fair value per unit$|^fair value/unit$|^value per unit$", re.I),
     "fair_value_per_unit"),
    (re.compile(r"^fair value$|^value$", re.I), "fair_value"),
    (re.compile(r"^% of net assets$|^percentage of net assets$", re.I), "pct_of_net_assets"),
]

REQUIRED_HEADERS = {"company", "investment", "cost", "fair_value"}

_TOTAL_LABEL = re.compile(r"^\s*(total|subtotal)\b", re.I)
_NUMLIKE = re.compile(r"\d")


class SOIParseError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# header -> region map
# --------------------------------------------------------------------------


def find_header_row(grid: list[list[str]]) -> tuple[int, dict[str, tuple[int, int]]]:
    """Locate the header row and turn it into {field: (start, end)} regions."""
    for row_i, row in enumerate(grid[:6]):
        hits: list[tuple[int, str]] = []
        for col_i, raw in enumerate(row):
            label = clean_name(raw)
            if not label:
                continue
            for pattern, field in HEADER_MAP:
                if pattern.match(label):
                    hits.append((col_i, field))
                    break
        found = {f for _, f in hits}
        if REQUIRED_HEADERS.issubset(found):
            hits.sort()
            regions: dict[str, tuple[int, int]] = {}
            width = len(row)
            for k, (col_i, field) in enumerate(hits):
                end = hits[k + 1][0] if k + 1 < len(hits) else width
                if field in regions:
                    raise SOIParseError(f"duplicate header {field!r} in SOI header row")
                regions[field] = (col_i, end)
            return row_i, regions
    raise SOIParseError(
        f"no SOI header row found; required {sorted(REQUIRED_HEADERS)}, first row seen: {grid[0][:20] if grid else []}"
    )


# A cell holding nothing but footnote markers: "(2)", "(2)(9)".  These must be
# excluded before any numeric read, otherwise a lone "(11)" beside an em-dash
# fair value parses as the negative number -11 (traps 3 and 4 colliding).
_PURE_FOOTNOTE = re.compile(r"^(?:\(\d{1,2}\))+$")


def region_tokens(row: list[str], span: tuple[int, int] | None) -> list[str]:
    if span is None:
        return []
    start, end = span
    return [t for t in row[start:end] if t and t != "$"]


def region_value(row: list[str], span: tuple[int, int] | None) -> str:
    """The single meaningful token in a region, footnote-only cells discarded.

    A region normally holds at most one value plus decoration ("$", a footnote
    marker cell).  The first token that actually parses as a number wins; if
    none does, the first non-footnote token is returned so that an em-dash
    (meaning zero) still reaches parse_number.
    """
    tokens = [t for t in region_tokens(row, span) if not _PURE_FOOTNOTE.match(t)]
    if not tokens:
        return ""
    for tok in tokens:
        if _NUMLIKE.search(tok) and parse_number(tok) is not None:
            return tok
    return tokens[0]


def region_text(row: list[str], span: tuple[int, int] | None) -> str:
    tokens = region_tokens(row, span)
    return " ".join(tokens).strip()


def region_footnotes(row: list[str], span: tuple[int, int] | None) -> list[int]:
    out: list[int] = []
    for tok in region_tokens(row, span):
        # A bare "(2)(9)" cell, or markers glued onto a number.
        if re.fullmatch(r"(?:\(\d{1,2}\))+", tok) or _FOOTNOTE_GLUED.search(tok):
            out.extend(footnote_numbers(tok))
    return out


_FOOTNOTE_GLUED = re.compile(r"(?<=\d)\(\d{1,2}\)")


# --------------------------------------------------------------------------
# main parse
# --------------------------------------------------------------------------


def parse_fragments(root, table_indices: list[int], scale: str,
                    non_accrual_footnote: int | None) -> pd.DataFrame:
    tables = root.xpath("//table")
    records: list[dict] = []

    industry: str | None = None
    borrower: str | None = None
    n_spacer = 0
    n_heading = 0
    n_subtotal = 0
    n_inherited = 0
    n_principal_from_desc = 0
    n_maturity_from_desc = 0

    for frag_pos, t_idx in enumerate(table_indices):
        grid = table_grid(tables[t_idx])
        header_i, regions = find_header_row(grid)
        for row_i, row in enumerate(grid):
            if row_i <= header_i:
                continue

            company_raw = region_text(row, regions.get("company"))
            investment_raw = region_text(row, regions.get("investment"))
            cost_cell = region_value(row, regions.get("cost"))
            fv_cell = region_value(row, regions.get("fair_value"))
            principal_cell = region_value(row, regions.get("principal"))
            has_money = any(parse_number(c) is not None for c in (cost_cell, fv_cell))
            any_text = any(t for t in row if t.strip())

            # --- spacer row (trap 9) -------------------------------------
            if not any_text:
                n_spacer += 1
                continue

            # --- repeated header on a continuation page -------------------
            if clean_name(investment_raw).lower() in {"investment", "type of investment"}:
                continue

            # --- section heading: a label and nothing else ----------------
            if company_raw and not investment_raw and not has_money:
                label = clean_name(company_raw)
                if label and not _TOTAL_LABEL.match(label):
                    industry = label
                    borrower = None
                    n_heading += 1
                    continue

            # --- subtotal / total rows (trap 1, trap 6) -------------------
            is_subtotal = False
            subtotal_reason = ""
            if has_money and not investment_raw:
                is_subtotal = True
                subtotal_reason = "money without an investment description"
            elif company_raw and _TOTAL_LABEL.match(clean_name(company_raw)):
                is_subtotal = True
                subtotal_reason = "leading label starts with Total"

            if not is_subtotal and not investment_raw:
                # text but no investment and no money: a stray note line
                continue

            # --- borrower carry-forward (trap 9) --------------------------
            if company_raw:
                borrower = clean_name(company_raw)
            elif not is_subtotal:
                n_inherited += 1

            if is_subtotal:
                n_subtotal += 1

            coupon = region_text(row, regions.get("coupon"))
            reference = region_text(row, regions.get("reference"))
            spread = region_value(row, regions.get("spread"))
            business = region_text(row, regions.get("business_description"))

            footnotes = sorted(
                set(
                    region_footnotes(row, regions.get("fair_value"))
                    + region_footnotes(row, regions.get("cost"))
                    + region_footnotes(row, regions.get("principal"))
                    + region_footnotes(row, regions.get("pct_of_net_assets"))
                    + region_footnotes(row, regions.get("shares_units"))
                )
            )
            is_non_accrual = bool(
                non_accrual_footnote is not None and non_accrual_footnote in footnotes
            )

            # Principal and maturity: prefer the filing's own columns. When the
            # SOI has no such column - common in older layouts, where both are
            # printed inside the investment description as "($1.5 par due
            # 5/2022)" - fall back to the description. The column always wins
            # where one exists, so this never overrides a reported cell.
            maturity = parse_soi_date(region_value(row, regions.get("maturity_date")))
            principal = parse_money(principal_cell, scale)
            if principal is None:
                par = parse_par_from_description(investment_raw)
                if par is not None:
                    principal = par * scale_factor(scale)
                    n_principal_from_desc += 1
            if maturity is None:
                maturity = parse_due_from_description(investment_raw)
                if maturity is not None:
                    n_maturity_from_desc += 1
            # An undrawn revolver states no par at all. That is handled in
            # stage 06, not here, because it must apply to debt rows only and
            # the investment type is not known until the vocabulary has run.
            records.append(
                {
                    "fragment_pos": frag_pos,
                    "table_index": t_idx,
                    "row_index": row_i,
                    "is_subtotal_row": is_subtotal,
                    "subtotal_reason": subtotal_reason,
                    "borrower": borrower if not is_subtotal else "",
                    "industry": industry or "",
                    "business_description": business,
                    "investment_type_raw": strip_footnotes(investment_raw),
                    "coupon_raw": coupon,
                    "reference_raw": reference,
                    "spread_raw": spread,
                    "reference_rate": parse_reference_rate(reference, coupon),
                    "spread_bps": (parse_spread_bps(spread)
                                   if parse_spread_bps(spread) is not None
                                   else parse_combined_spread_bps(coupon)),
                    "all_in_rate_pct": parse_all_in_rate_pct(coupon),
                    "pik_rate_pct": parse_pik_rate_pct(coupon),
                    "maturity_date": maturity.isoformat() if maturity else "",
                    "shares_units": parse_number(region_value(row, regions.get("shares_units"))),
                    "principal_amount": principal,
                    "cost": parse_money(cost_cell, scale),
                    "fair_value": parse_money(fv_cell, scale),
                    "pct_of_net_assets": parse_number(
                        region_value(row, regions.get("pct_of_net_assets"))
                    ),
                    "footnotes": ";".join(str(f) for f in footnotes),
                    "is_non_accrual": is_non_accrual,
                    "source_scale": scale,
                }
            )

    df = pd.DataFrame.from_records(records)
    log.info(
        "soi: %d fragments -> %d rows (%d positions, %d subtotal/total); "
        "%d spacer rows, %d section headings, %d rows with an inherited borrower",
        len(table_indices), len(df), int((~df["is_subtotal_row"]).sum()), n_subtotal,
        n_spacer, n_heading, n_inherited,
    )
    if n_principal_from_desc or n_maturity_from_desc:
        log.info("soi: no principal/maturity column for some rows; read from the "
                 "investment description instead (%d principal, %d maturity)",
                 n_principal_from_desc, n_maturity_from_desc)

    positions = df[~df["is_subtotal_row"]]
    blank_borrower = int((positions["borrower"].fillna("") == "").sum())
    if blank_borrower:
        raise SOIParseError(f"{blank_borrower} position rows have no borrower after carry-forward")
    n_na = int(positions["is_non_accrual"].sum())
    log.info("soi: %d positions flagged non-accrual by footnote (%s)", n_na, non_accrual_footnote)
    return df


def main() -> int:
    manifest = json.loads((INTERIM / "manifest.json").read_text())
    extract = json.loads((INTERIM / "extract.json").read_text())
    root = load_document(manifest["doc_path"])
    df = parse_fragments(
        root,
        extract["soi_current_indices"],
        extract["soi_scale"],
        extract.get("non_accrual_footnote"),
    )
    df.to_csv(OUT_PATH, index=False)

    total_row = df[df["is_subtotal_row"] & df["subtotal_reason"].eq("leading label starts with Total")]
    pos_sum = df.loc[~df["is_subtotal_row"], "fair_value"].sum()
    log.info("soi: sum(position fair_value) = %.1f USD", pos_sum)
    if len(total_row):
        reported = total_row["fair_value"].iloc[-1]
        if reported:
            log.info(
                "soi: reported 'Total Investments' row = %.1f USD, delta %.1f USD (%.6f%%)",
                reported, pos_sum - reported, 100.0 * (pos_sum - reported) / reported,
            )
    log.info("soi: wrote %s", OUT_PATH.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
