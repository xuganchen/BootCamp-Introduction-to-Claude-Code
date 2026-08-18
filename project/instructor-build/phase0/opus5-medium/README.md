# ARCC 10-Q, parsed

Source filing: Ares Capital Corporation (ARCC, CIK 0001287750), Form 10-Q for
the quarter ended **2026-06-30**, filed 2026-07-29, accession
`0001628280-26-050307`.
<https://www.sec.gov/Archives/edgar/data/1287750/000162828026050307/arcc-20260630.htm>

ARCC is the largest publicly traded BDC by total assets ($30,498.0M at
2026-06-30).

## Run

```bash
python3 code/parse_arcc_10q.py    # writes both tables to output/
python3 code/verify_tieout.py     # reconciles them against the filing
```

Re-downloading requires an EDGAR-compliant User-Agent header and no more than
10 requests/second:

```bash
curl --compressed -H "User-Agent: Name Org email" <url>
```

## Table 1 — `output/financial_statements.csv`

472 rows, long format, one row per line item per column. Covers the balance
sheets, statements of operations, stockholders' equity, and cash flows.

| Column | Meaning |
|---|---|
| `statement` | which of the four statements |
| `row_order` | position within the statement; with `column`, a unique key |
| `section` | heading the row sits under (`LIABILITIES`, `INVESTMENT INCOME:`) |
| `column` | period or equity component, e.g. `3 Months Ended \| Jun. 30, 2026` |
| `line_item` | label as printed |
| `indent_px` | indentation, which encodes the subtotal hierarchy |
| `value` | numeric value |
| `value_type` | `number` or `percent` |
| `unit` | `millions`, except per-share and share-count rows |
| `is_primary_block` | `False` for the R-file's repeated dimensional breakdowns |

**Filter to `is_primary_block == True` before summing.** The SEC renderings
print the primary statement and then repeat line items inside disaggregations
(investment income by type, investments by affiliation tier). Without the
filter, `Total investment income` appears four times per period.

## Table 2 — `output/schedule_of_investments.csv`

2,848 rows: one row per position per balance sheet date (1,439 at 2026-06-30,
1,409 at 2025-12-31), across 24 industries.

| Column | Source | Meaning |
|---|---|---|
| `as_of` | XBRL context | `2026-06-30` or `2025-12-31` |
| `industry` | SOI section header | GICS-style industry banner |
| `issuer`, `instrument` | `InvestmentIdentifierAxis` | filer-tagged "Issuer \| Instrument" |
| `business_description` | SOI row | e.g. "Provider of technology solutions" |
| `coupon_pct`, `spread_pct`, `pik_pct` | XBRL | all-in coupon, spread over the reference rate, PIK component |
| `reference_rate` | SOI row | e.g. `SOFR (Q)`; null for fixed-rate and equity |
| `acquisition_date`, `maturity_date` | SOI row | `MM/YYYY`; maturity null for equity |
| `shares_units`, `principal` | XBRL | position size; which one applies depends on instrument |
| `amortized_cost`, `fair_value` | XBRL | in dollars, not millions |
| `affiliation` | company footnotes 4 and 5 | Investment Company Act tier |
| `rate_scale_corrected` | derived | `True` where a mis-tagged rate was rescaled (3 rows) |
| `footnotes`, `company_footnotes` | SOI row | footnote numbers as printed |

Rates are in percent (9.41 means 9.41%), converted from the XBRL decimals.
Three coupon facts carry `scale="0"` or no scale where their siblings carry
`scale="-2"`, so the fact asserts 948% while the filing prints "9.48 %".
Those are rescaled and flagged. Taken at face value they move the
principal-weighted coupon from 9.41% to 27.36%, which is the kind of error
that survives a plausible-looking output.

Null rates at 2026-06-30 are structural, not gaps: `coupon_pct` and
`maturity_date` are absent on equity positions (35% and 26%), `shares_units`
on debt (74%), `principal` on equity (28%).

### Why the numbers come from XBRL

Every value is read from the inline-XBRL fact, which carries its own `scale`
and `sign`, rather than from the rendered text. That removes the two errors
this filing invites: guessing the "$ in millions" multiplier, and reading an
em dash as missing when the filer tagged it `ixt:fixed-zero`, a real zero
(268 positions).

Position identity comes from `us-gaap:InvestmentIdentifierAxis`, a typed
dimension. Attributes the filer did not tag (industry, business description,
reference rate, dates, footnotes) are recovered from the HTML row that
physically contains each fact, with industry and issuer forward-filled down
the section as printed.

## Verification

`verify_tieout.py` reconciles the position detail to the balance sheet:

- Total investments at fair value ties **exactly** at both dates
  (29,349.3M and 29,484.8M).
- Amortized cost sums to 29,674.6M at 2026-06-30, matching the SOI total.
- Industry subtotals match the filing's own rollup (Software and Services
  6,451.2M, Financial Services 3,935.8M, and so on).
- Every position has both a cost and a fair value.

Two residuals are breaks in the filing, not in the parse; both are documented
in `verify_tieout.py` and neither affects the total. The larger one:
DIEM-VII (QP), LLC is carried in the SOI at cost 11.6M / fair value 11.1M,
while the affiliate note reports its ending fair value as 11.6M with no
unrealized loss, so the balance sheet's controlled-affiliate line and the SOI
detail disagree by 0.5M.

## Layout

```
data/raw/    filing as downloaded (arcc-20260630.htm is 24 MB; do not commit)
code/        parse_arcc_10q.py, verify_tieout.py
output/      the two tables
```
