"""
Parse an ARCC (Ares Capital Corp) 10-Q from SEC EDGAR into two structured tables.

Inputs (already downloaded under data/raw/):
  arcc-20260630.htm  primary inline-XBRL document (24 MB)
  R2/R4/R6/R8.htm    SEC "Financial Report" renderings of the statements

Outputs (output/):
  financial_statements.csv  tidy long table: statement, line item, period, value
  schedule_of_investments.csv  one row per position per balance-sheet date

Method
------
Numbers come from the inline-XBRL facts, not from scraped text: every fact
carries its own scale and sign, so no guessing about "$ in millions".
Position identity comes from the typed dimension us-gaap:InvestmentIdentifierAxis,
which the filer tags as "Issuer | Instrument".  Attributes that are NOT tagged
(industry, business description, reference rate, dates) are recovered from the
HTML row that physically contains the fact.
"""

import re
import os
import json
from collections import defaultdict

import pandas as pd
from lxml import etree

RAW = "data/raw"
OUT = "output"

# ---------------------------------------------------------------- XBRL helpers

def parse_ix_value(el):
    """Value of an ix:nonFraction element, applying @scale and @sign."""
    # an em dash rendered with format ixt:fixed-zero is a tagged zero, not a gap
    if (el.get("format") or "").endswith("fixed-zero"):
        return 0.0
    txt = "".join(el.itertext())
    txt = txt.replace(",", "").replace("\xa0", " ").strip()
    txt = txt.replace("(", "").replace(")", "").replace("$", "").replace("%", "").strip()
    if txt in ("", "-", "—", "–"):
        return None
    try:
        v = float(txt)
    except ValueError:
        return None
    scale = el.get("scale")
    if scale:
        v *= 10 ** int(scale)
    if el.get("sign") == "-":
        v = -v
    return v


def load_doc(path):
    parser = etree.HTMLParser(huge_tree=True)
    return etree.parse(path, parser).getroot()


def build_contexts(root):
    """contextRef -> dict(period, instant, investment identifier, explicit members)."""
    ctx = {}
    for c in root.iter():
        if not (isinstance(c.tag, str) and c.tag.endswith("context")):
            continue
        rec = {"instant": None, "start": None, "end": None,
               "investment": None, "members": {}}
        for el in c.iter():
            tag = el.tag if isinstance(el.tag, str) else ""
            if tag.endswith("instant"):
                rec["instant"] = el.text
            elif tag.endswith("startdate"):
                rec["start"] = el.text
            elif tag.endswith("enddate"):
                rec["end"] = el.text
            elif tag.endswith("typedmember"):
                if el.get("dimension") == "us-gaap:InvestmentIdentifierAxis":
                    rec["investment"] = " ".join("".join(el.itertext()).split())
            elif tag.endswith("explicitmember"):
                rec["members"][el.get("dimension")] = el.text
        ctx[c.get("id")] = rec
    return ctx


# ------------------------------------------------- table 1: financial statements

STATEMENTS = {
    "R2.htm": "Consolidated Balance Sheets",
    "R4.htm": "Consolidated Statements of Operations",
    "R6.htm": "Consolidated Statements of Stockholders Equity",
    "R8.htm": "Consolidated Statements of Cash Flows",
}


def clean_num(text):
    t = text.replace(",", "").replace("$", "").replace("\xa0", " ").strip()
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").strip()
    pct = t.endswith("%")
    t = t.rstrip("%").strip()
    if t in ("", "-", "—", "–"):
        return None, None
    try:
        v = float(t)
    except ValueError:
        return None, None
    if neg:
        v = -v
    return v, ("percent" if pct else "number")


