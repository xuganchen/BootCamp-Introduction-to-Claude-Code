"""Resolve ticker -> CIK and pick the target filing.

Plan v1 section 1: CIK is looked up at runtime from company_tickers.json,
never hardcoded. Target filing is the most recent 10-Q, falling back to the
most recent 10-K when that is the later period end.
"""

from __future__ import annotations

import argparse

from bdc_09_utils import INTERIM, fetch_json, log, parse_date, write_json

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SUBMISSIONS_PAGE_URL = "https://data.sec.gov/submissions/{name}"

PERIODIC_FORMS = ("10-Q", "10-K")


def resolve_cik(ticker: str) -> tuple[int, str]:
    data = fetch_json(TICKERS_URL, subdir="meta")
    for row in data.values():
        if row["ticker"].upper() == ticker.upper():
            return int(row["cik_str"]), row["title"]
    raise SystemExit(f"ticker {ticker} not found in company_tickers.json")


def filing_history(cik: int) -> tuple[list[dict], dict]:
    """Every 10-Q/10-K the filer has on EDGAR, newest period end first.

    The submissions JSON caps `filings.recent` at 1000 entries and pages the
    remainder into `filings.files`. A long-lived filer's early years therefore
    live in those extra pages: for ARCC, `recent` reaches back only to a
    2013-03-31 period end while the filer has reported since 2004. Anything
    that walks `recent` alone silently sees a truncated history, which is the
    kind of gap that looks like a complete backfill.
    """
    subs = fetch_json(SUBMISSIONS_URL.format(cik=cik), subdir="meta")
    blocks = [subs["filings"]["recent"]]
    for page in subs["filings"].get("files") or []:
        blocks.append(fetch_json(SUBMISSIONS_PAGE_URL.format(name=page["name"]), subdir="meta"))

    rows: list[dict] = []
    for block in blocks:
        for i, form_type in enumerate(block["form"]):
            if form_type not in PERIODIC_FORMS:
                continue
            rows.append(
                {
                    "form_type": form_type,
                    "accession": block["accessionNumber"][i],
                    "period_end": block["reportDate"][i],
                    "filing_date": block["filingDate"][i],
                    "primary_doc": block["primaryDocument"][i],
                }
            )
    rows.sort(key=lambda r: (r["period_end"], r["filing_date"]), reverse=True)
    meta = {
        "cik": cik,
        "bdc_name": subs["name"],
        "fiscal_year_end": subs.get("fiscalYearEnd"),
        "n_pages": len(blocks),
    }
    return rows, meta


def filing_url_fields(row: dict, cik: int) -> dict:
    """Attach the archive URLs and the parsed period end to a history row."""
    acc_nodash = row["accession"].replace("-", "")
    row["cik"] = cik
    row["base_url"] = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}"
    row["doc_url"] = f"{row['base_url']}/{row['primary_doc']}"
    row["period_end_date"] = str(parse_date(row["period_end"]))
    return row


def pick_filing(cik: int, period_end: str | None = None, form: str | None = None) -> dict:
    """Pick the target filing for `cik`.

    Default (no selectors): the most recent 10-Q or 10-K by period end - the
    behaviour every earlier run used.

    `period_end` ("YYYY-MM-DD") selects that period exactly. It is a *selector*,
    not an inference: a period end that the filer never reported fails with the
    list of periods that exist, rather than falling back to the nearest one.
    This is what makes any quarter reproducible - back-filling a panel, or
    re-running a period after a parser change - without hardcoding an accession.

    `form` restricts to one form type ("10-Q" / "10-K"), for the case where a
    filer reports the same period end on both.
    """
    rows, meta = filing_history(cik)
    if not rows:
        raise SystemExit(f"no 10-K/10-Q found for CIK {cik}")

    if form:
        rows = [r for r in rows if r["form_type"] == form.upper()]
        if not rows:
            raise SystemExit(f"no {form.upper()} found for CIK {cik}")
    if period_end:
        matches = [r for r in rows if r["period_end"] == period_end]
        if not matches:
            available = [f"{r['form_type']} {r['period_end']}" for r in rows[:12]]
            raise SystemExit(
                f"no filing with period_end {period_end} for CIK {cik}; "
                f"most recent available: {available}"
            )
        if len(matches) > 1:
            raise SystemExit(
                f"{len(matches)} filings share period_end {period_end} "
                f"({[(m['form_type'], m['accession']) for m in matches]}); "
                "disambiguate with --form"
            )
        rows = matches

    chosen = filing_url_fields(rows[0], cik)
    chosen["bdc_name"] = meta["bdc_name"]
    chosen["fiscal_year_end"] = meta["fiscal_year_end"]  # 'MMDD'
    return chosen


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default="ARCC")
    ap.add_argument("--period-end", default=None,
                    help="target period end as YYYY-MM-DD; default is the most recent filing")
    ap.add_argument("--form", default=None, choices=["10-Q", "10-K"],
                    help="restrict to one form type when a period end appears on both")
    args = ap.parse_args(argv)

    cik, title = resolve_cik(args.ticker)
    log.info("resolved %s -> CIK %d (%s)", args.ticker, cik, title)
    target = pick_filing(cik, period_end=args.period_end, form=args.form)
    target["ticker"] = args.ticker.upper()
    log.info("target %(form_type)s period_end=%(period_end)s filed=%(filing_date)s", target)
    write_json(INTERIM / "target_filing.json", target)
    return target


if __name__ == "__main__":
    main()
