#!/usr/bin/env bash
# Fetch the ARCC 10-Q for the quarter ended 2026-06-30 from SEC EDGAR.
#
# EDGAR ground rules: declare a real User-Agent with contact details, and stay
# under 10 requests/second. This script makes 7 requests with a pause between
# them, so it is nowhere near the limit.
#
# To point this at a different BDC or quarter, change CIK and ACCESSION. Find
# them in https://data.sec.gov/submissions/CIK<10-digit-cik>.json
set -euo pipefail

UA="Yale MAM BootCamp"
CIK=1287750                      # Ares Capital Corp
ACCESSION=000162828026050307     # 10-Q filed 2026-07-29, period 2026-06-30
STEM=arcc-20260630

BASE="https://www.sec.gov/Archives/edgar/data/${CIK}/${ACCESSION}"
RAW="$(dirname "$0")/../data/raw"
mkdir -p "$RAW"

# The primary document is the inline-XBRL 10-Q itself. The _htm.xml instance is
# SEC's extraction of every tagged fact from it -- same numbers, far easier to
# read. The linkbases supply statement membership, ordering and labels.
FILES=(
  "${STEM}.htm"          # primary document, 24 MB
  "${STEM}_htm.xml"      # XBRL instance, 14 MB
  "${STEM}_pre.xml"      # presentation linkbase
  "${STEM}_lab.xml"      # label linkbase
  "${STEM}.xsd"          # schema, maps role URIs to statement titles
  "FilingSummary.xml"    # index of the SEC-rendered statement pages
)

for f in "${FILES[@]}"; do
  if [[ -s "$RAW/$f" ]]; then
    echo "cached  $f"
    continue
  fi
  echo "fetch   $f"
  curl -sS --fail -H "User-Agent: $UA" "$BASE/$f" -o "$RAW/$f"
  sleep 0.3
done

ls -lh "$RAW"