def statement_columns(rows):
    """Column labels for an R-file.

    The header is one or two rows.  When there are two, the top row spans
    groups ("3 Months Ended") and the bottom row gives the dates, so a column
    label is the pair.  When there is only one, its cells already name the
    columns and their colspans are layout padding (a value cell plus its
    footnote marker), not extra columns."""
    header_rows = []
    for tr in rows:
        cells = [c for c in tr if c.tag in ("th", "td")]
        if not any(c.tag == "th" for c in cells):
            break
        header_rows.append(cells)

    title = " ".join(header_rows[0][0].itertext()).strip()
    top = [" ".join(c.itertext()).strip() for c in header_rows[0][1:]]

    if len(header_rows) < 2:
        return title, top

    spans = []
    for c, label in zip(header_rows[0][1:], top):
        spans.extend([label] * int(c.get("colspan") or 1))
    bottom = [" ".join(c.itertext()).strip() for c in header_rows[1]]
    return title, [f"{g} | {d}" if g else d
                   for g, d in zip(spans, bottom)]


def parse_statement(path, statement):
    """SEC R-files are one clean table: a label column plus one column per
    period.  Cell classes mark the roles (pl = label, nump/num = value,
    fn = footnote marker, text = an empty cell holding a column's place)."""
    root = load_doc(path)
    rows = root.find(".//table").findall(".//tr")
    title, columns = statement_columns(rows)

    # unit hint lives in the title, e.g. "USD ($) $ in Millions"
    unit = "millions" if "in Millions" in title else (
        "thousands" if "in Thousands" in title else "units")

    out = []
    section = None
    order = 0
    for tr in rows:
        tds = tr.findall("./td")
        if not tds or "pl" not in (tds[0].get("class") or "").split():
            continue
        label = " ".join(tds[0].itertext()).strip()
        if not label:
            continue
        style = tds[0].get("style") or ""
        m = re.search(r"padding-left:\s*(\d+)px", style)
        indent = int(m.group(1)) if m else 0

        # Keep blank ("text") cells: they hold a column's position.  Dropping
        # them shifts every later value into the wrong column on sparse rows.
        cells = [td for td in tds[1:]
                 if "fn" not in (td.get("class") or "").split()]
        if not any({"nump", "num"} & set((td.get("class") or "").split())
                   for td in cells):
            # A label with no values is a heading.  These matter: the R-file
            # stacks the primary statement and then its dimensional
            # breakdowns, so "Total investment income" appears several times
            # and only the heading above it says which block it belongs to.
            section = label
            continue

        order += 1
        for i, td in enumerate(cells):
            if i >= len(columns):
                break
            v, kind = clean_num(" ".join(td.itertext()))
            if v is None:
                continue
            out.append({
                "statement": statement,
                "row_order": order,
                "section": section,
                "column": columns[i],
                "line_item": label,
                "indent_px": indent,
                "value": v,
                "value_type": kind,
                "unit": unit if kind == "number" else "percent",
            })
    return out, title


# --------------------------------------------- table 2: schedule of investments

SOI_CONCEPTS = {
    "InvestmentOwnedAtCost": "amortized_cost",
    "InvestmentOwnedAtFairValue": "fair_value",
    "InvestmentOwnedBalancePrincipalAmount": "principal",
    "InvestmentOwnedBalanceShares": "shares_units",
    "InvestmentInterestRate": "coupon_pct",
    "InvestmentBasisSpreadVariableRate": "spread_pct",
    "InvestmentInterestRatePaidInKind": "pik_pct",
    "InvestmentOwnedBalancePercentOfShares": "pct_of_shares_held",
}

DATE_RE = re.compile(r"^\d{2}/\d{4}$")
REF_RE = re.compile(r"\b(SOFR|LIBOR|EURIBOR|SONIA|BBSY|CDOR|NIBOR|STIBOR|"
                    r"TIBOR|BKBM|Base Rate|Prime)\b", re.I)
FOOTNOTE_RE = re.compile(r"^(\(\d+\))+$")


