"""
Parse Ares Capital Corp (ARCC) 10-Q for the quarter ended 2026-06-30 into two
analysis-ready tables.

Inputs -- data/raw/ (fetched by download.sh):
  arcc-20260630_htm.xml    SEC-extracted XBRL instance (all facts + contexts)
  arcc-20260630_pre.xml    presentation linkbase (statement membership + ordering)
  arcc-20260630_lab.xml    label linkbase (human-readable line-item names)
  arcc-20260630.xsd        schema (role URI -> statement title)
  arcc-20260630.htm        inline-XBRL primary document (source of untagged SOI text)

Outputs -- output/:
  financial_statements.csv     one row per (statement, line item, period, dimension)
  schedule_of_investments.csv  one row per (holding, balance-sheet date)

Two design decisions worth knowing before you edit this:

1. Numbers come from the XBRL instance, never from scraped HTML text. The rendered
   R files drop the XBRL element names and re-scale everything to millions, which
   silently corrupts per-share lines (NAV/share becomes 19,350,000). Instance facts
   carry their own unit and decimals, so no scaling guesswork is needed.

2. The schedule of investments joins XBRL facts to HTML rows on *context id*, not
   on row position. ARCC's ix tags spill across <tr> boundaries in ~80 places, so
   position-based assignment mis-labels those holdings.
"""

import csv
import re
from collections import defaultdict
from pathlib import Path

import lxml.html as LH
from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)

XBRLI = "{http://www.xbrl.org/2003/instance}"
XBRLDI = "{http://xbrl.org/2006/xbrldi}"
LINK = "{http://www.xbrl.org/2003/linkbase}"
XLINK = "{http://www.w3.org/1999/xlink}"

TICKER = "ARCC"
CIK = "0001287750"
ACCESSION = "0001628280-26-050307"
FORM = "10-Q"
PERIOD = "2026-06-30"

# Statement roles to emit as Table 1. The two SCHEDULE OF INVESTMENTS roles are
# excluded on purpose -- they are 3,800 holdings deep and become Table 2.
WANTED_STATEMENTS = {
    "0000002": "Consolidated Balance Sheets",
    "0000004": "Consolidated Statements of Operations",
    "0000006": "Consolidated Statements of Stockholders' Equity",
    "0000008": "Consolidated Statements of Cash Flows",
}


def clean(s):
    return re.sub(r"[\s ]+", " ", s or "").strip()


# --------------------------------------------------------------------------
# XBRL instance
# --------------------------------------------------------------------------

class Instance:
    """Facts and contexts from the SEC-extracted instance document."""

    def __init__(self, path):
        root = etree.parse(str(path)).getroot()
        self.prefix = {v: k for k, v in root.nsmap.items() if k}

        self.contexts = {}          # id -> dict(start, end, instant, dims, typed)
        self.investments = {}       # id -> (identifier, instant)  SOI holdings only
        for ctx in root.findall(XBRLI + "context"):
            cid = ctx.get("id")
            per = ctx.find(XBRLI + "period")
            instant = per.findtext(XBRLI + "instant")
            dims = {m.get("dimension"): m.text for m in ctx.iter(XBRLDI + "explicitMember")}
            typed = {}
            for tm in ctx.iter(XBRLDI + "typedMember"):
                child = list(tm)
                typed[tm.get("dimension")] = clean(child[0].text) if child else ""
            self.contexts[cid] = {
                "start": per.findtext(XBRLI + "startDate"),
                "end": per.findtext(XBRLI + "endDate"),
                "instant": instant,
                "dims": dims,
                "typed": typed,
            }
            ident = typed.get("us-gaap:InvestmentIdentifierAxis")
            if ident and instant:
                self.investments[cid] = (ident, instant)

        self.units = {}
        for u in root.findall(XBRLI + "unit"):
            ms = [m.text for m in u.iter(XBRLI + "measure")]
            self.units[u.get("id")] = "/".join(m.split(":")[-1] for m in ms)

        self.facts = defaultdict(list)          # "us-gaap:Assets" -> [fact, ...]
        self.by_context = defaultdict(dict)     # context id -> {localname: text}
        for el in root:
            cref = el.get("contextRef")
            if cref is None:
                continue
            qn = etree.QName(el)
            name = f"{self.prefix.get(qn.namespace, qn.namespace)}:{qn.localname}"
            rec = {"name": name, "context": cref, "unit": self.units.get(el.get("unitRef"), ""),
                   "decimals": el.get("decimals", ""), "sign": el.get("sign", ""),
                   "text": clean(el.text)}
            self.facts[name].append(rec)
            self.by_context[cref][qn.localname] = rec["text"]

    def value(self, cid, localname):
        v = self.by_context.get(cid, {}).get(localname)
        if v in (None, ""):
            return None
        try:
            return float(v)
        except ValueError:
            return None


