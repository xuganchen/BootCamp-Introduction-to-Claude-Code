"""Download the target filing and the XBRL companyfacts, with a run manifest.

Plan v1 step 1: filing on disk, cached, manifest recording URL, accession, SHA-256.
"""

from __future__ import annotations

import json

from bdc_09_utils import INTERIM, RAW, cache_name, fetch, log, sha256_file, write_json

FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"


def main() -> dict:
    target = json.loads((INTERIM / "target_filing.json").read_text())

    doc = fetch(target["doc_url"], subdir="filings")
    doc_path = RAW / "filings" / cache_name(target["doc_url"])
    log.info("filing %.1f MB", len(doc) / 1e6)

    facts_url = FACTS_URL.format(cik=target["cik"])
    fetch(facts_url, subdir="meta")
    facts_path = RAW / "meta" / cache_name(facts_url)

    manifest = {
        "ticker": target["ticker"],
        "cik": target["cik"],
        "bdc_name": target["bdc_name"],
        "form_type": target["form_type"],
        "accession": target["accession"],
        "period_end": target["period_end"],
        "filing_date": target["filing_date"],
        "fiscal_year_end": target["fiscal_year_end"],
        "doc_url": target["doc_url"],
        "doc_path": str(doc_path),
        "doc_bytes": len(doc),
        "doc_sha256": sha256_file(doc_path),
        "facts_url": facts_url,
        "facts_path": str(facts_path),
        "facts_sha256": sha256_file(facts_path),
    }
    write_json(INTERIM / "manifest.json", manifest)
    log.info("manifest written; doc sha256=%s", manifest["doc_sha256"][:16])
    return manifest


if __name__ == "__main__":
    main()
