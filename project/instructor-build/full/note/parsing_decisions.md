# Parsing decisions - stages 03 to 07

Filing parsed: ARCC (Ares Capital Corp), CIK 1287750, 10-Q, period end
2026-06-30, filed 2026-07-29, accession 0001628280-26-050307.
Primary document `arcc-20260630.htm`, 24,846,021 bytes, 275 `<table>` elements.

Everything below is a decision that a different reasonable parser could have
made differently. Where a decision could be wrong on another filer, that is
said explicitly rather than left implicit.

---

## 1. How tables are found (stage 03)

Nothing in a table's own markup says what it is. Every financial statement in
an EDGAR filing is preceded by a **banner** of loose text blocks: registrant
name, statement title, "As of <date>", a scale line, "(unaudited)". Stage 03
walks the document once in order, attaches the text blocks that appear between
the previous table and this one to this table, and classifies from the banner.

Guard added after a false positive: a statement title only counts when it is a
**standalone heading line** - at most 80 characters, and the regex match covers
at least 60% of the line. Without this, prose such as *"...is included in
'accounts payable and other liabilities' in the accompanying consolidated
balance sheets."* inside a footnote classified four unrelated tables as the
balance sheet, and stage 03 aborted with "found 5 balance sheets". The abort
was the correct behaviour; the fix was to tighten the title test, not to relax
the "exactly one" rule.

## 2. Colspan grid, not raw `<td>` counts

Physical cell counts per row vary (25, 27, 28, 31 within a single SOI
fragment) because "$", the number, and the footnote marker "(2)(9)" are each
their own `<td>`. Every table is expanded by `colspan` into a rectangular grid
(`bdc_03_extract.table_grid`). After expansion a header label sits at a fixed
column index, and each header defines a **region** running from its own index
to the next header's index. A value is then "the numeric token somewhere in
this region", which survives the dollar sign and footnote cells drifting
around inside it.

`rowspan` is deliberately **not** expanded. These filings do not use it for
numeric data, and honouring it would duplicate values downward.

## 3. Which Schedule of Investments (the biggest single risk)

The 10-Q contains **two complete Schedules of Investments**: tables 9-75 as of
2026-06-30 (67 fragments) and tables 90-154 as of 2025-12-31 (65 fragments).
They are visually and structurally identical. Summing both would have produced
roughly 2x the portfolio.

They are distinguished only by the "As of <date>" line in each fragment's own
banner. Stage 03 reads that line per fragment and keeps only fragments whose
date equals `periodOfReport`; 65 comparative fragments are dropped and the drop
is logged. If any fragment's banner had no parseable date, stage 03 fails
rather than assuming.

The comparative SOI is out of scope per plan section 8, so the investment panel
is current-period only.

## 4. Scale, resolved per table

Not assumed document-wide. Each banner declares its own scale and it is read
with `\(\s*(?:dollar amounts )?in (millions|thousands)\)`:

| Table | Banner scale line | Factor applied |
|---|---|---|
| Balance sheet (table 7) | `(in millions, except per share data)` | 1e6 |
| SOI, all 67 current fragments | `(dollar amounts in millions)` | 1e6 |

**ARCC reports in millions, not thousands.** All money in both panels is
plain USD dollars: 29,349.3 in the filing becomes 29,349,300,000.0.

`nav_per_share` is explicitly exempted from the scale factor - the banner says
"except per share data". Share **counts** are not exempt: the caption's "718"
means 718,000,000, confirmed against the inline XBRL tag on that number
(`us-gaap:CommonStockSharesOutstanding`, `scale="6"`).

Stage 03 fails if the current-period SOI fragments disagree with each other on
scale.

## 5. Balance sheet: both columns, one map (plan section 3.1, trap 11)

Header row of table 7 after colspan expansion:

```
col 3 -> "June 30, 2026"      region cols [3, 9)
col 9 -> "December 31, 2025"  region cols [9, 12)
```

The map is built **once**, asserted before any data row is read, and reused for
every row. Assertions, all fatal:

- exactly two dated columns (three or more -> abort, do not guess);
- the two header dates differ;
- one of them equals `periodOfReport` exactly;
- the other is strictly earlier.

`period_end_prior = 2025-12-31` is read **from the column header**. It is never
computed. `period_end_prior_kind` compares it against `fiscal_year_end = 1231`
from the submissions JSON, giving `prior_fiscal_year_end`. A non-fiscal-year-end
comparative is allowed but logged as a warning.

### Row label matching

| Field | Matched label |
|---|---|
| `total_investments_fv` | "Total investments at fair value (amortized cost of $29,675 and $29,250, respectively)" |
| `total_assets` | "Total assets" |
| `total_liabilities` | "Total liabilities" |
| `net_assets` | "Total stockholders' equity" |
| `nav_per_share` | "NET ASSET VALUE PER SHARE" |
| `total_debt_outstanding` | "Debt" |

`total_liabilities` uses an anchored exact match so that "Total liabilities and
stockholders' equity" (the cross-foot line, same value as total assets) cannot
capture it. Each field is taken from its **first** matching row in statement
order.