# --------------------------------------------------------------------------
# Table 1 -- financial statements from the presentation + label linkbases
# --------------------------------------------------------------------------

def statement_roles():
    """roleURI -> (statement number, title) for the roles we want."""
    root = etree.parse(str(RAW / "arcc-20260630.xsd")).getroot()
    roles = {}
    for rt in root.iter():
        if etree.QName(rt).localname != "roleType":
            continue
        definition = rt.findtext(LINK + "definition") or ""
        m = re.match(r"^(\d+) - Statement - (.+)$", definition)
        if m and m.group(1) in WANTED_STATEMENTS:
            roles[rt.get("roleURI")] = (m.group(1), WANTED_STATEMENTS[m.group(1)])
    return roles


def load_labels():
    """(element, label role) -> text, for every element in the label linkbase."""
    root = etree.parse(str(RAW / "arcc-20260630_lab.xml")).getroot()
    labels = {}
    for link in root.iter(LINK + "labelLink"):
        loc = {l.get(XLINK + "label"): href_to_name(l.get(XLINK + "href"))
               for l in link.iter(LINK + "loc")}
        lab = defaultdict(dict)
        for l in link.iter(LINK + "label"):
            lab[l.get(XLINK + "label")][l.get(XLINK + "role")] = clean(l.text)
        for arc in link.iter(LINK + "labelArc"):
            element = loc.get(arc.get(XLINK + "from"))
            for role, text in lab.get(arc.get(XLINK + "to"), {}).items():
                labels[(element, role)] = text
    return labels


def href_to_name(href):
    """'arcc-20260630.xsd#us-gaap_Assets' -> 'us-gaap:Assets'."""
    frag = (href or "").split("#")[-1]
    return frag.replace("_", ":", 1)


STD_LABEL = "http://www.xbrl.org/2003/role/label"


def presentation_order(roles):
    """[(statement_no, title, order, element, preferred_label_role), ...]"""
    root = etree.parse(str(RAW / "arcc-20260630_pre.xml")).getroot()
    out = []
    for link in root.iter(LINK + "presentationLink"):
        role = link.get(XLINK + "role")
        if role not in roles:
            continue
        num, title = roles[role]
        loc = {l.get(XLINK + "label"): href_to_name(l.get(XLINK + "href"))
               for l in link.iter(LINK + "loc")}
        for i, arc in enumerate(link.iter(LINK + "presentationArc")):
            child = loc.get(arc.get(XLINK + "to"))
            parent = loc.get(arc.get(XLINK + "from"))
            if not child:
                continue
            try:
                order = float(arc.get("order") or i)
            except ValueError:
                order = float(i)
            out.append((num, title, order, i, child, parent,
                        arc.get("preferredLabel") or STD_LABEL))
    return out


def describe_dims(ctx):
    """Render a context's dimensions as 'Axis=Member; Axis=Member' (or '')."""
    parts = [f"{k.split(':')[-1]}={v.split(':')[-1]}" for k, v in sorted(ctx["dims"].items())]
    parts += [f"{k.split(':')[-1]}={v}" for k, v in sorted(ctx["typed"].items())]
    return "; ".join(parts)