# Investment Company Act tiers, per the SOI footnote legend in this filing:
#   (4) "Affiliated Person"  -> 5% or more of voting securities
#   (5) "Affiliated Person" and "Control" -> more than 25% of voting securities
# Everything else is non-controlled / non-affiliate.  These three tiers are the
# same split the balance sheet reports, which makes them a second tie-out.
AFFILIATION = {5: "Controlled affiliate", 4: "Non-controlled affiliate"}


def affiliation(company_footnotes):
    for fn in (5, 4):
        if fn in company_footnotes:
            return AFFILIATION[fn]
    return "Non-controlled/non-affiliate"


def row_cells(tr):
    """Cell text with runs of whitespace collapsed — the filing's HTML carries
    line-break artifacts inside labels ("Commercial and  Professional Services")."""
    return [" ".join("".join(td.itertext()).replace("\xa0", " ").split())
            for td in tr.findall("./td")]


def strip_footnotes(s):
    return re.sub(r"\s*\((?:\d+)\)", "", s).strip()


def is_industry_header(cells):
    """An industry banner is a single non-empty leading cell and nothing else."""
    nz = [i for i, c in enumerate(cells) if c]
    return len(nz) == 1 and nz[0] == 0 and len(cells[0]) > 2


def parse_soi(root, ctx):
    tables = list(root.iter("table"))

    records = {}
    industry = None
    company = None
    company_fns = ()
    portfolio_co_desc = None

    for tbl in tables:
        facts = [f for f in tbl.iter("ix:nonfraction")
                 if ctx.get(f.get("contextref"), {}).get("investment")]
        if not facts:
            continue
        names = {f.get("name").split(":")[1] for f in facts}
        if "InvestmentOwnedAtCost" not in names:
            continue  # commitments note / affiliate rollforward, not the SOI
        if "InterestIncomeOperating" in names:
            continue

        # facts indexed by the <tr> that contains them
        by_row = defaultdict(list)
        for f in facts:
            tr = f.getparent()
            while tr is not None and tr.tag != "tr":
                tr = tr.getparent()
            if tr is not None:
                by_row[tr].append(f)

        for tr in tbl.findall(".//tr"):
            cells = row_cells(tr)
            if tr not in by_row:
                if is_industry_header(cells):
                    industry = strip_footnotes(cells[0])
                    company = None
                continue

            # ---- forward-filled text columns
            if cells and cells[0]:
                company = strip_footnotes(cells[0])
                # footnotes printed against the company name carry the
                # Investment Company Act affiliation tier (see AFFILIATION)
                company_fns = tuple(int(x) for x in
                                    re.findall(r"\((\d+)\)", cells[0]))
                portfolio_co_desc = None
            nonempty = [c for c in cells if c]

            desc = None
            for c in nonempty[1:6]:
                if (len(c) > 15 and not DATE_RE.match(c) and "%" not in c
                        and not FOOTNOTE_RE.match(c)):
                    desc = c
                    break
            if desc:
                portfolio_co_desc = desc

            ref = None
            m = REF_RE.search(" | ".join(nonempty))
            if m:
                for c in nonempty:
                    if REF_RE.search(c) and len(c) < 30:
                        ref = c
                        break

            dates = [c for c in cells if DATE_RE.match(c)]
            acq = dates[0] if len(dates) >= 1 else None
            mat = dates[1] if len(dates) >= 2 else None

            fns = sorted({int(x) for c in cells if FOOTNOTE_RE.match(c)
                          for x in re.findall(r"\((\d+)\)", c)})

            # ---- one record per (position, balance sheet date)
            for f in by_row[tr]:
                c = ctx[f.get("contextref")]
                ident = c["investment"]
                key = (ident, c["instant"])
                rec = records.setdefault(key, {
                    "investment_id": ident,
                    "as_of": c["instant"],
                    "issuer": ident.split("|")[0].strip(),
                    "instrument": ident.split("|", 1)[1].strip() if "|" in ident else None,
                    "industry": industry,
                    "company_as_printed": company,
                    "business_description": portfolio_co_desc,
                    "reference_rate": ref,
                    "acquisition_date": acq,
                    "maturity_date": mat,
                    "footnotes": ";".join(str(x) for x in fns) or None,
                    "company_footnotes": ";".join(str(x) for x in company_fns) or None,
                    "affiliation": affiliation(company_fns),
                })
                # the same position can be tagged across several stacked rows;
                # keep the first non-null value seen for each text column
                for k, v in (("industry", industry),
                             ("company_as_printed", company),
                             ("business_description", portfolio_co_desc),
                             ("reference_rate", ref),
                             ("acquisition_date", acq),
                             ("maturity_date", mat)):
                    if rec.get(k) is None and v is not None:
                        rec[k] = v
                col = SOI_CONCEPTS.get(f.get("name").split(":")[1])
                if col:
                    rec[col] = parse_ix_value(f)

    df = pd.DataFrame(list(records.values()))

    # XBRL tags rates as decimals (0.1038); the filing prints percent (10.38 %).
    #
    # A handful of rate facts in this filing carry scale="0" or no scale where
    # the sibling facts carry scale="-2", so the fact asserts 9.48 (948%) while
    # the filing prints "9.48 %".  That is a tagging error on ARCC's side, not
    # a parsing question: no loan in this book pays over 100%.  Rates above
    # 1.0 before conversion are rescaled and flagged rather than silently kept
    # or silently dropped.
    RATE_COLS = ("coupon_pct", "spread_pct", "pik_pct")
    df["rate_scale_corrected"] = False
    for col in RATE_COLS:
        if col not in df:
            continue
        bad = df[col] > 1.0
        df.loc[bad, col] = df.loc[bad, col] / 100.0
        df["rate_scale_corrected"] |= bad.fillna(False)
    for col in RATE_COLS + ("pct_of_shares_held",):
        if col in df:
            df[col] = df[col] * 100
    return df