### Two fields that are not in a value cell

- **`shares_outstanding`** is printed inside the common-stock caption, not in a
  column: *"...1,000 common shares authorized; 718 common shares issued and
  outstanding"*. ARCC prints **one** figure, not the more common "718 and 717
  ... respectively", so the same 718,000,000 is assigned to both columns. The
  inline XBRL confirms this is correct here (the same value is tagged for both
  the `c-9` and `c-10` contexts), but on another filer or another quarter the
  two-figure form is what to expect, and the regex handles both.
- **Reported total amortized cost** is inside the total-investments caption,
  not a row of its own. It is parsed out to `total_investments_cost` /
  `_prior` in `balance_sheet.json` for tie-out check 14. It is **not** in the
  quarter panel, because plan section 3.1 does not list it and the panel is
  held to exactly the documented schema.

## 6. SOI row classification (trap 1)

Detected structurally, never by row index:

| Row shape | Treatment |
|---|---|
| no text at all | spacer, skipped (29 seen) |
| investment column reads "Investment" | repeated header on a continuation page, skipped (67, one per fragment) |
| label in the company column and nothing else | industry section heading; sets `industry`, clears the carried borrower (24 seen) |
| money present but **no investment description** | subtotal - flagged `is_subtotal_row=True` (420 seen) |
| leading label starts with "Total"/"Subtotal" | total row - flagged `is_subtotal_row=True` |
| anything else with an investment description | position row (1,439) |

The 420 excluded rows are 419 per-borrower subtotals plus the single grand
"Total Investments" row. They **are** written to `data/interim/soi_rows.csv`
with the flag and a `subtotal_reason`, so the exclusion is auditable, and
stage 06 drops them. `is_subtotal_row` never reaches either panel.

The grand total row in this filing has no leading label in the company column,
so it is caught by the "money without an investment description" rule rather
than the "Total" rule. Both rules are kept: other filers label their subtotals.

## 7. Carried state

`industry` and `borrower` are carried forward **across fragment boundaries**,
because a borrower's tranches can straddle a page break. 846 of the 1,439
positions inherit their borrower from a row above. After parsing, stage 04
asserts that no position row has an empty borrower.

Assumption worth flagging: a row with a label in the company column and nothing
else is treated as an **industry heading**, not as a borrower name printed on
its own line. This holds here - the 24 such labels are exactly the 24 industry
groups, with no company names among them - but it is a filer-layout assumption
and would need rechecking on a BDC that prints the borrower on its own row.

## 8. Numbers

`bdc_06_normalize.parse_number` handles, in this order: em/en dash -> `0.0`
(an unfunded revolver shows "—", which is zero, not missing); `$` stripped;
trailing footnote markers stripped; trailing `%` stripped; surrounding
parentheses -> negative; thousands separators removed.

The footnote strip is anchored on a preceding digit - `(?<=\d)(\(\d{1,2}\))+$`
- so `1,234(5)` loses the `(5)` while `(1,234)` stays a negative number.

## 9. Rates (trap 8)

| Filing cell | Parsed to |
|---|---|
| Reference `SOFR (Q)` | `reference_rate = "SOFR"` (the `(Q)` is reset frequency, dropped) |
| Spread `5.25%` | `spread_bps = 525.0` |
| Coupon `8.65%` | `all_in_rate_pct = 8.65` |
| Coupon `9.48% (2.88% PIK)` | `all_in_rate_pct = 9.48`; PIK component kept separately in the interim file |
| Coupon `8.00% PIK`, blank reference | `all_in_rate_pct = 8.00`, `reference_rate = "fixed"` |
| Blank reference, blank coupon | `reference_rate = None` - non-income-producing (footnote 3) |