def build_financial_statements(inst):
    roles = statement_roles()
    labels = load_labels()
    rows = []
    seen = set()
    for num, title, order, seq, element, parent, pref in presentation_order(roles):
        label = (labels.get((element, pref)) or labels.get((element, STD_LABEL)) or element)
        for fact in inst.facts.get(element, []):
            ctx = inst.contexts[fact["context"]]
            if "us-gaap:InvestmentIdentifierAxis" in ctx["typed"]:
                continue  # a single holding, not a statement line -- that is Table 2
            key = (title, element, fact["context"])
            if key in seen:
                continue
            seen.add(key)
            try:
                value = float(fact["text"])
            except ValueError:
                continue  # non-numeric fact (text block, date); not a statement line
            if fact["sign"] == "-":
                value = -value
            rows.append({
                "ticker": TICKER, "cik": CIK, "accession": ACCESSION, "form": FORM,
                "statement": title,
                "statement_no": num,
                "line_order": f"{num}.{seq:04d}",
                "line_item": label,
                "xbrl_tag": element,
                "parent_tag": parent or "",
                "period_start": ctx["start"] or "",
                "period_end": ctx["end"] or ctx["instant"] or "",
                "period_type": "duration" if ctx["start"] else "instant",
                "dimensions": describe_dims(ctx),
                "is_consolidated_total": not (ctx["dims"] or ctx["typed"]),
                "value": value,
                "unit": fact["unit"],
                "decimals": fact["decimals"],
                "context_id": fact["context"],
            })
    rows.sort(key=lambda r: (r["statement_no"], r["line_order"], r["period_end"], r["dimensions"]))
    return rows


# --------------------------------------------------------------------------
# Table 2 -- schedule of investments
# --------------------------------------------------------------------------

REF_RATE_RE = re.compile(r"\b(SOFR|EURIBOR|SONIA|CDOR|BBSY|TIBOR|LIBOR|Prime|Base Rate)\b", re.I)
FOOTNOTE_SUFFIX_RE = re.compile(r"\s*(\(\d+\))+\s*$")
FOOTNOTE_ONLY_RE = re.compile(r"^(\(\d+\))+$")
MMYYYY_RE = re.compile(r"^\d{1,2}/\d{4}$")

# Header cell text -> output column. ARCC lays every schedule row out on the same
# fixed-width colspan grid, so once the header row is located the column offsets
# are exact; no positional guessing and no dependence on which cells are blank.
COLUMNS = {
    "Company": "issuer",
    "Business Description": "business_description",
    "Investment": "investment_type",
    "Coupon": "coupon_text",
    "Reference": "reference_rate_reset",
    "Spread": "spread_text",
    "Acquisition Date": "acquisition_date",
    "Maturity Date": "maturity_date",
    "Shares/Units": "shares_units_text",
    "Principal": "principal_text",
    "Amortized Cost": "amortized_cost_text",
    "Fair Value": "fair_value_text",
    # "% of Net Assets" is printed only on industry subtotals, never per holding,
    # and unfunded commitments are disclosed in a separate note keyed by issuer
    # rather than by holding, so neither becomes a column here.
}
HEADER_SIGNATURE = ("Amortized Cost", "% of Net Assets", "Company")


def grid(tr):
    """Expand one <tr> into {column offset: text}, honouring colspan."""
    out, offset = {}, 0
    for cell in tr.xpath("./td | ./th"):
        text = clean(cell.text_content())
        if text:
            out[offset] = text
        offset += int(cell.get("colspan") or 1)
    return out


def header_map(table):
    """{column offset: output field} for a schedule page, or None if not one."""
    for tr in table.xpath(".//tr"):
        g = grid(tr)
        joined = " ".join(g.values())
        if all(s in joined for s in HEADER_SIGNATURE):
            return {off: COLUMNS[key]
                    for off, text in g.items()
                    for key in [FOOTNOTE_SUFFIX_RE.sub("", text)] if key in COLUMNS}
    return None


def pct(v):
    """XBRL states rates as decimals (0.0865); the filing prints 8.65%."""
    return None if v is None else round(v * 100, 6)


def to_float(text):
    t = (text or "").replace("$", "").replace(",", "").replace("%", "").strip()
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").strip()
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def affiliation_of(footnotes):
    """The schedule does not tag affiliation per holding; it flags it with a footnote
    on the *company* name, which therefore has to be carried down the issuer's block
    along with the name itself. Legend in the filing: (4) 'Affiliated Person' -- owns
    >=5% of voting securities; (5) 'Affiliated Person' and 'Control' -- owns >25%.
    These map one-to-one onto the three investment lines on the face of the balance
    sheet, which is what the affiliation tie-out checks."""
    if "(5)" in footnotes:
        return "Controlled affiliate"
    if "(4)" in footnotes:
        return "Non-controlled affiliate"
    return "Non-controlled/non-affiliate"


