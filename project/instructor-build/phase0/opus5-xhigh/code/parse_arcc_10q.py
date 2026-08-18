"""
Parse Ares Capital Corp (ARCC) Form 10-Q into two structural tables.

Source
------
CIK 0001287750, accession 0001628280-26-050307, period 2026-06-30, filed 2026-07-29.
Primary document: arcc-20260630.htm (~25 MB Inline XBRL).

Why this approach
-----------------
The filing is Inline XBRL: every reported number is wrapped in an <ix:nonFraction>
element carrying (a) the us-gaap/arcc element name, (b) a contextRef that resolves to
a reporting date, and (c) a `scale` exponent and optional `sign`. So numeric fields are
identified by XBRL element name (position-independent, immune to column drift), while
text-only fields (company name, business description, dates, footnote markers) are
identified by position on the table's column grid, which is derived from each page's
own header row rather than hardcoded.

Two outputs
-----------
1. financial_statements.csv - tidy long table, one row per reported fact, covering the
   Consolidated Balance Sheets, Statements of Operations, Statements of Stockholders'
   Equity and Statements of Cash Flows.
2. soi_investments.csv - one row per investment line in the Consolidated Schedule of
   Investments, for both dates presented (2026-06-30 and 2025-12-31).

Plus supporting artifacts: soi_subtotals.csv, soi_footnote_legend.csv, tieout_report.txt.

Units
-----
Dollar fields are in whole USD (the filing prints millions; `scale=6` is applied).
Rate fields are in percentage points (coupon_pct = 8.65 means 8.65%), i.e. the number
as printed, NOT the XBRL decimal (0.0865).
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict

import pandas as pd
from lxml import etree

# --------------------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------------------

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(HERE, "data", "raw", "arcc-20260630.htm")
OUT = os.path.join(HERE, "output")

FILING = {
    "cik": "0001287750",
    "ticker": "ARCC",
    "bdc_name": "Ares Capital Corporation",
    "form": "10-Q",
    "accession": "0001628280-26-050307",
    "period_of_report": "2026-06-30",
    "filed_date": "2026-07-29",
}

# Table indices in document order, established by inspection. A bare index would silently
# read the wrong table if this were pointed at a different filing, so each one carries a
# phrase that must appear in it; check_statement_tables() enforces that before parsing.
STATEMENT_TABLES = {
    7: ("balance_sheet", "Total investments at fair value"),
    8: ("statement_of_operations", "NET INVESTMENT INCOME"),
    169: ("statement_of_stockholders_equity", "Capital in"),
    170: ("statement_of_cash_flows", "OPERATING ACTIVITIES"),
}
# The Schedule of Investments is printed one HTML table per page, twice: once as of
# 2026-06-30 and once as of 2025-12-31. These ranges are re-derived at runtime.
SOI_HEADER_KEYS = ("Company", "Amortized Cost", "Fair Value")

# XBRL element name -> column in the investment panel. Authoritative for numeric fields.
SOI_FACT_MAP = {
    "us-gaap:InvestmentInterestRate": "coupon_pct",
    "us-gaap:InvestmentInterestRatePaidInKind": "pik_pct",
    "us-gaap:InvestmentBasisSpreadVariableRate": "spread_pct",
    "us-gaap:InvestmentOwnedBalanceShares": "shares_units",
    "us-gaap:InvestmentOwnedBalancePrincipalAmount": "principal_usd",
    "us-gaap:InvestmentOwnedAtCost": "amortized_cost_usd",
    "us-gaap:InvestmentOwnedAtFairValue": "fair_value_usd",
    "us-gaap:InvestmentOwnedPercentOfNetAssets": "pct_of_net_assets",
    "arcc:InvestmentOwnedBalancePercentOfShares": "pct_of_shares_owned",
}
# Fields whose XBRL value is a decimal fraction but which we report in percentage points.
PERCENT_FIELDS = {"coupon_pct", "pik_pct", "spread_pct", "pct_of_net_assets",
                  "pct_of_shares_owned"}

# Header label (footnote markers stripped) -> column in the investment panel. Used only
# for text fields; numerics come from SOI_FACT_MAP above.
SOI_HEADER_MAP = {
    "Company": "portfolio_company",
    "Business Description": "business_description",
    "Investment": "investment_type",
    "Coupon": "coupon_text",
    "Reference": "reference_rate",
    "Spread": "spread_text",
    "Acquisition Date": "acquisition_date",
    "Maturity Date": "maturity_date",
    "Shares/Units": "shares_units_text",
    "Principal": "principal_text",
    "Amortized Cost": "amortized_cost_text",
    "Fair Value": "fair_value_text",
    "% of Net Assets": "pct_of_net_assets_text",
}

# Footnote markers carry the economically meaningful flags. Both SOI sections number
# their notes 1..18 identically; only the wording of the date-specific ones differs.
#
# Notes 1, 3, 7 and 18 are referenced from column headings rather than from individual
# rows, so they describe the column and produce no per-line flag. Notes 4, 5, 13, 14 and
# 15 are printed against the company name and therefore apply to every line of that
# company; the rest are printed against individual investment lines.
FOOTNOTE_FLAGS = {
    2: "is_pledged_as_collateral",
    4: "is_affiliated_person",       # Company owns >=5% of portfolio company voting securities
    5: "is_controlled",              # Affiliated Person AND control
    6: "is_non_qualifying_asset",    # not a qualifying asset under sec. 55(a)
    8: "is_non_accrual",
    9: "has_interest_rate_floor",
    10: "is_sdlp_certificate",
    11: "has_letters_of_credit_unfunded",
    12: "has_letters_of_credit_additional",
    # Note 16 is worded as an exception: everything EXCEPT the marked lines is valued
    # with unobservable (Level 3) inputs, so the marker means "not Level 3". Verified
    # against Note 8: the 34 marked lines total $661.1m at 2026-06-30 against $662m of
    # Level 1, Level 2 and NAV-measured investments.
    16: "fair_value_not_level_3",
    13: "has_unfunded_loan_commitment",
    14: "has_unfunded_equity_commitment",
    15: "has_sdlp_coinvest_commitment",
}

NBSP = " "
DASHES = {"—", "–", "-"}  # printed in place of a zero


# --------------------------------------------------------------------------------------
# Low-level helpers
# --------------------------------------------------------------------------------------

def localname(el) -> str:
    """Tag name without namespace prefix, lowercased ('ix:nonFraction' -> 'nonfraction')."""
    tag = el.tag if isinstance(el.tag, str) else ""
    return tag.split("}")[-1].split(":")[-1].lower()


def text_of(el) -> str:
    """Collapsed visible text of an element."""
    return " ".join("".join(el.itertext()).replace(NBSP, " ").split())


def parse_contexts(root) -> dict:
    """contextRef id -> {instant | start/end, dims: {axis: member}}."""
    contexts = {}
    for el in root.iter():
        if localname(el) != "context":
            continue
        ctx = {"instant": None, "start": None, "end": None, "dims": {}}
        for child in el.iter():
            name = localname(child)
            value = (child.text or "").strip()
            if name == "instant":
                ctx["instant"] = value
            elif name == "startdate":
                ctx["start"] = value
            elif name == "enddate":
                ctx["end"] = value
            elif name == "explicitmember":
                ctx["dims"][child.get("dimension")] = value
        contexts[el.get("id")] = ctx
    return contexts


NIL_ATTR = "{http://www.w3.org/2001/XMLSchema-instance}nil"


def _flatten(el, target, acc, span):
    """Concatenate an element's text, recording where `target`'s own text falls."""
    if el is target:
        span[0] = sum(len(s) for s in acc)
    if el.text:
        acc.append(el.text)
    for child in el:
        _flatten(child, target, acc, span)
    if el is target:
        span[1] = sum(len(s) for s in acc)
    if el.tail:
        acc.append(el.tail)


def is_negated_in_place(container, ix_el) -> bool:
    """
    True when the number is printed wrapped in parentheses.

    ARCC renders a negative as literal "(" and ")" text nodes flanking the
    <ix:nonFraction>, so the test has to look at the characters immediately around the
    element, not at the whole cell: a label cell such as "Total investments at fair value
    (amortized cost of $29,674.6 ...)" contains both parentheses and tagged numbers that
    are not negative.
    """
    acc, span = [], [None, None]
    _flatten(container, ix_el, acc, span)
    if span[0] is None:
        return False
    full = "".join(acc).replace(NBSP, " ")
    before = full[:span[0]].rstrip().rstrip("$").rstrip()
    after = full[span[1]:].lstrip().lstrip("%").lstrip()
    return before.endswith("(") and after.startswith(")")


def fact_value(ix_el, container):
    """
    Decode one <ix:nonFraction> into (displayed_value, xbrl_value, printed_value).

    displayed_value applies the `scale` exponent and takes its sign from the printed page
    (parentheses mean negative). This is what ties out to the statements.
    xbrl_value also applies `scale` but takes its sign from the `sign="-"` attribute, i.e.
    the element's own convention. The two differ wherever the presentation linkbase
    applies a negated weight, which is common in the cash flow reconciliation.
    printed_value is the number exactly as it appears on the page, with no scaling. It is
    the safe choice for the rate columns, because ARCC's tagging of them is not uniform:
    three of the 1,846 coupon facts (the ones sharing a cell with a PIK rate) carry
    scale="0" where every other rate carries scale="-2", so trusting `scale` there would
    report a 9.48% coupon as 948%.

    Returns (None, None, None) for nil facts and for anything that is not a number.
    """
    if ix_el.get(NIL_ATTR) == "true":
        return None, None, None

    raw = text_of(ix_el)
    if raw == "":
        return None, None, None
    if raw in DASHES:
        digits = 0.0
    else:
        cleaned = re.sub(r"[^\d.]", "", raw.replace(",", ""))
        if cleaned in ("", "."):
            return None, None, None
        digits = float(cleaned)

    negated = is_negated_in_place(container, ix_el)
    magnitude = digits * (10 ** int(ix_el.get("scale") or 0))
    xbrl_value = -magnitude if ix_el.get("sign") == "-" else magnitude
    displayed = -magnitude if negated else magnitude
    printed = -digits if negated else digits
    return displayed, xbrl_value, printed


def row_cells(row):
    """
    Return [(col_start, colspan, text, [ix elements], cell_element)] for one <tr>.

    col_start is the cumulative colspan offset, which gives a stable column grid even
    though the number of <td> elements per row varies with merged and spacer cells.
    """
    out, pos = [], 0
    for cell in row.xpath("./td|./th"):
        span = int(cell.get("colspan") or 1)
        facts = [d for d in cell.iter() if localname(d) == "nonfraction"]
        out.append((pos, span, text_of(cell), facts, cell))
        pos += span
    return out


def is_noise(text: str) -> bool:
    """Currency symbols, percent signs and stray punctuation printed in their own cell."""
    return text.strip() in {"", "$", "%", "(", ")", ":"}


# --------------------------------------------------------------------------------------
# Financial statements
# --------------------------------------------------------------------------------------

def check_statement_tables(tables):
    """Fail loudly if a hardcoded statement index no longer points at that statement."""
    problems = []
    for tindex, (statement, phrase) in STATEMENT_TABLES.items():
        if tindex >= len(tables):
            problems.append(f"table {tindex} ({statement}) does not exist")
        elif phrase not in text_of(tables[tindex]):
            problems.append(f"table {tindex} does not look like {statement}: "
                            f"expected to find {phrase!r}")
    if problems:
        raise SystemExit("statement tables have moved:\n  " + "\n  ".join(problems))


def parse_statements(tables, contexts) -> pd.DataFrame:
    """
    Tidy long table: one row per reported fact across the four primary statements.

    Line-item labels come from the leftmost text cell of each row (column 0 on the grid);
    the reporting period and any dimensional breakdown come from the fact's context.

    `section` is the most recent heading printed above the row ("EXPENSES:", "OPERATING
    ACTIVITIES:"). Statements do not close their sections, so a heading carries forward
    until the next one appears and some summary rows inherit the section above them; use
    it as a navigation aid, not as a strict grouping key.
    """
    records = []
    for tindex, (statement, _) in STATEMENT_TABLES.items():
        rows = tables[tindex].xpath(".//tr")
        current_section = None
        for order, row in enumerate(rows):
            cells = row_cells(row)
            # The label is the leftmost cell, whether or not it also carries tagged
            # numbers: "Total investments at fair value (amortized cost of $29,674.6 and
            # $29,249.9 ...)" tags the cost figures inside the label itself.
            label_cells = [c for c in cells if c[0] == 0 and c[2].strip()]
            label = label_cells[0][2] if label_cells else None

            facts = [(c, ix) for c in cells for ix in c[3]]
            if not facts:
                # A row with a label but no numbers is a section heading (e.g. "ASSETS",
                # "OPERATING ACTIVITIES:"). Carry it forward as context for later rows.
                if label and not is_noise(label):
                    current_section = label
                continue

            for cell, ix in facts:
                displayed, xbrl, _ = fact_value(ix, cell[4])
                if displayed is None:
                    continue
                ctx = contexts.get(ix.get("contextref"), {})
                records.append({
                    **FILING,
                    "statement": statement,
                    "row_order": order,
                    "section": current_section,
                    "line_item": label,
                    "xbrl_tag": ix.get("name"),
                    "context_id": ix.get("contextref"),
                    "period_type": "instant" if ctx.get("instant") else "duration",
                    "period_instant": ctx.get("instant"),
                    "period_start": ctx.get("start"),
                    "period_end": ctx.get("end"),
                    "dimensions": json.dumps(ctx.get("dims", {}), sort_keys=True),
                    "value_usd": displayed,
                    "value_usd_xbrl_signed": xbrl,
                    "scale": ix.get("scale"),
                    "decimals": ix.get("decimals"),
                })
    return pd.DataFrame.from_records(records)


# --------------------------------------------------------------------------------------
# Schedule of Investments
# --------------------------------------------------------------------------------------

def find_soi_tables(tables) -> list:
    """Indices of the page-tables that make up the Consolidated Schedule of Investments."""
    hits = []
    for i, table in enumerate(tables):
        head = " ".join(text_of(r) for r in table.xpath(".//tr")[:3])
        if all(key in head for key in SOI_HEADER_KEYS):
            hits.append(i)
    return hits


def soi_column_map(table) -> dict:
    """
    col_start -> field name, derived from this page's own header row.

    Footnote markers (e.g. "(2)(9)") are printed in an unlabelled column that sits
    between Fair Value and % of Net Assets, so it is added explicitly.
    """
    for row in table.xpath(".//tr")[:3]:
        cells = [c for c in row_cells(row) if c[2].strip()]
        labels = {re.sub(r"\s*\(\d+\)\s*$", "", c[2]).strip(): c[0] for c in cells}
        if "Company" in labels and "Fair Value" in labels:
            mapping = {pos: SOI_HEADER_MAP[lab] for lab, pos in labels.items()
                       if lab in SOI_HEADER_MAP}
            fair_value_pos = labels["Fair Value"]
            pct_pos = labels.get("% of Net Assets")
            for offset in range(fair_value_pos + 1, pct_pos if pct_pos else fair_value_pos + 7):
                mapping.setdefault(offset, "footnotes")
            return mapping
    return {}


def parse_footnote_legends(root) -> tuple:
    """
    The two printed footnote legends (one per SOI date), read from the body-level divs
    that follow each schedule. Both are numbered 1..18; only the wording of the
    date-specific notes differs. Returns (legend_dataframe, {number: text} for section 0).
    """
    body = root.find("body")
    blocks = []
    for i, child in enumerate(body):
        text = text_of(child)
        m = re.match(r"^\((\d+)\)\s*(.+)$", text)
        if m and len(text) < 1500:
            blocks.append((i, int(m.group(1)), m.group(2)))

    groups, current = [], []
    for item in blocks:
        if current and item[1] <= current[-1][1]:
            groups.append(current)
            current = []
        current.append(item)
    if current:
        groups.append(current)

    # The SOI legends are the two 18-item groups that define the non-accrual note.
    legends = [g for g in groups
               if len(g) >= 18 and any("non-accrual status" in t for _, _, t in g)]
    records = []
    for section, group in enumerate(legends):
        for _, number, text in group:
            records.append({
                "soi_section": section,
                "footnote_number": number,
                "flag": FOOTNOTE_FLAGS.get(number),
                "footnote_text": text,
            })
    return pd.DataFrame.from_records(records), legends


def parse_soi(tables, contexts, soi_indices) -> tuple:
    """
    Walk the SOI page-tables in document order and emit one record per investment line.

    Row types encountered, in the order they are tested:
      * header row              - repeated on every printed page; skipped
      * industry heading        - text in column 0 only, no numbers; sets current industry
      * grand total row         - labelled "Total Investments"; captured as a subtotal
      * investment line         - has an investment description; a blank company column
                                  means another tranche of the company above (forward-fill)
      * subtotal row            - numbers only, no description; issuer or industry rollup
    """
    investments, subtotals = [], []
    unmapped_tags = Counter()

    industry = None
    company = None
    business = None
    line_no = 0
    # Line ids of the company currently being printed. An issuer subtotal row applies to
    # the block of lines immediately above it, which is a far more reliable link than
    # matching the printed company name to the XBRL issuer member (the member spells
    # names inconsistently: "Ferrellgas" vs "Ferrelgas", digits prefixed with "A", and
    # co-borrowers listed in a different order).
    company_lines = []

    for tindex in soi_indices:
        table = tables[tindex]
        colmap = soi_column_map(table)
        if not colmap:
            continue

        # Reporting date for this page: the instant shared by its facts.
        instants = Counter()
        for row in table.xpath(".//tr"):
            for cell in row_cells(row):
                for ix in cell[3]:
                    inst = contexts.get(ix.get("contextref"), {}).get("instant")
                    if inst:
                        instants[inst] += 1
        page_instant = instants.most_common(1)[0][0] if instants else None

        for row in table.xpath(".//tr"):
            cells = [c for c in row_cells(row) if c[2].strip() or c[3]]
            if not cells:
                continue

            by_col = {}
            for pos, span, text, facts, el in cells:
                field = colmap.get(pos)
                by_col[pos] = {"field": field, "text": text, "facts": facts, "el": el}

            texts = {v["field"]: v["text"] for v in by_col.values()
                     if v["field"] and not is_noise(v["text"])}
            has_facts = any(v["facts"] for v in by_col.values())

            # 1. repeated column header
            if texts.get("portfolio_company", "").startswith("Company") and not has_facts:
                continue

            # 2. industry heading: a lone label with no numbers
            occupied = {v["field"] for v in by_col.values() if not is_noise(v["text"]) or v["facts"]}
            if occupied == {"portfolio_company"} and not has_facts:
                industry = texts["portfolio_company"]
                company = business = None
                company_lines = []
                continue

            # Collect numeric fields by XBRL element name (position-independent).
            values, ctx_ids = {}, []
            for v in by_col.values():
                for ix in v["facts"]:
                    name = ix.get("name")
                    field = SOI_FACT_MAP.get(name)
                    if field is None:
                        unmapped_tags[name] += 1
                        continue
                    displayed, _, printed = fact_value(ix, v["el"])
                    if displayed is None:
                        continue
                    # Rates are taken as printed (percentage points); dollar amounts are
                    # scaled out of the filing's millions into whole USD.
                    values[field] = printed if field in PERCENT_FIELDS else displayed
                    ctx_ids.append(ix.get("contextref"))

            ctx = contexts.get(ctx_ids[0], {}) if ctx_ids else {}
            instant = ctx.get("instant") or page_instant
            dims = ctx.get("dims", {})

            label = texts.get("portfolio_company")
            investment = texts.get("investment_type")

            # 3. grand total, and 4./5. subtotal rows (no investment description)
            if not investment:
                level = ("total" if label else
                         "issuer" if "us-gaap:InvestmentIssuerNameAxis" in dims else
                         "industry")
                subtotals.append({
                    **FILING,
                    "period_end": instant,
                    "level": level,
                    "label": label or (company if level == "issuer" else industry),
                    "for_company": company if level == "issuer" else None,
                    "covers_line_ids": (",".join(str(n) for n in company_lines)
                                        if level == "issuer" else None),
                    "industry": industry,
                    "dimensions": json.dumps(dims, sort_keys=True),
                    "amortized_cost_usd": values.get("amortized_cost_usd"),
                    "fair_value_usd": values.get("fair_value_usd"),
                    "pct_of_net_assets": values.get("pct_of_net_assets"),
                    "source_table": tindex,
                })
                continue

            # 6. investment line
            if label:
                # A company whose tranches straddle a page break has its name reprinted;
                # only a genuinely new name starts a new block.
                if label != company:
                    company_lines = []
                company, business = label, texts.get("business_description")

            footnotes = texts.get("footnotes", "")
            markers = {int(n) for n in re.findall(r"\((\d+)\)", footnotes)}
            # Footnote markers appended to the company name (e.g. "Foo Inc. (4)") describe
            # the portfolio company - notably affiliation - rather than this one tranche,
            # so they apply to every line of that company.
            trailing = re.search(r"((?:\(\d+\))+)\s*$", company or "")
            company_footnotes = trailing.group(1) if trailing else None
            company_markers = {int(n) for n in re.findall(r"\((\d+)\)", company_footnotes or "")}

            line_no += 1
            company_lines.append(line_no)
            record = {
                **FILING,
                "period_end": instant,
                "line_id": line_no,
                "industry": industry,
                "portfolio_company": re.sub(r"\s*(\(\d+\))+\s*$", "", company or "").strip(),
                "business_description": business,
                "investment_type": investment,
                "coupon_pct": values.get("coupon_pct"),
                "pik_pct": values.get("pik_pct"),
                "reference_rate": texts.get("reference_rate"),
                "spread_pct": values.get("spread_pct"),
                "acquisition_date": texts.get("acquisition_date"),
                "maturity_date": texts.get("maturity_date"),
                "shares_units": values.get("shares_units"),
                "principal_usd": values.get("principal_usd"),
                "amortized_cost_usd": values.get("amortized_cost_usd"),
                "fair_value_usd": values.get("fair_value_usd"),
                "pct_of_net_assets": values.get("pct_of_net_assets"),
                "pct_of_shares_owned": values.get("pct_of_shares_owned"),
                "footnotes": footnotes or None,
                "company_footnotes": company_footnotes,
                "source_table": tindex,
                "context_id": ctx_ids[0] if ctx_ids else None,
            }
            all_markers = markers | company_markers
            for number, flag in FOOTNOTE_FLAGS.items():
                record[flag] = number in all_markers
            # Note 3 ("investments without an interest rate are non-income producing") is
            # referenced from the Coupon column heading, so the condition has to be read
            # off the data rather than off a row marker.
            record["is_non_income_producing"] = (values.get("coupon_pct") is None
                                                 and values.get("pik_pct") is None)
            record["affiliation"] = ("controlled" if 5 in all_markers else
                                     "affiliated" if 4 in all_markers else
                                     "non_controlled_non_affiliated")
            investments.append(record)

    return (pd.DataFrame.from_records(investments),
            pd.DataFrame.from_records(subtotals),
            unmapped_tags)


# --------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------

def tie_out(inv: pd.DataFrame, sub: pd.DataFrame, stmt: pd.DataFrame) -> str:
    """
    Check the parsed schedule against numbers the filing prints for itself.

    Four independent checks per date:
      A. sum of the parsed investment lines   vs. the printed "Total Investments" row
      B. issuer subtotals + single-tranche lines vs. the printed "Total Investments" row
         (the filing prints an issuer subtotal only where a company has >1 tranche, so
          single-tranche companies have to be added back)
      C. printed "Total Investments"          vs. total investments at fair value and at
                                                  amortized cost on the balance sheet
      D. sum of the three affiliation buckets on the balance sheet vs. its own total,
         and the parsed lines split by footnote-derived affiliation vs. those buckets
    """
    def money(x):
        return f"{x:>18,.0f}"

    lines = ["ARCC Form 10-Q parse - tie-out report",
             f"{FILING['bdc_name']} | CIK {FILING['cik']} | accession {FILING['accession']}",
             "All figures in whole USD.",
             "=" * 78, ""]

    bs = stmt[stmt.statement == "balance_sheet"]

    def bs_lookup(tag, label_contains=None):
        rows = bs[bs.xbrl_tag == tag]
        if label_contains:
            rows = rows[rows.line_item.astype(str).str.contains(label_contains, regex=False)]
        return rows.set_index("period_instant")["value_usd"].to_dict()

    bs_total_fv = bs_lookup("us-gaap:InvestmentOwnedAtFairValue", "Total investments")
    bs_total_cost = bs_lookup("us-gaap:InvestmentOwnedAtCost", "Total investments")
    bs_buckets = bs[(bs.xbrl_tag == "us-gaap:InvestmentOwnedAtFairValue")
                    & (~bs.line_item.astype(str).str.contains("Total", regex=False))]

    affiliation_to_bucket = {
        "non_controlled_non_affiliated": "Non-controlled/non-affiliate company investments",
        "affiliated": "Non-controlled affiliate company investments",
        "controlled": "Controlled affiliate company investments",
    }

    for period in sorted(inv.period_end.dropna().unique()):
        i = inv[inv.period_end == period]
        s = sub[sub.period_end == period]
        total_row = s[s.level == "total"]
        printed_cost = total_row.amortized_cost_usd.sum()
        printed_fv = total_row.fair_value_usd.sum()

        # Link each issuer subtotal to the block of lines it sits under.
        issuers = s[s.level == "issuer"]
        by_line = i.set_index("line_id")
        covered, mismatches = set(), []
        for _, sr in issuers.iterrows():
            ids = [int(n) for n in str(sr.covers_line_ids).split(",") if n.strip().isdigit()]
            covered.update(ids)
            block = by_line.loc[[n for n in ids if n in by_line.index]]
            for field in ("amortized_cost_usd", "fair_value_usd"):
                if abs(block[field].sum() - (sr[field] or 0)) > 1:
                    mismatches.append((sr.label, field, block[field].sum(), sr[field]))
        uncovered = i[~i.line_id.isin(covered)]
        b_cost = issuers.amortized_cost_usd.sum() + uncovered.amortized_cost_usd.sum()
        b_fv = issuers.fair_value_usd.sum() + uncovered.fair_value_usd.sum()

        lines += [
            f"As of {period}",
            "-" * 78,
            f"  investment lines parsed              {len(i):>16,}",
            f"  distinct portfolio companies         {i.portfolio_company.nunique():>16,}",
            f"  issuer subtotal rows printed         {len(issuers):>16,}",
            f"  lines covered by an issuer subtotal  {len(covered):>16,}",
            f"  lines with no issuer subtotal        {len(uncovered):>16,}",
            "",
            "  A. sum of parsed lines vs printed Total Investments",
            f"       amortized cost, parsed   {money(i.amortized_cost_usd.sum())}",
            f"       amortized cost, printed  {money(printed_cost)}",
            f"       difference               {money(i.amortized_cost_usd.sum() - printed_cost)}",
            f"       fair value, parsed       {money(i.fair_value_usd.sum())}",
            f"       fair value, printed      {money(printed_fv)}",
            f"       difference               {money(i.fair_value_usd.sum() - printed_fv)}",
            "",
            "  B. every issuer subtotal vs the block of lines printed above it",
            f"       subtotals checked         {len(issuers):>18,}",
            f"       subtotals that disagree   {len(mismatches):>18,}",
            f"       amortized cost           {money(b_cost)}   diff {money(b_cost - printed_cost)}",
            f"       fair value               {money(b_fv)}   diff {money(b_fv - printed_fv)}",
            "",
        ]
        for label, field, got, want in mismatches[:10]:
            lines.append(f"       ! {label} {field}: {got:,.0f} vs {want:,.0f}")
        if mismatches:
            lines.append("")

        if period in bs_total_fv:
            lines += [
                "  C. schedule of investments vs consolidated balance sheet",
                f"       balance sheet, fair value{money(bs_total_fv[period])}",
                f"       SOI total, fair value    {money(printed_fv)}",
                f"       difference               {money(bs_total_fv[period] - printed_fv)}",
                f"       balance sheet, cost      {money(bs_total_cost.get(period, float('nan')))}",
                f"       SOI total, cost          {money(printed_cost)}",
                f"       difference               {money(bs_total_cost.get(period, float('nan')) - printed_cost)}",
                "",
            ]

        buckets = (bs_buckets[bs_buckets.period_instant == period]
                   .set_index("line_item")["value_usd"].to_dict())
        if buckets:
            lines.append("  D. affiliation split: parsed lines vs balance sheet buckets")
            parsed_by_aff = i.groupby("affiliation").fair_value_usd.sum().to_dict()
            for affiliation, bucket in affiliation_to_bucket.items():
                got = parsed_by_aff.get(affiliation, 0.0)
                want = buckets.get(bucket, float("nan"))
                lines.append(f"       {affiliation:<32}{money(got)} vs{money(want)}"
                             f"   diff {money(got - want)}")
            lines += [f"       {'sum of buckets':<32}{money(sum(buckets.values()))}", ""]

        lines.append("")

    # E. the schedule's own percentage-of-net-assets total against the balance sheet.
    equity = (stmt[stmt.xbrl_tag == "us-gaap:StockholdersEquity"]
              .set_index("period_instant")["value_usd"].to_dict())
    lines += ["Cross-statement checks", "-" * 78]
    for period in sorted(inv.period_end.dropna().unique()):
        total_row = sub[(sub.period_end == period) & (sub.level == "total")]
        printed_pct = total_row.pct_of_net_assets.sum()
        if period in equity and equity[period]:
            derived = total_row.fair_value_usd.sum() / equity[period] * 100
            lines.append(f"  {period}  total investments / stockholders' equity: "
                         f"{derived:6.2f}%  printed {printed_pct:6.2f}%")

    cash = (stmt[stmt.xbrl_tag.isin(["us-gaap:CashAndCashEquivalentsAtCarryingValue",
                                     "us-gaap:RestrictedCash"])
                 & (stmt.statement == "balance_sheet")]
            .groupby("period_instant")["value_usd"].sum().to_dict())
    change = stmt[stmt.line_item.astype(str).str.startswith("CHANGE IN CASH")]
    change = change[change.period_start == "2026-01-01"]["value_usd"]
    if len(cash) == 2 and len(change):
        moved = cash["2026-06-30"] - cash["2025-12-31"]
        lines.append(f"  cash + restricted cash movement: {moved:,.0f}  "
                     f"cash flow statement: {change.iloc[0]:,.0f}  "
                     f"diff {moved - change.iloc[0]:,.0f}")

    lines += ["", "Data quality", "-" * 78]
    for column, low, high in [("coupon_pct", 0, 40), ("pik_pct", 0, 40),
                              ("spread_pct", 0, 25), ("pct_of_shares_owned", 0, 100)]:
        series = inv[column].dropna()
        outliers = int(((series < low) | (series > high)).sum())
        lines.append(f"  {column:<22} n={len(series):>5}  "
                     f"min={series.min():>8.2f}  max={series.max():>8.2f}  "
                     f"outside [{low},{high}]: {outliers}")
    for column in ["portfolio_company", "investment_type", "industry",
                   "amortized_cost_usd", "fair_value_usd"]:
        lines.append(f"  {column:<22} missing: {int(inv[column].isna().sum())}")

    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------

def main():
    os.makedirs(OUT, exist_ok=True)
    parser = etree.HTMLParser(huge_tree=True)
    root = etree.parse(RAW, parser).getroot()
    tables = root.xpath("//table")
    contexts = parse_contexts(root)

    print(f"parsed {len(tables)} tables, {len(contexts)} XBRL contexts")

    check_statement_tables(tables)
    stmt = parse_statements(tables, contexts)
    stmt.to_csv(os.path.join(OUT, "financial_statements.csv"), index=False)
    print(f"financial_statements.csv  {len(stmt):,} facts, "
          f"{stmt.statement.nunique()} statements")

    soi_indices = find_soi_tables(tables)
    print(f"schedule of investments spans {len(soi_indices)} page-tables "
          f"({soi_indices[0]}-{soi_indices[-1]})")

    legend, _ = parse_footnote_legends(root)
    legend.to_csv(os.path.join(OUT, "soi_footnote_legend.csv"), index=False)

    inv, sub, unmapped = parse_soi(tables, contexts, soi_indices)
    inv.to_csv(os.path.join(OUT, "soi_investments.csv"), index=False)
    sub.to_csv(os.path.join(OUT, "soi_subtotals.csv"), index=False)
    print(f"soi_investments.csv       {len(inv):,} investment lines")
    print(f"soi_subtotals.csv         {len(sub):,} subtotal rows")
    if unmapped:
        print("unmapped XBRL tags inside the SOI:", dict(unmapped))

    report = tie_out(inv, sub, stmt)
    with open(os.path.join(OUT, "tieout_report.txt"), "w") as fh:
        fh.write(report)
    print()
    print(report)


if __name__ == "__main__":
    main()