Reference rates present: SOFR 862, fixed 103, Base Rate 25, CORRA 19, Euribor 11,
SONIA 10, NIBOR 2, CDOR 2, TONA 1, BBSY 1, BKBM 1; 402 null (equity, warrants -
no coupon at all, footnote 3: "Investments without an interest rate are
non-income producing").
"Base Rate" and "Base rate" both appear in the filing and are canonicalised to
one value.

## 10. Dates in the SOI

Maturity and acquisition dates are printed as `MM/YYYY` ("10/2029"). The day is
not reported, so a month-only date is normalised to the **first day of the
month**. Choosing month end would invent precision the filing does not have.
Resulting maturity range: 2026-05-01 to 2054-06-01; 368 positions (equity,
warrants) have no maturity, which is legitimate.

## 11. Investment type vocabulary

109 distinct `investment_type_raw` strings map onto the six controlled values
by an ordered rule list. Order matters: "Class A **preferred** units" must hit
the preferred rule before the equity rule, and "Warrant to purchase **preferred**
stock" must hit the warrant rule before either.

| `investment_type` | rows |
|---|---|
| first lien | 965 |
| equity | 292 |
| preferred | 85 |
| subordinated | 53 |
| second lien | 25 |
| other | 19 |

`other` is only reached by an explicit rule (warrants, certificates,
participation rights, unclassifiable loans/notes). An unmatched raw string
raises `VocabularyError` and fails the run - it never falls into `other`
silently, per plan check 4.

## 12. Currency

**No non-USD positions found.** The SOI carries foreign reference rates
(CORRA, SONIA, Euribor, NIBOR, TONA, BBSY, CDOR, BKBM - 46 positions), but the
principal, cost and fair value columns are USD throughout: a scan for `£`, `€`,
`A$`, `C$` and for currency codes in the money columns returned zero hits, and
the SOI ties out exactly against a USD balance sheet.

A `currency` column was therefore **not** added, per the instruction to add one
only if non-USD positions are found. Nothing is silently mixed: everything in
`principal_amount` is USD. On a BDC that does report local-currency principal
(some do), this scan would fire and the column would be required.

## 13. `position_id`

`sha256` of `cik|period_end|borrower|investment_type_raw|maturity_date|principal|cost|fair_value|occurrence`,
truncated to 16 hex characters. Content-derived rather than row-number-derived,
so it is stable across parser changes. The occurrence counter disambiguates
positions identical in every reported field, which does occur (two identical
unfunded revolver tranches to the same borrower). Verified unique across all
1,439 rows.

## 14. What is written where

Stages 04-07 write only to `data/interim/`:

| File | Contents |
|---|---|
| `extract.json` | table indices, per-table scale, SOI as-of dates, non-accrual footnote number |
| `soi_rows.csv` | all 1,859 SOI rows including the 420 flagged subtotals - the audit trail |
| `soi_rows_normalized.csv` | 1,439 positions, USD, controlled vocabulary |
| `balance_sheet.json` | both columns, the column map, the reported total cost |
| `bdc_quarter.csv` / `.parquet` | the fund-level panel |
| `bdc_quarter_investment.csv` / `.parquet` | the position panel |

Nothing here writes to `output/`. Promotion is the verification gate's job.

---

# Decisions added by the full-history backfill (all 88 ARCC filings)

Each of these is a judgement a different reasonable parser could have made
differently. Evidence and consequences in `note/trap_log.md`.

## 15. Block boundaries produce a space; inline markup does not

`cell_text` inserts a space at `div`, `p`, `br`, `li`, `tr`, `td`, `th`,
`table`, `ul`, `ol` and `h1`-`h6` boundaries, and nowhere else. A block element
renders on its own line, so text either side of one is visually separated and
must be textually separated. Inline markup (`<b>`, `<font>`, `<span>`) still
joins tightly, so `<b>SO</b>FR` stays `SOFR`.

The risk accepted: if a filer ever splits a single number across two block
elements, this turns `1,234` into `1, 234`, which `parse_number` rejects rather
than mis-reads. That is the safe direction - a rejected number fails a check
loudly, a silently glued one does not. Verified against the 2026-06-30 filing:
both panels are byte-identical before and after.

## 16. Par and maturity read from the investment description only as a fallback

When the SOI has a Principal or Maturity column, that column is used. The
description is read only when the column is absent or its cell is empty. The
`par` keyword is required, so `($1.5 par due 5/2022)` yields a principal while
an equity row's `(4,000,000 units)` does not.

Alternative rejected: reading the description first, as "the most specific
statement". A filer that prints both could disagree between them, and the
column is the reported field.

## 17. A fully undrawn revolver records principal_amount = 0.0

Applied only when **all three** hold: the row is a debt type, no par is stated
anywhere, and the filing prints zero for **both** cost and fair value.

This is an inference and is worth naming as one. The filing does not print a
principal; it prints nothing. Three things justify the 0.0: the instrument is a
revolver with nothing drawn, the filer states zero cost and zero value for it,
and the modern layout - which has a Principal column - prints an em-dash there
for the same instrument, which `parse_number` already reads as 0.0. So this
records the value the same filer states in the era where the column exists.

The rule lives in stage 06, after the vocabulary, so it cannot touch equity or
warrant rows. An earlier version ran in stage 04 and gave 50 equity/warrant
rows a principal of 0.0; no check caught it, only the byte-diff of the
reference panel did.

Alternative rejected: leaving the field null. That fails the plan's
"principal_amount is non-null for every debt-type row" and would exclude ~25
otherwise-clean filings over positions the filing reports as zero.

## 18. A two-row date header is composed from the filing's own caption

`As of December 31,` in one row plus bare years `2025` / `2024` in the next are
combined into two dated columns. The month and day come from the caption in the
filing, never from `periodOfReport`: composing against the period end would make
check 6 ("the current column's header date equals periodOfReport") compare a
value against itself and it could never fail again. Every existing assertion
still runs unchanged.

## 19. Absent inline XBRL is a SKIP, not a FAIL

Inline XBRL was phased in for periods ending on or after 2019-06-15, so the
gate's independent ground truth simply does not exist for earlier filings.
Checks 5, 14 and 15 report SKIP with the condition stated. A pre-2019 filing
therefore passes on a weaker basis than a modern one, and `note/coverage.md`
records the skip count per filing so that difference stays visible.