def build_schedule_of_investments(inst):
    doc = LH.parse(str(RAW / "arcc-20260630.htm"), LH.HTMLParser(huge_tree=True)).getroot()

    rows = []
    issuer = issuer_footnotes = business_description = industry = ""
    seen = set()
    # The schedule is broken across ~130 page-level tables, each repeating the
    # header. Walking tables (not raw <tr>) keeps us out of the affiliated-
    # investments note, which restates ~39 positions already in the schedule and
    # would double-count 5.1bn of fair value if picked up by tag alone.
    for table in doc.xpath("//table"):
        cols = header_map(table)
        if cols is None:
            continue
        for tr in table.xpath(".//tr"):
            g = grid(tr)
            f = {field: g.get(off, "") for off, field in cols.items()}

            if f["issuer"]:
                bare = FOOTNOTE_SUFFIX_RE.sub("", f["issuer"])
                if len(g) == 1:
                    # A row with the company column filled and nothing else in it is
                    # an industry heading, not a holding. 25 such labels, no false
                    # positives: every real issuer row also carries its first
                    # investment on the same line.
                    industry = bare
                    continue
                if bare != "Company":
                    issuer = bare  # carries down until the next issuer block
                    m = FOOTNOTE_SUFFIX_RE.search(f["issuer"])
                    issuer_footnotes = m.group(0).strip() if m else ""
                    business_description = f["business_description"]

            fv = [e for e in tr.xpath(".//*[starts-with(name(),'ix:')]")
                  if (e.get("name") or "").startswith("us-gaap:InvestmentOwnedAtFairValue")
                  and e.get("contextref") in inst.investments]
            if not fv:
                continue  # subtotal, spacer, or repeated header
            cid = fv[0].get("contextref")
            if cid in seen:
                continue
            seen.add(cid)
            identifier, instant = inst.investments[cid]

            reset = f["reference_rate_reset"]
            ref = REF_RATE_RE.search(reset)
            footnotes = next((v for v in g.values() if FOOTNOTE_ONLY_RE.match(v)), "")
            rows.append({
                "ticker": TICKER, "cik": CIK, "accession": ACCESSION, "form": FORM,
                "as_of_date": instant,
                "affiliation": affiliation_of(issuer_footnotes),
                "industry": industry,
                "issuer": issuer,
                "issuer_footnotes": issuer_footnotes,
                "business_description": business_description,
                "investment_type": FOOTNOTE_SUFFIX_RE.sub("", f["investment_type"]),
                "coupon_text": f["coupon_text"],
                "interest_rate_pct": pct(inst.value(cid, "InvestmentInterestRate")),
                "pik_rate_pct": pct(inst.value(cid, "InvestmentInterestRatePaidInKind")),
                "reference_rate": ref.group(0).upper() if ref else "",
                "reference_rate_reset": reset,
                "spread_pct": pct(inst.value(cid, "InvestmentBasisSpreadVariableRate")),
                "acquisition_date": f["acquisition_date"] if MMYYYY_RE.match(f["acquisition_date"]) else "",
                "maturity_date": f["maturity_date"] if MMYYYY_RE.match(f["maturity_date"]) else "",
                "shares_units": inst.value(cid, "InvestmentOwnedBalanceShares"),
                "principal_usd": inst.value(cid, "InvestmentOwnedBalancePrincipalAmount"),
                "amortized_cost_usd": inst.value(cid, "InvestmentOwnedAtCost"),
                "fair_value_usd": inst.value(cid, "InvestmentOwnedAtFairValue"),
                # Footnote markers sit in an unlabelled trailing cell, e.g. "(2)(9)".
                "footnotes": footnotes,
                "investment_identifier": identifier,
                "context_id": cid,
            })
    rows.sort(key=lambda r: (r["as_of_date"], r["industry"], r["issuer"], r["investment_type"]))
    return rows


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------

