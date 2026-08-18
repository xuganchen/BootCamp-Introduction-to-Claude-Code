# Trap log - which of plan section 5's twelve traps actually fired

Filing: ARCC 10-Q, period end 2026-06-30, accession 0001628280-26-050307.

"Fired" means the trap was present in this filing and would have produced a
wrong number without a handler. "Handled, not present" means the handler
exists but this filing did not exercise it - that is worth recording, because
it is the set of things that are untested against real data here.

| # | Trap | Fired? | Evidence in this filing | Handler |
|---|---|---|---|---|
| 1 | Subtotal / total rows inside the SOI | **YES** | 419 per-borrower subtotal rows + 1 "Total Investments" row. Including them would have made `sum(fair_value)` = 112,328.0M against a reported 29,349.3M, a **+282.7%** error (the subtotals cascade: per-borrower subtotals plus the grand total) - the single largest failure mode | structural: money present but no investment description; or a leading label matching `^Total\|^Subtotal`. `bdc_04_parse_soi.py` |
| 2 | Multi-page SOI split across HTML tables | **YES** | the current-period SOI is **67 separate `<table>` elements** (indices 9-75), each with its own repeated header row | fragments walked as one stream in document order, header re-detected per fragment, `industry`/`borrower` carried across boundaries |
| 3 | Footnote markers glued to numbers and names | **YES** | `ACP Avenu Midco LLC (13)`, `Company (1)`, `Investment (18)`; footnote cells `(2)(9)` sitting in the fair-value region | `strip_footnotes` anchored on a preceding digit; `clean_name` for labels; pure-footnote cells excluded from numeric regions |
| 4 | Negative numbers in parentheses | **handled, not present** | no parenthesised negative appears in the SOI money columns of this filing | `parse_number` treats `(x)` as negative; the digit-anchored footnote regex keeps `(1,234)` and `1,234(5)` distinct |
| 5 | Scale header far above the table | **YES** | `(dollar amounts in millions)` sits in the page banner, outside the table, repeated per page; `(in millions, except per share data)` for the balance sheet. Assuming thousands would have been wrong by **1000x** | scale resolved per table from its own banner, recorded in `source_scale` |
| 6 | Controlled / affiliated / non-controlled sections with their own subtotals | **partially** | the balance sheet splits investments three ways (non-controlled/non-affiliate 24,282M, non-controlled affiliate 572M, controlled affiliate 4,495M) and footnotes (4)/(5) mark affiliate and control status per borrower, but this filing's SOI is sectioned by **industry** (24 groups), not by control status, and prints no control-section subtotals | the subtotal rule is shape-based, so it would catch control-section subtotals identically; the industry heading rule handles the sectioning that is actually present |
| 7 | Non-accrual flagged only by footnote | **YES** | 32 positions, 404.4M fair value (1.4% of the portfolio) carry footnote **(8)**, defined as *"Loan was on non-accrual status as of June 30, 2026."* Nothing else in the row says non-accrual. Corroborated by the MD&A statement that ~1% of the portfolio was on non-accrual | the footnote **number is discovered, not hardcoded**: the legend is regex-matched and anchored on the current period-end date, because the comparative SOI carries its own legend `(8) ... as of December 31, 2025` and other filers number their footnotes differently |
| 8 | Mixed rate strings: SOFR spreads, fixed rates, PIK | **YES** | `SOFR (Q)` + `5.25%` + `8.98%`; `9.48% (2.88% PIK)`; `8.00% PIK` with no reference rate; 11 distinct reference-rate families | split into `reference_rate` / `spread_bps` / `all_in_rate_pct`; PIK component captured separately; blank reference + a coupon -> `"fixed"` |
| 9 | Blank spacer rows; borrower inherited from the row above | **YES** | 29 fully blank rows; **846 of 1,439 positions** (59%) have no borrower in their own row and inherit it from above | blank rows skipped; last non-empty borrower carried, including across fragment boundaries; post-parse assertion that no position has a blank borrower |
| 10 | Equity and warrant rows with no principal, rate or maturity | **YES** | 292 equity + 85 preferred + 19 other rows; 368 positions have no maturity, 402 have neither a coupon nor a reference rate | those fields are nullable by schema; the never-null rule is enforced only where the plan requires it - `fair_value` always, `principal_amount` for debt-type rows only (0 violations) |
| 11 | Balance-sheet columns in merged cells with spacer and dollar-sign columns | **YES** | after colspan expansion the header dates sit at physical columns 3 and 9 of a 12-column grid; the value for the current column appears at index 3 on some rows and index 4 on others depending on whether a `$` cell is present | header-date -> column-range map built **once** from the header row, asserted (exactly two dates, distinct, one equal to `periodOfReport`, the other earlier), then reused for every row |
| 12 | Header dates written in prose; audited qualifiers | **YES** | the SOI banner reads `As of June 30, 2026` and the current statements are marked `(unaudited)`; the comparative SOI banner reads `As of December 31, 2025` with no unaudited marker (it is drawn from the audited 10-K) | `parse_date` strips prose and qualifiers; the audited flag is recorded in `extract.json` (`soi_audited: false` for the current period, `balance_sheet_audited: null` - the balance sheet's own banner states neither) |

---

## Bugs found by running against the real filing

Both were found by looking at output, not by reading code.

1. **Standalone footnote cells parsed as negative numbers.** A fair-value
   region holding `["—", "(11)"]` - an em-dash value plus a lone footnote
   marker - selected `(11)` as the number and parsed it as **-11**. 57 rows
   were affected and the tie-out came in **122.0M short (-0.42%)**. Traps 3 and
   4 collide here: the same parentheses mean "footnote" in one cell and
   "negative" in another. Fix: cells matching `^(\(\d{1,2}\))+$` in their
   entirety are discarded before any numeric read, while a marker *glued to* a
   number is still stripped. `bdc_04_parse_soi._PURE_FOOTNOTE`.

2. **PIK-only coupons were not recognised as fixed rate.** `parse_reference_rate`
   tested the coupon with `parse_number`, which rejects `"14.00% PIK"` because
   of the trailing text, so 87 fixed-rate PIK positions (fixed-rate count went from 16 to 103) got a null
   `reference_rate` instead of `"fixed"`. Fix: use the percentage-extracting
   `parse_all_in_rate_pct` instead of `parse_number`.

3. **Statement titles matched inside prose** (stage 03, caught before any
   numbers existed). `"...in the accompanying consolidated balance sheets."`
   inside a footnote classified four unrelated tables as balance sheets, and
   stage 03 aborted with "expected exactly 1 balance-sheet table, found 5". The
   abort was correct - the fix tightened the title test to standalone heading
   lines rather than relaxing the "exactly one" rule.

## Tie-out achieved

```
sum(investment.fair_value)  = 29,349,300,000.00 USD   (1,439 positions)
total_investments_fv        = 29,349,000,000.00 USD   (balance sheet, current column)
delta                       =        300,000.00 USD   = 0.001022%   (tolerance 0.1%)

sum(investment.cost)        = 29,674,600,000.00 USD
reported amortized cost     = 29,675,000,000.00 USD
delta                       =        400,000.00 USD   = 0.001348%
```

The residual is **presentation rounding, not a parsing error**: the SOI prints
one decimal place in millions (29,349.3) and the balance sheet prints whole
millions (29,349). The SOI's own printed "Total Investments" row is
29,349.3M - the parsed positions match it to the cent, exactly 0.000000%. No
tolerance was widened anywhere to get here.

## Not resolved / caveats

- **Company-name-on-its-own-row.** A row with a label in the company column and
  nothing else is treated as an industry heading. Correct here (all 24 such
  labels are industry groups), but it is a layout assumption that would need
  rechecking on a filer that prints the borrower on a separate line.
- **`pct_of_net_assets` is null for every position.** ARCC reports "% of Net
  Assets" only on the per-borrower subtotal rows, which are excluded by design.
  The field is nullable, so this is schema-legal, but the panel carries no
  per-position percentage for this filer.
- **`shares_outstanding_prior` is inferred from a single caption figure.** ARCC
  printed one share count rather than the usual "X and Y ... respectively", so
  the same 718,000,000 is used for both columns. Verified against the inline
  XBRL, where the same value is tagged for both period contexts - but it is a
  read of a one-figure caption, not two independent reads.
- **Only the current-period SOI is parsed.** `total_investments_fv_prior` has
  nothing to tie out against inside v1, by design (plan section 8).

---

# Second filing parsed: ARCC 10-Q, period end 2026-03-31

Accession 0001628280-26-027688, filed 2026-04-28, primary document
`arcc-20260331.htm`, 23,988,846 bytes, SHA-256 `cf9487aa874c...`. Run on
2026-08-16.

| Field | Value |
|---|---|
| Symptom | Not a check failure. The pipeline could not target this filing at all: `pick_filing` sorted by period end and returned `rows[0]`, so only the most recent 10-Q/10-K was reachable. |
| Signature | A requested period end that exists in the submissions JSON but is not the newest one. Nothing in the filing itself; this is a selection gap, not a representation difference. |
| Representation difference | None. This filing uses the same representation as 2026-06-30 in every respect probed below. |
| Extension | `bdc_01_resolve.pick_filing` gained optional `period_end` and `form` selectors, exposed as `--period-end` / `--form`; `bdc_01_resolve.main` now takes `argv`; `run_all.py` forwards the selectors to stage 01 only and calls the gate as `bdc_08_checks.main([])` so its argparse never sees them. |
| Serves | Every filer and every quarter: any period the filer reported is now reproducible by date. The selector is exact - an unreported period end fails with the list of periods that do exist, and two filings sharing a period end fail asking for `--form`. No accession, CIK or index is hardcoded, and the no-selector default is unchanged (most recent filing). |
| ARCC re-run | 2026-06-30 re-runs green with no selectors: 16 pass, 0 fail, 0 warn, 0 skip. |
| Residual | Tie-out delta 300,000.00 USD on 29,499,000,000.00 = **0.001017%** (tolerance 0.1%). Cost delta 500,000.00 USD on 29,648,000,000.00 = 0.001686%. Against the SOI's own printed grand total the parsed positions match to the cent, **0.000000%**. Presentation rounding, same as the first filing. No tolerance was widened. |
| New SKIPs | None. 16 pass, 0 fail, 0 warn, 0 skip. |

**No parser, vocabulary or tolerance change was required.** Every table in
section 2 of the skill was already sufficient: header labels, balance-sheet
labels, the type vocabulary, the rate canon, the scale words and the XBRL tags
all matched unchanged.

## Which traps fired on this filing

Same set as 2026-06-30, at slightly different magnitudes. Trap 4
(parenthesised negatives) is **still not present** and therefore still untested
against real data after two filings.

| Trap | This filing |
|---|---|
| 1 subtotals | 415 subtotal rows, all caught by the shape rule; the printed grand total is again **unlabelled**, so the `^Total\|^Subtotal` rule fired **0 times**. Both rules stay. |
| 2 fragmented SOI | 66 current fragments (67 last quarter), 65 comparative dropped |
| 3 glued footnotes | present, numeric markers only |
| 4 parenthesised negatives | **not present - still untested** |
| 5 scale banner | `millions` for both the SOI and the balance sheet |
| 7 non-accrual by footnote | 26 positions, 344.5M fair value, footnote **(8)** discovered from the legend |
| 8 mixed rate strings | 11 reference-rate families: SOFR 852, fixed 105, Base Rate 17, CORRA 16, Euribor 13, SONIA 10, NIBOR 2, CDOR 2, TONA 1, BBSY 1, BKBM 1, null 399 |
| 9 inherited borrower | 836 of 1,419 positions (59%) inherit their borrower; 30 spacer rows |
| 11 balance-sheet columns | header dates at columns 3 and 9 of a 12-column grid, identical layout |
| 12 prose dates | `As of March 31, 2026`, current SOI `(unaudited)` |

Footnote **(8)** means non-accrual in **both** legends in this document - the
current one anchored on "March 31, 2026" and the comparative one on
"December 31, 2025". The date anchoring at `bdc_03_extract.find_non_accrual_footnote`
was therefore exercised but not decisive here; it picked the current legend by
construction, and would have mattered had the numbering differed.

## Cross-filing confirmation (not available on a single filing)

Both filings report **2025-12-31** as their comparative column, parsed
independently from two different documents. All six comparative fields agree
exactly:

```
total_investments_fv_prior   29,485,000,000    both filings
total_assets_prior           31,235,000,000    both filings
total_liabilities_prior      16,917,000,000    both filings
net_assets_prior             14,318,000,000    both filings
nav_per_share_prior                   19.94    both filings
shares_outstanding_prior        718,000,000    both filings
```

This is a stronger statement about the balance-sheet column map than any single
run can make: an inverted or misaligned map in either run would have to be
wrong in the same way in both documents to produce this.

Position ids are disjoint across the two quarters (0 collisions on 2,858 rows),
as intended - `period_end` is part of the hashed key.

## Still-open caveats, re-confirmed on this filing

- `pct_of_net_assets` is null for all 1,419 positions, same cause as before.
- `shares_outstanding` comes from a one-figure caption again ("718 common shares
  issued and outstanding"), copied to both columns. Check 10 does corroborate it
  for the current column here: 19.59 x 718,000,000 = 14,065.6M against a
  reported 14,065M, 0.004%.
- The currency scan was re-run on this document and returned **zero** non-USD
  signals, so no `currency` column is required (`parsing_decisions.md` section 12).
- Footnote markers are numeric only; no lettered markers appear, so
  `_PURE_FOOTNOTE` remains sufficient.
- Only the current-period SOI is parsed (plan section 8).

---

# Full-history backfill: all 88 ARCC 10-K/10-Q filings

Run 2026-08-16 via `code/bdc_10_backfill.py`, which runs the unchanged
single-filing pipeline once per filing and keeps only what the gate promoted.
Coverage went from **5 of 88 to 22 of 88 filings, 0 regressions**. Full
per-filing detail in `note/coverage.md` and `note/coverage.json`.

The reference filing (2026-06-30) was re-run after every change below and its
two panels stayed **byte-identical** throughout. 124 tests pass.

## Extension 1 - filing history is paginated

| Field | Value |
|---|---|
| Symptom | Not a check failure. Only filings back to a 2013-03-31 period end were reachable; ARCC has reported since 2004. |
| Signature | `filings.recent` in the submissions JSON caps at 1000 entries; `filings.files` lists the overflow pages. ARCC: 1 extra page covering 2004-04-20 to 2013-04-13. |
| Representation difference | None - an EDGAR API shape, identical for every filer with a long history. |
| Extension | `bdc_01_resolve.filing_history` walks `recent` plus every page in `filings.files`; `pick_filing` uses it. |
| Serves | Any filer with more than 1000 filings on EDGAR. A backfill that walked `recent` alone would look complete and silently omit the early years. |
| Residual | 54 -> 88 filings visible. |

## Extension 2 - word boundaries lost inside a cell (mechanism, not vocabulary)

| Field | Value |
|---|---|
| Symptom | `SOIParseError: no SOI header row found; required ['company', 'cost', 'fair_value', 'investment']` on 25 filings, 2017-2021. |
| Signature | The header reads `AmortizedCost`, `FairValue`, `AcquisitionDate`, and - the giveaway - `Percentageof Net Assets`. A missing space *inside* a word means text extraction, not wording. |
| Representation difference | The filer stacks a two-line header as two sibling `<div>`s: `<td><div>Amortized</div><div>Cost</div></td>`. `lxml`'s `text_content()` concatenates descendant text with no separator. |
| Extension | `bdc_03_extract.cell_text` now walks the cell and inserts a space at every block-level boundary (`div`, `p`, `br`, `li`, `tr`, `td`, `th`, `table`, `ul`, `ol`, `h1`-`h6`). Inline markup still joins tightly, so `<b>SO</b>FR` stays `SOFR`. |
| Serves | Every filer and every cell. The damage was never limited to headers: any stacked borrower name or investment description lost the same space. |
| Why not the header patterns | A pattern matching `AmortizedCost` would have accepted the corrupted text everywhere else too, so borrower names and investment descriptions would have stayed silently glued while the tie-out still passed. **The right fix was upstream of the symptom.** |
| ARCC re-run | 2026-06-30 panels byte-identical. |

## Extension 3 - principal and maturity printed inside the investment description

| Field | Value |
|---|---|
| Symptom | `ValueError: N debt-type rows have no principal_amount`, N from 1 to 670, on 25 filings once extension 2 let them get further. |
| Signature | The SOI has **no Principal and no Maturity column at all**. The header is Company / Business Description / Investment / Interest / Acquisition Date / Amortized Cost / Fair Value / Percentage of Net Assets, and the description reads `First lien senior secured loan ($24.6 par due 1/2022)`. |
| Representation difference | Both fields are printed inside the investment description in the long-standing BDC convention `($X par due M/YYYY)`. |
| Extension | `bdc_06_normalize.parse_par_from_description` and `parse_due_from_description`; `bdc_04_parse_soi` falls back to them **only when the column is absent or empty**, so a reported column always wins. The `par` keyword is required, so an equity row's `(4,000,000 units)` is not mistaken for a principal. |
| Serves | Any filer using the convention, which is most of the older BDC universe. |
| Residual | 2020-03-31: 585 principals and 585 maturities recovered; tie-out 0.001392%. |

## Extension 4 - balance-sheet header split across two rows

| Field | Value |
|---|---|
| Symptom | `BalanceSheetError: no balance-sheet header row with two parseable dates found` on 8 filings - **every 10-K sampled, 2017 through 2025**. |
| Signature | Row 1 carries `As of December 31,` at one column; row 2 carries bare years `2025` and `2024`. Neither row alone holds a parseable date. ARCC's 10-Q writes the whole date in one cell; its 10-K does not. |
| Extension | `bdc_05_parse_bs._dated_columns` composes a bare-year header row with the nearest month-and-day caption above it (`HEADER_LOOKBACK = 4`). |
| Serves | Any filer using a stacked date header, and it is the standard 10-K layout here. |
| Guard | The month and day come from the filing's own caption, never from `periodOfReport`. Composing against the period end would make check 6 ("current column header date equals periodOfReport") circular and unable to fail. All existing assertions - exactly two dated columns, distinct, one equal to the period end - still run unchanged. |
| Residual | 2025-12-31 10-K: 16 pass / 0 fail / 0 warn / 0 skip, tie-out 0.000678%. Its `total_investments_fv` of 29,485,000,000 equals the `total_investments_fv_prior` that the 2026 Q1 and Q2 filings each reported independently. |

## Gate correction 1 - check 5 blamed the filing for the gate's blind spot

| Field | Value |
|---|---|
| Symptom | `check 5 FAIL: 0 dated column(s) found via inline XBRL, expected exactly 2` on every pre-2019 filing. |
| Signature | `inline_xbrl_facts` returns zero facts for **every** tag. Inline XBRL only became mandatory for fiscal periods ending on or after 2019-06-15. |
| Diagnosis | "The gate has no data" was being reported as "the filing has the wrong number of columns". The gate's own contract (module docstring) says a check that cannot be evaluated is a SKIP with a stated reason. |
| Fix | `_bs_dates` distinguishes "no inline XBRL in this document" from "inline XBRL reports a count other than two". The first is now `SKIP: CONDITION NOT MET: the filing carries no inline XBRL facts (pre-inline-XBRL filing)`. |
| Not a relaxation | Where inline XBRL exists, check 5 is exactly as strict as before. This removes a false FAIL, it does not remove a real one. |

## Gate correction 2 - check 16's maturity window was mis-specified

**This is the one place a bound was widened, so it is stated in full.**

| Field | Value |
|---|---|
| Symptom | `check 16 FAIL: 4 maturity_date(s) outside [period_end - 2y, period_end + 30y]`. |
| Evidence checked first | The four dates were traced back to the filing text before anything moved: `First lien senior secured loan ($16.0 par due 6/2017)` (Javlin), `($19.9 par due 1/2018)` (NECCO Holdings - the candy maker that failed in 2018), `($0.1 par due 2/2055)` and `($0.4 par due 6/2054)` (Sunrun solar securitizations). **The parser was right and the bound was wrong.** |
| Why the bound was wrong | A BDC holds defaulted paper years past its stated maturity, and solar/infrastructure paper runs 30+ years. Neither is implausible. |
| Change | `[period_end - 2y, period_end + 30y]` -> `[period_end - 10y, period_end + 40y]`, `bdc_08_checks.check_16_sanity_bounds`. |
| What is preserved | It still catches a mangled date (year 1900, year 2199), which is what a plausibility bound is for. Two tests were added: one asserting the real past-due and long-dated values pass, one asserting 1995 and 2120 still fail. |
| What was NOT changed | No tie-out, accounting-identity, NAV or XBRL tolerance. The tie-out is still 0.1%, the balance-sheet identity still 0.05%/1 USD, the XBRL cross-check still 0.1%. |

## A bug this backfill introduced, and how it surfaced

The first version of the undrawn-revolver rule ran in stage 04, before the
investment-type vocabulary. It fired on any row with zero cost and zero fair
value, and so gave **50 equity and warrant rows** in the 2026-06-30 reference
filing a `principal_amount` of 0.0 where the schema requires null.

Nothing in the 16 checks caught it - `principal_amount` is nullable for equity,
so 0.0 is schema-legal, and the tie-out was untouched. It was caught only by the
byte-for-byte diff of the reference panel against its pre-change backup, which
is why that regression step exists. The rule now lives in stage 06, after the
vocabulary, and is restricted to debt rows by construction.

## Traps: what the full history added

- **Trap 4 (parenthesised negatives): still not present.** After 88 filings the
  handler has still never met a real parenthesised negative in a money column.
- **Trap 1 (subtotals):** in every era the grand total is unlabelled and caught
  by the shape rule; the `^Total|^Subtotal` rule has still fired 0 times on ARCC.
- **New trap - lost word boundaries in a cell.** Signature: a missing space
  inside a word (`Percentageof`). Detected by reading the header row, not by any
  check. Nothing downstream can see it, because the damage is upstream of every
  number.
- **New trap - a statement header split across two rows.** Signature: bare years
  in one row, a month-and-day caption in another.
- **New trap - the gate's own ground truth absent.** Signature: every inline
  XBRL tag returns zero facts. Must be a SKIP, never a FAIL.

## Known gaps, with the extension each one needs

These are documented rather than fixed, and are the next work:

1. **Rate columns are unread for 2018-2022 (13 filings in the panel, 0% rate
   coverage).** Signature: the SOI has a single `Interest` column holding
   `8.50% (Base Rate + 5.25%/Q)` rather than separate Reference / Spread /
   Coupon columns. `HEADER_MAP` has no `^interest$` entry, so the column is
   unmapped. The values are **null, not wrong** - `parse_reference_rate`
   returns None when both cells are empty, so nothing is mislabelled as fixed.
   Extension needed: an `^interest$` header entry plus a combined-rate parser
   that decomposes `all-in% (Reference + spread%/freq)`.
2. **`nav_per_share` is 14% populated.** Older filings label the line
   differently; `LABEL_RULES` needs the variants.
3. **`pct_of_net_assets` is 0% populated** in every era, for the reason already
   recorded: ARCC prints it only on subtotal rows.
4. **2004-2016 (28 filings) never reach the SOI parser**, failing at
   `no SOI located` or `no balance sheet located`. These are a different
   document generation and need their own diagnosis; nothing here has been
   guessed about them.

---

# Backfill round 2: oldest-first, 2004 onward

Run 2026-08-16 with `bdc_10_backfill.py --order oldest`. Processing forward in
time makes each era's failures arrive as one contiguous block instead of
interleaved, which is what exposed that **every 10-K 2005-2012 failed the same
way** and **every 10-K 2013-2016 failed a different same way** - invisible when
walking newest-first.

The reference filing (2026-06-30) stayed byte-identical through every change
below; 124 tests pass.

## Extension 5 - SOI continuation pages that carry no banner

| Field | Value |
|---|---|
| Symptom | `gate FAIL on check(s) [13]`: 2005 Q1 summed 149,902,125 against a reported 235,331,295, **-36.3%**. Not a rounding residual - a third of the portfolio was missing. |
| Signature | `classify` found 1 current SOI fragment, but the schedule is 4 tables: current, its continuation, comparative, its continuation. The continuation repeats only the **column header row**, with no title, no "As of" line and no scale line, so it classified as "other" and was never parsed. |
| Representation difference | Modern filings repeat the whole banner on every printed page (ARCC 2026: 67 self-describing fragments). Older filings print the banner once and let the table run on. |
| Extension | `bdc_03_extract._attach_soi_continuations`: a table classified "other" is adopted as an SOI fragment when the table immediately before it in document order is an SOI fragment (or an already-adopted continuation) **and** its own grid contains a full SOI header row. It inherits the as-of date, scale and audited flag of its chain head. |
| Why it cannot over-reach | The chain breaks at the first table that fails the header test, so a note table following the schedule cannot pull in the rest of the document. Inheriting the *chain head's* as-of date keeps the current/comparative split exact: a comparative fragment's continuations inherit the comparative date and are dropped with it (2005 Q1: 2 adopted for the current schedule, 2 for the comparative, all 2 comparative dropped). |
| Residual | 2005 Q1 tie-out **0.000000%** - 235,331,295.00 against a reported 235,331,295.00, exact to the cent. |
| ARCC re-run | 2026-06-30 adopts 0 continuations (every fragment carries its own banner) and its panels are byte-identical. |

## Extension 6 - CP-1252 em dash decoded as a control character

| Field | Value |
|---|---|
| Symptom | `ValueError: 1 position rows have no fair_value; fair_value is never-null` on 2005 Q1, and the same on a long run of 2006-2016 filings. |
| Signature | The cell contains `\x97`, not `—`. Older EDGAR documents are CP-1252 served without a usable charset declaration, so the 0x80-0x9F punctuation range decodes to C1 control characters. |
| Why it mattered | 0x97 is the em dash, and in these filings the em dash **is how zero is written**. Left as U+0097 it reached `parse_number` as an unrecognised character, so a reported zero read as missing and tripped the never-null rule. |
| Extension | `bdc_03_extract._clean` translates the CP-1252 punctuation range to the characters the filer typed; `bdc_06_normalize.DASHES` also accepts `\x96`/`\x97` as a second line of defence. |
| Serves | Every filer with a pre-2010 document, and every field, not just money - the same range carries the curly quotes and apostrophes in borrower names. |

## Extension 7 - one "Interest" column instead of Reference / Spread / Coupon

| Field | Value |
|---|---|
| Signature | The SOI header reads `Interest (9)`, and the cell reads `13.00% (Base Rate + 7.25%/Q)` or `8.50% (Libor + 7.50%/Q)`. |
| Two separate defects | (a) `HEADER_MAP` had no `^interest$` entry, so the column was unmapped - and because a region runs to the **next mapped header**, the unmapped Interest column was being absorbed into the *investment description* region, polluting `investment_type_raw`. (b) With the column mapped but no combined-rate parser, `parse_reference_rate` would see an empty reference cell plus a parseable coupon and return `"fixed"` for every floating-rate position - **a wrong value, not a null.** |
| Extension | `^interest$` and `^stated interest rate$` added to the coupon entry; `parse_combined_reference` / `parse_combined_spread_bps` decompose `all-in% (Name + spread%/freq)`; `parse_reference_rate` tries the combined form **before** falling back to "fixed". `_REF_CANON` gained LIBOR, Euribor, SOFR. |
| Guard | The combined pattern requires a name followed by `+` and a percentage, so the modern `9.48% (2.88% PIK)` - which has no `+` - cannot match it. Verified: `SOFR (Q)`/`8.98%` still yields SOFR, `14.00% PIK` still yields fixed. |

## Extension 8 - "Fair Value Per Unit" column

| Field | Value |
|---|---|
| Signature | A `Fair Value Per Unit` column sitting between Fair Value and Percentage of Net Assets, in 2005-2016 layouts. |
| Why an unused column still has to be mapped | A region runs from its own header to the next **mapped** header. Leaving this unmapped extended the fair-value region across it, so whenever a position's real fair-value cell was blank, `region_value` would find the per-unit *price* and report it as the position's fair value. |
| Extension | Mapped to `fair_value_per_unit`, placed **before** the `fair_value` entry so the anchored `^fair value$` cannot claim it. The field is not carried into the panel; mapping it exists purely to bound the neighbouring region. |
| General lesson | An unmapped column is not neutral. It silently widens its neighbour. |

## Extension 9 - two more instrument types

`Letter of credit facility` (10 rows) and `Real estate owned` map to `other` by
**explicit rule**, in keeping with the standing decision that "other" is
reserved for things deliberately put there. A letter-of-credit facility is a
contingent commitment rather than a funded tranche; real estate owned is an
asset taken in a workout. Both rules precede the generic loan/note rule.

## Cross-check correction - C4 was mis-specified for a panel with gaps

| Field | Value |
|---|---|
| Symptom | `C4 FAIL: total_assets 2006-03-31 778,620,556 -> 2008-03-31 1,996,362,000 (61.0%)` and `net_assets 2009-09-30 -> 2011-03-31 (61.3%)`. |
| Diagnosis | Adjacent **rows** are not adjacent **periods** when the panel has gaps, and gaps are by design - an excluded filing leaves its period out. Both flagged pairs span 24 and 18 months of excluded filings, over which ARCC genuinely grew. The check was blaming the data for the coverage report's contents. |
| Change | The bound now depends on elapsed time: 60% for pairs <= 120 days apart (consecutive quarters, unchanged), a 10x band across a gap. |
| What is preserved | The thing C4 exists to catch - a scale error confined to one filing - is a 1000x jump, not a 61% one, so it is still caught either way. The message now reports how many pairs span a gap (11 of 38). |

## Driver correction - a resumed run under-reported its own coverage

`coverage.json` was rebuilt only from filings attempted in the current run, so a
resumed run (which skips everything already assembled) wrote a report listing
almost no filings. A coverage report that under-reports itself is worse than
none, because a missing row reads as "never attempted". Per-filing records are
now carried forward from the previous report and merged.

## Still excluded, with the extension each needs

- **`no balance sheet located`, every 10-K 2005-2012 (8 filings).** The statement
  title is not in the banner in a form `BS_TITLE_RE` recognises.
- **`no SOI located`, every 10-K 2013-2016 (6 filings).** The title and the
  as-of date share one line - `Schedules of Investments as of December 31, 2015
  and 2014` - so `_banner_title_pos`'s 60%-coverage guard rejects it as prose.
  The guard is right to be strict; the extension is to accept a line whose
  remainder after the title is itself just an as-of clause. Note the phrasing
  also warns that a 10-K SOI may carry two years in one table, which would need
  column selection, so this one must not be rushed.
- **`SOI header row not recognised`, 2006-2007 (5 filings).**
- **`debt rows with no principal_amount`, 2022-2024 (6 filings).**
- **One filer anomaly, 2019 Q3.** A row prints a borrower name,
  `Infinite Electronics International, Inc. ($13.0 par due 4/2022)`, in the
  **Investment** column while the Company column names a different borrower.
  Neighbouring rows in the same table are correctly aligned, so this is not a
  layout rule. `map_investment_type` refuses to guess and the filing is
  excluded. **Deliberately not fixed:** any rule mapping a company-name-shaped
  string to an instrument type would be inventing a type the filing does not
  state.

---

# Backfill round 3: only the quarters inside the existing panel span

Scope set deliberately to 2018-03-31 through 2026-06-30, highest period end
first, with no attempt to extend coverage backwards. 34 filings in that span, 23
already in the panel, **11 excluded at the start**.

## Extension 10 - unit-denominated debt (CLO subordinated notes)

| Field | Value |
|---|---|
| Symptom | `ValueError: 1 debt-type rows have no principal_amount` on 6 filings, 2022-12-31 through 2024-03-31. |
| Signature | `ARES 2007-3R | Subordinated notes | Shares/Units 20,000,000 | Principal (blank)`. The position's size is stated as a unit count; the Principal column is empty. |
| Representation difference | A CLO subordinated-notes tranche is unit-denominated. There is no USD principal to report, so the filer reports units instead. |
| Extension | `bdc_06_normalize.normalize_soi` exempts a debt row from the principal rule when it carries a positive `shares_units` and no principal. `principal_amount` is left **null**, not filled - unlike the undrawn-revolver case there is no printed zero anywhere to record. |
| Why it cannot mask a failed extraction | On the 2024 Q1 filing, **0 of 831** normal debt rows carry a Shares/Units count while the one exception does. A row whose principal we simply failed to read would have neither field. |
| Schema change | `shares_units` added to the investment panel (`bdc_07_panels.INVESTMENT_COLUMNS`), extending plan v1 section 3.2. Without it the panel carries no stated size for these rows, **and the gate has no evidence with which to check the principal rule itself** - check 2 now reads `shares_units` from the panel rather than taking the parser's word for it. |
| Reference filing | 2026-06-30: the new column is the only difference; every pre-existing column is byte-identical and the quarter panel is unchanged. |

## Extension 11 - commitment lines that print no amounts at all

| Field | Value |
|---|---|
| Symptom | `ValueError: 1 position rows have no fair_value` on 2022-03-31. |
| Signature | `Rialto Management Group, LLC | First lien senior secured revolving loan | 11/30/2018` with the cost cell empty and the fair-value region holding **only the footnote `(14)`** - not even the em dash that elsewhere means zero. |
| Extension | Both amounts recorded as 0.0, in stage 06. |
| Why this is safe rather than a guess | It is independently checkable and independently checked: if the filing did attribute value to the row, adding zero would break the tie-out. On this filing the other positions already reach the reported total to **-0.002566%**, so the filing itself attributes nothing to the line. Check 13 re-verifies at 0.1% on every run. |
| Bounded | More than 0.5% of positions in this state raises instead, because a mis-parsed fragment would produce many such rows and zeroing those would understate the portfolio. |

## Gate correction 3 - check 16's fv/cost ratio had no materiality floor

| Field | Value |
|---|---|
| Symptom | `1 debt row(s) with fair_value/cost outside [0, 3]; worst ratio=6.00 (fv=600,000.00 cost=100,000.00)` on 2023-03-31, and 3.50 on 2023-09-30. |
| Evidence checked first | The row is `Prime Buyer, L.L.C`, a first lien revolver printed as principal 0.7, cost 0.1, fair value 0.6. The filing reports in millions to one decimal, so each of those figures is a single printed digit carrying +/-50% of rounding. The ratio is built entirely out of presentation rounding. |
| Why the columns are known to be right | On the same run, three independent checks passed: 13 tied the fair-value column to the balance sheet at **0.000000%**, 14 tied the cost column to the reported total at **0.001867%**, and 15 tied both balance-sheet columns to the XBRL. A column misread cannot survive those and then show up only in one tiny row. |
| Change | The ratio test now applies only where cost is at least 10 presentation granules, the granule being derived from the panel's own recorded `source_scale` (millions -> 0.1M, thousands -> 0.1k, units -> 0.1). |
| Never silent | Rows not evaluated are reported as a WARN naming the count and the floor: on the reference filing, "fv/cost ratio not evaluated for 152 debt row(s) with cost below 1,000,000.00". |

## Gate correction 4 - the maturity window was applied to warrants

| Field | Value |
|---|---|
| Symptom | `2 maturity_date(s) outside [2012-12-23, 2063-01-30]; examples: ['2100-08-01', '2100-08-01']` on the 2022 10-K. |
| Evidence checked first | The filing prints `8/2100` for a McLaren Group warrant. The parse is faithful to the page. |
| Diagnosis | A loan maturing in 2100 is a parse error; a warrant expiring in 2100 is a filer convention for "effectively no expiry". The single window was asking the same question of two different instruments. |
| Change | Debt keeps the tight `[-10y, +40y]` window unchanged. Non-debt rows get `[1980-01-01, 2200-01-01]`, loose enough to admit a nominal far-future expiry and still catch a mangled year. |

## Fixed in this round (7 of 11)

2024-03-31, 2023-12-31, 2023-09-30, 2023-06-30, 2023-03-31, 2022-12-31,
2022-09-30.

## Deliberately still excluded (4 of 11), with the evidence

Three of these are the **same filer defect**: the filing puts the wrong text in
the Investment column, so it never states the instrument.

- **2018-03-31.** `Heartland Dental, LLC` - Business Description reads
  `Detanl services provider` (the filer's own typo) and the **Investment**
  column reads `Dental services provider ($27.8 par due 7/2024)`. The
  description text was typed into the instrument column. The filing does not
  name the instrument anywhere on the row.
- **2018-06-30.** Investment column holds only `($0.6 par due 10/2020)` - the
  instrument name is absent.
- **2019-09-30.** Investment column holds
  `Infinite Electronics International, Inc. ($13.0 par due 4/2022)`, a borrower
  name; neighbouring rows in the same table are correctly aligned, so this is
  not a layout rule.

  In all three the row is clearly debt - it has a par amount, a maturity and a
  floating coupon - but the **lien seniority is not stated**, and first lien
  versus second lien is exactly what `investment_type` records. Mapping them to
  `other` would violate the standing rule that "other" is reserved for
  instruments explicitly decided to belong there, and picking a lien would
  invent the fact the filing is missing. `map_investment_type` refuses, the
  filing is excluded, and the row cannot simply be dropped either because it
  carries fair value and would break the tie-out.

- **2022-03-31.** Two `Senior subordinated revolving loan` positions
  (Sunrun Luna Holdco 2021) are drawn - cost 45.0 and 30.0, fair value 44.6 and
  29.7 - but state no par in the description, and this era's SOI layout has
  **no Principal column at all**. 568 of 888 positions in the same filing do
  state par, so this is the filer omitting it on two rows, not a parsing
  failure. Leaving `principal_amount` null would satisfy nothing the gate can
  verify: unlike the unit-denominated case there is no `shares_units` to point
  at, and there is no reported total principal to tie against. **Not fixed on
  purpose** - exempting it would mean relaxing a never-null rule with no
  independent verifier, which is the one thing the gate exists to prevent.