# ------------------------------------------------------------------------ main

def main():
    os.makedirs(OUT, exist_ok=True)

    # ---- table 1
    fin = []
    titles = {}
    for fname, stmt in STATEMENTS.items():
        rows, title = parse_statement(os.path.join(RAW, fname), stmt)
        fin.extend(rows)
        titles[stmt] = title
    fin_df = pd.DataFrame(fin)

    # The R-files print the primary statement first, then repeat line items
    # inside dimensional breakdowns (investment income by type, and so on).
    # Summing without this flag double counts.
    seen = set()
    primary = []
    for st, col, li in zip(fin_df.statement, fin_df.column, fin_df.line_item):
        key = (st, col, li)
        primary.append(key not in seen)
        seen.add(key)
    fin_df["is_primary_block"] = primary
    fin_df.to_csv(os.path.join(OUT, "financial_statements.csv"), index=False)

    # ---- table 2
    root = load_doc(os.path.join(RAW, "arcc-20260630.htm"))
    ctx = build_contexts(root)
    soi = parse_soi(root, ctx)

    order = ["as_of", "industry", "issuer", "instrument", "business_description",
             "coupon_pct", "reference_rate", "spread_pct", "pik_pct",
             "acquisition_date", "maturity_date", "shares_units", "principal",
             "amortized_cost", "fair_value", "pct_of_shares_held",
             "affiliation", "rate_scale_corrected", "footnotes", "company_footnotes",
             "company_as_printed", "investment_id"]
    soi = soi.reindex(columns=[c for c in order if c in soi.columns])
    soi = soi.sort_values(["as_of", "industry", "issuer", "instrument"],
                          na_position="last")
    soi.to_csv(os.path.join(OUT, "schedule_of_investments.csv"), index=False)

    print(json.dumps({
        "financial_statements_rows": len(fin_df),
        "statements": sorted(fin_df["statement"].unique().tolist()),
        "soi_rows": len(soi),
        "soi_dates": sorted(soi["as_of"].dropna().unique().tolist()),
        "titles": titles,
    }, indent=2))


if __name__ == "__main__":
    main()