def tie_out(stmts, soi):
    """The schedule of investments must foot to the balance sheet. This is the
    only check that proves the SOI parse is complete rather than merely plausible."""
    # The balance sheet is tagged decimals="-6" (rounded to whole millions) while the
    # schedule is stated to 0.1mn, so an exact match is not achievable. Half a million
    # is the largest difference rounding alone can produce.
    TOL = 500_000

    bs = {}
    for r in stmts:
        if r["statement"] == "Consolidated Balance Sheets" and r["is_consolidated_total"]:
            bs[(r["xbrl_tag"], r["period_end"])] = r["value"]

    print("\nTIE-OUT: schedule of investments vs. balance sheet")
    print(f"  {'date':<12}{'n':>6}{'SOI cost':>16}{'SOI fair value':>18}"
          f"{'BS fair value':>18}{'diff':>12}  status")
    ok = True
    for date in ("2026-06-30", "2025-12-31"):
        sub = [r for r in soi if r["as_of_date"] == date]
        cost = sum(r["amortized_cost_usd"] or 0 for r in sub)
        fv = sum(r["fair_value_usd"] or 0 for r in sub)
        ref = bs.get(("us-gaap:InvestmentOwnedAtFairValue", date))
        diff = fv - ref if ref is not None else float("nan")
        good = ref is not None and abs(diff) <= TOL
        ok &= good
        print(f"  {date:<12}{len(sub):>6}{cost/1e6:>15,.1f}M{fv/1e6:>17,.1f}M"
              f"{ref/1e6:>17,.1f}M{diff/1e6:>+11,.1f}M  {'OK' if good else 'MISMATCH'}")

    # Second, independent check: the footnote-derived affiliation split must
    # reproduce the three investment lines on the face of the balance sheet.
    buckets = {
        "Non-controlled/non-affiliate": "us-gaap:InvestmentAffiliatedIssuerNoncontrolledNonaffiliatedMember",
        "Non-controlled affiliate": "us-gaap:InvestmentAffiliatedIssuerNoncontrolledMember",
        "Controlled affiliate": "us-gaap:InvestmentAffiliatedIssuerControlledMember",
    }
    dim_bs = {}
    for r in stmts:
        if r["statement"] == "Consolidated Balance Sheets" and \
                r["xbrl_tag"] == "us-gaap:InvestmentOwnedAtFairValue" and r["dimensions"]:
            dim_bs[(r["dimensions"].split("=")[-1], r["period_end"])] = r["value"]
    print("\n  affiliation split (footnotes 4/5) vs. balance sheet")
    for date in ("2026-06-30", "2025-12-31"):
        for label, member in buckets.items():
            fv = sum(r["fair_value_usd"] or 0 for r in soi
                     if r["as_of_date"] == date and r["affiliation"] == label)
            ref = dim_bs.get((member.split(":")[-1], date))
            if ref is None:
                continue
            good = abs(fv - ref) <= TOL
            ok &= good
            print(f"    {date}  {label:<30}{fv/1e6:>12,.1f}M vs {ref/1e6:>10,.1f}M"
                  f"  {'OK' if good else 'MISMATCH'}")

    # Balance sheet must itself balance.
    for date in ("2026-06-30", "2025-12-31"):
        a = bs.get(("us-gaap:Assets", date))
        le = bs.get(("us-gaap:LiabilitiesAndStockholdersEquity", date))
        if a and le:
            good = abs(a - le) < 1
            ok &= good
            print(f"  {date}  assets {a/1e6:,.1f}M vs liabilities+equity {le/1e6:,.1f}M"
                  f"  {'OK' if good else 'MISMATCH'}")
    return ok


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"  {path.relative_to(ROOT)}  {len(rows):,} rows x {len(rows[0])} cols")


def main():
    inst = Instance(RAW / "arcc-20260630_htm.xml")
    print(f"instance: {len(inst.contexts):,} contexts, "
          f"{sum(len(v) for v in inst.facts.values()):,} facts, "
          f"{len(inst.investments):,} holding contexts")

    stmts = build_financial_statements(inst)
    soi = build_schedule_of_investments(inst)

    print("\noutputs")
    write_csv(OUT / "financial_statements.csv", stmts)
    write_csv(OUT / "schedule_of_investments.csv", soi)

    if not tie_out(stmts, soi):
        raise SystemExit("tie-out failed -- do not use these tables")


if __name__ == "__main__":
    main()
