---
name: bdc-soi-parse
description: Parse a BDC's Schedule of Investments and balance sheet from a raw SEC 10-Q/10-K into the two panels, and pass the 16-check verification gate. Use when pointing the pipeline at a BDC or a quarter it has not parsed before, when a gate check fails on an unfamiliar filing, or when deciding whether a filing needs a new handler.
---

# Parsing a BDC filing that this pipeline has never seen

The engine already exists in `code/`. Do not rewrite it and do not copy it into a
new script. Your job on a new filer or a new quarter is: run it, read the
failure, decide which of the shared configuration tables is missing an entry,
add the entry, and record what forced it.

The pipeline was built and tied out against exactly one filing: ARCC 10-Q,
period end 2026-06-30, accession 0001628280-26-050307. Everything the ARCC
filing did not exercise is untested. `note/trap_log.md` says which traps
actually fired and which handlers have never met real data.

Run it:

```bash
python3 code/run_all.py                                   # latest filing, stages 01-07, then the gate
python3 code/run_all.py --ticker OBDC                     # ticker is a parameter, not a constant
python3 code/run_all.py --ticker ARCC --period-end 2026-03-31   # any reported period, by date
python3 code/bdc_08_checks.py --no-promote                # re-run the gate alone
```

`--period-end` is an exact selector, not a nearest-match: a period the filer
never reported fails with the list of periods that exist. `--form` disambiguates
when a period end appears on both a 10-Q and a 10-K.

`output/` and `data/interim/` hold **one filing at a time** (plan v1 scope). A
run overwrites the previous one. To cover many filings, do not copy files by
hand and do not make the stages multi-filing - use the assembly driver in
section 8:

```bash
python3 code/bdc_10_backfill.py --ticker ARCC              # every 10-K/10-Q the filer has
python3 code/bdc_10_backfill.py --ticker ARCC --from 2013-01-01
```

Exit non-zero and nothing in `output/` is the correct result of a failing run.

---

## 1. Reuse unchanged

These are mechanisms, not filer knowledge. If one of them looks wrong on a new
filing, you have almost certainly found a missing vocabulary entry instead.
Read the file before concluding otherwise.

| Reuse | Where | What it does |
|---|---|---|
| EDGAR client, throttle, cache, `parse_date` | `code/bdc_09_utils.py:40-94` | every byte cached to `data/raw/`, never refetched |
| Ticker -> CIK | `code/bdc_01_resolve.py:21-27` | CIK looked up at runtime, never hardcoded |
| Full filing history, all submissions pages | `code/bdc_01_resolve.py:30-76` | `filings.recent` caps at 1000 entries; older years live in `filings.files` |
| Filing selection by period end / form | `code/bdc_01_resolve.py:78-121` | exact selector, fails with the list of real periods |
| Manifest with SHA-256 | `code/bdc_02_fetch.py:26-43` | provenance for the whole run |
| Banner capture and table classification | `code/bdc_03_extract.py:130-252` | nothing in a table's markup says what it is; the banner above it does |
| Colspan grid | `code/bdc_03_extract.py:97-127` | makes a column index a stable coordinate; `rowspan` is deliberately not expanded |
| Two-SOI discrimination by as-of date | `code/bdc_03_extract.py:264-311` | the single largest correctness risk in the document |
| Header -> region map, region token selection | `code/bdc_04_parse_soi.py:93-158` | survives `$` cells and footnote cells drifting inside a column |
| Cross-fragment carried state | `code/bdc_04_parse_soi.py:173-306` | industry and borrower straddle page breaks |
| Build-once, assert-once column map | `code/bdc_05_parse_bs.py:68-158` | a per-row column guess is silent when wrong |
| Number, footnote, rate, date parsing | `code/bdc_06_normalize.py:58-215` | `parse_number` handles dash-as-zero, parenthesised negatives, glued footnotes |
| Content-derived `position_id` | `code/bdc_07_panels.py:45-65` | stable across parser changes |
| All 16 checks, fail-closed promotion | `code/bdc_08_checks.py:383-969` | the gate derives its own ground truth and never trusts the parser |

Note the gate's independence rule (`code/bdc_08_checks.py:5-13`): it reads the
inline XBRL and companyfacts itself. Never feed it a value the parser produced
and call that a cross-check.

---

## 2. Extend, and exactly where

Every filer difference this pipeline has anticipated is a row in one of these
tables. Adding a row serves every filer. **A per-filer branch (`if ticker ==`,
`if cik ==`, a per-filer module, a per-filer config file) is not an acceptable
extension** and will be rejected on review: it makes the pipeline a collection
of one-filing scripts, which is the thing the tie-out exists to prevent.

| You saw | Add to | File:line |
|---|---|---|
| an SOI column header spelled differently | `HEADER_MAP` | `code/bdc_04_parse_soi.py:62-76` |
| a required SOI column genuinely absent | reconsider `REQUIRED_HEADERS` (see 5.4) | `code/bdc_04_parse_soi.py:78` |
| a balance-sheet row labelled differently | `LABEL_RULES` | `code/bdc_05_parse_bs.py:41-46` |
| a different share-count caption | `SHARES_RE` | `code/bdc_05_parse_bs.py:53-56` |
| amortized cost stated differently | the cost-caption regex | `code/bdc_05_parse_bs.py:216-219` |
| a new instrument description | `_TYPE_RULES`, ordered, first match wins | `code/bdc_06_normalize.py:228-248` |
| a rate name cased two ways | `_REF_CANON` | `code/bdc_06_normalize.py:167` |
| a reset-frequency suffix other than (M)(Q)(S)(A) | `_REF_SUFFIX` | `code/bdc_06_normalize.py:160` |
| a new scale word ("billions", none at all) | `SCALE_RE` **and both** `SCALE_FACTOR` maps | `code/bdc_03_extract.py:52,54`, `code/bdc_06_normalize.py:34` |
| a statement titled differently | `BS_TITLE_RE` / `SOI_TITLE_RE` | `code/bdc_03_extract.py:44-49` |
| an LP/LLC-form BDC (partners' capital) | `IX_TAGS` and `XBRL_CROSSCHECK` | `code/bdc_08_checks.py:166-176,733-737` |
| a maturity/acquisition date format | `_MM_YYYY` / `_MM_DD_YYYY` | `code/bdc_06_normalize.py:123-124` |
| lettered or 3-digit footnotes | `_PURE_FOOTNOTE`, `_FOOTNOTE_TAIL`, `_FOOTNOTE_ANY` | `code/bdc_04_parse_soi.py:124`, `code/bdc_06_normalize.py:53-54` |
| a repeated-header cell spelled differently | the continuation-header test | `code/bdc_04_parse_soi.py:206` |
| non-USD principal or fair value | a `currency` column: `INVESTMENT_COLUMNS` plus a parse of the symbol/code | `code/bdc_07_panels.py:36-42` |
| par/maturity printed inside the description, no such column | `parse_par_from_description` / `parse_due_from_description` | `code/bdc_06_normalize.py:157-186` |
| a date header split across two rows (bare years + a caption) | `_dated_columns` / `_month_day_above` | `code/bdc_05_parse_bs.py:68-131` |
| a missing space *inside* a word (`Percentageof`) | `cell_text` block-boundary set - a mechanism fix, see below | `code/bdc_03_extract.py:89-137` |
| an SOI page repeating only the column header, no banner | `_attach_soi_continuations` | `code/bdc_03_extract.py:270-325` |
| `\x97` / `\x96` instead of a dash (pre-2010 CP-1252 docs) | `_CP1252_PUNCT` in `_clean`, and `DASHES` | `code/bdc_03_extract.py:94-108`, `code/bdc_06_normalize.py:48` |
| one `Interest` column holding `13.00% (Base Rate + 7.25%/Q)` | `^interest$` in `HEADER_MAP` **and** `parse_combined_reference` / `parse_combined_spread_bps` | `code/bdc_04_parse_soi.py:70`, `code/bdc_06_normalize.py:193-225` |
| a column you do not need but that sits between two you do | map it anyway, before its neighbour - see "an unmapped column is not neutral" | `code/bdc_04_parse_soi.py:78-85` |
| debt sized in units, not principal (CLO subordinated notes) | the `shares_units` exemption, and `shares_units` in the panel so the gate can see it | `code/bdc_06_normalize.py:376-397`, `code/bdc_07_panels.py:36-46` |
| a commitment line printing no cost and no fair value at all | zero both, bounded at 0.5% of positions | `code/bdc_06_normalize.py:340-372` |

Rules for a new entry:

1. **Add, never replace.** ARCC's spellings must keep matching. Re-run against
   the ARCC filing before you call the extension done.
2. **Ordered lists stay ordered by specificity.** In `_TYPE_RULES`, "Class A
   preferred units" must reach the preferred rule before the equity rule and
   "Warrant to purchase preferred stock" must reach the warrant rule before
   either (`note/parsing_decisions.md:205-225`). Insert, do not append blindly.
3. **A pattern that would also match something else is not an extension, it is a
   bug.** `total_liabilities` is anchored exactly so "Total liabilities and
   stockholders' equity" cannot capture it (`code/bdc_05_parse_bs.py:43`).
4. **Widen the vocabulary, never the tolerance.** See section 6.

### When it is genuinely the mechanism, not the vocabulary

The default assumption stays "you found a missing vocabulary entry". It has been
wrong exactly once, and the tell was specific: **a missing space inside a word.**
`Percentageof Net Assets` and `AmortizedCost` are not how anyone writes a
header, so the text extraction was at fault, not the pattern. The filer stacked
the header as two sibling `<div>`s and `text_content()` concatenated them.

The rule that decides: ask what else the fix touches. Loosening the header
pattern to match `AmortizedCost` would have made the header parse while leaving
every borrower name and investment description silently glued, and no check
would have caught it - the tie-out is indifferent to a corrupted string. Fixing
`cell_text` repaired all of them at once.

**Suspect the mechanism when the symptom is malformed text rather than
unfamiliar text.** Everything else is vocabulary.

Two more mechanism cases have since been confirmed, both in text handling and
both invisible to every check:

- **`\x97` where a dash belongs.** Pre-2010 EDGAR documents are CP-1252 served
  without a usable charset, so the punctuation range decodes to C1 control
  characters. It matters because the em dash *is how these filings write zero*:
  left undecoded, a reported zero reads as missing.
- **A page that repeats only the column header.** Older filings print the SOI
  banner once and let the table run across pages, so continuation pages
  classify as "other" and vanish. On ARCC 2005 Q1 that silently dropped a third
  of the portfolio - the tie-out caught it at -36.3%, but nothing else would
  have.

### An unmapped column is not neutral

A region runs from its own header to the **next mapped header**, so an unmapped
column silently widens its left-hand neighbour. A `Fair Value Per Unit` column
left unmapped extended the fair-value region across it, and `region_value`
would then report a per-unit *price* as a position's fair value whenever the
real cell was blank.

So map a column even when the panel does not want it, and place the more
specific pattern first (`^fair value per unit$` before `^fair value$`). The same
mechanism sent an unmapped `Interest` column into the investment-description
region, corrupting `investment_type_raw`.

Two extensions are structural rather than table entries, and both need a stated
decision in `note/parsing_decisions.md`:

- **Borrower printed on its own row.** `code/bdc_04_parse_soi.py:210-216` treats
  a lone label in the company column as an industry heading. On a filer that
  prints borrowers that way, this silently converts borrowers into industries.
  The extension is a discriminator (does the label reappear as a section header?
  does an industry column exist separately?), added to the row classifier for
  all filers, not a per-filer flag.
- **Control-status sectioning.** ARCC sections its SOI by industry
  (`note/trap_log.md:17`). A filer sectioning by non-controlled / affiliated /
  controlled prints those subtotals too; the shape-based subtotal rule catches
  them, but the section label will land in `industry` unless you add a separate
  carried field.

---

## 3. Detecting which representation a filing uses

Run these before assuming anything. Each is cheap and each maps to a decision
the pipeline has to make. Stage 03 writes most of the answers to
`data/interim/extract.json`; read that file first.

| Question | Signature to look for | Consequence |
|---|---|---|
| How many SOIs? | distinct `soi_all_dates` in `extract.json`; ARCC had 2 (67 current + 65 comparative fragments) | summing both roughly doubles the portfolio |
| Is the SOI fragmented? | `n_soi_fragments_current` > 1 | header must be re-detected per fragment; state carries across |
| What scale? | `soi_scale`, `balance_sheet_scale`; the banner phrase `(dollar amounts in millions)` vs `(in thousands, except per share data)` | a 1000x error that check 9 cannot see and check 15 can |
| Do the SOI and the balance sheet share a scale? | compare the two fields | they need not; the pipeline resolves scale per table |
| How are subtotals printed? | grep `data/interim/soi_rows.csv` for `subtotal_reason`; ARCC: 419 unlabelled per-borrower + 1 unlabelled grand total | if a filer labels them, the `^Total|^Subtotal` rule fires instead; keep both |
| Sectioned by what? | the values landing in `industry` in `soi_rows.csv`; ARCC: 24 industry names | control-status sectioning needs a second carried field |
| Footnote style | the legend block; ARCC: numeric `(1)`-`(18)` | lettered footnotes defeat `_PURE_FOOTNOTE` and re-open the trap-3/trap-4 collision |
| Which footnote means non-accrual? | discovered at `code/bdc_03_extract.py:314-337`, never hardcoded | if the WARNING "no non-accrual footnote legend found" appears, `is_non_accrual` is False everywhere and the panel is wrong-but-passing |
| Balance-sheet columns | `column_map` in `data/interim/balance_sheet.json`; must be exactly 2 dated | 3+ columns aborts by design |
| Comparative kind | `period_end_prior_kind`; 10-Q normally `prior_fiscal_year_end` | `prior_quarter_end` is allowed but warns (check 8) |
| Share count form | `shares_caption` in `balance_sheet.json`; one figure vs "718 and 717 ... respectively" | a one-figure caption is copied to both columns and is a weaker read (`note/trap_log.md:82-85`) |
| Amortized cost location | a caption inside the total-investments label vs its own row | drives whether check 14 can run |
| Rate representation | distinct `reference_raw` / `coupon_raw` values in `soi_rows.csv` | PIK-only coupons, blank reference, foreign reference rates |
| Date format | distinct `maturity_date` raw strings | `MM/YYYY` normalises to the first of the month |
| Currency | scan the money columns for the symbols and codes; ARCC returned zero hits (`note/parsing_decisions.md:229-237`) | any hit makes a `currency` column mandatory |
| Legal form | `us-gaap:StockholdersEquity` present in the inline XBRL vs `PartnersCapital` / `MembersEquity` | drives check 15's tag map |

A fast way to see the layout without reading 25 MB: run stages 01-04, then read
`data/interim/soi_rows.csv`, which contains every row including the flagged
subtotals, with `subtotal_reason` explaining each exclusion.

---

## 4. Acceptance criteria

From `plan_v0.md`, non-negotiable:

- **BDC-quarter panel**: one row per BDC-quarter; `BDC`, `CIK`, `period end`,
  `filing date` never null; `total liabilities + net assets = total assets`.
- **BDC-quarter-investment panel**: one row per position; `BDC`, `period end`,
  `borrower`, `investment type`, `amount`, `fair value` never null; the sum of
  extracted fair value equals total investments in the filing **within 0.1%**;
  unique borrower names fewer than rows.
- Units consistent across rows and tables.
- **If any check fails, exit non-zero and write no output file.**

`plan_v0`'s `amount` is `principal_amount`, and its never-null rule is relaxed
for that one field only: non-null for every debt-type row, nullable for equity,
preferred and other, because equity has no principal (`plan_v1.md:106`). That is
the only relaxation anywhere in this pipeline, it is written down, and it is
enforced at `code/bdc_06_normalize.py:317-323` and `code/bdc_08_checks.py:415-423`.

`plan_v1.md:108-143` expands these into the 16 checks in
`code/bdc_08_checks.py`. Which ones matter most on an unfamiliar filing:

- **5, 6, 12** catch the comparative balance-sheet column being read as current.
- **13** is the core tie-out and doubles as a second, independent confirmation
  that the right column was identified: the SOI sum ties to one column, not both.
  Check 13 prints "the SOI sum ties to the PRIOR column instead" when the map is
  inverted (`code/bdc_08_checks.py:686-689`) - read that line before touching
  anything else.
- **15** is the only check that can see a scale error, because a 1000x error
  makes both sides of check 9 wrong by the same factor.
- **4** fails the run on an unmapped instrument rather than bucketing it into
  "other".

WARN and SKIP do not block promotion; only FAIL does
(`code/bdc_08_checks.py:65-68`). A SKIP is a check that could not be evaluated
and it always states why. Read every SKIP on a new filer: a green run with four
SKIPs is a much weaker result than a green run with none.

---

## 5. Traps, and the signature that detects each

From `note/trap_log.md`, written against the ARCC filing. "Fired" means the trap
was present and would have produced a wrong number. "Not present" means the
handler exists but has never met real data - treat those as unverified.

| # | Trap | Detection signature | Handler | ARCC |
|---|---|---|---|---|
| 1 | Subtotal / total rows inside the SOI | `sum(fair_value)` overshoots reported total by a large multiple; ARCC: 112,328.0M vs 29,349.3M, **+282.7%** | shape-based: money present but no investment description, or leading label `^Total\|^Subtotal` - `code/bdc_04_parse_soi.py:80,221-226` | fired |
| 2 | Multi-page SOI split across tables | `n_soi_fragments_current` > 1 (ARCC: 67); a repeated header row inside the data | fragments walked as one stream, header re-detected per fragment - `code/bdc_04_parse_soi.py:185-206` | fired |
| 3 | Footnote markers glued to numbers and names | borrower names ending `(13)`; cells reading `(2)(9)` | `strip_footnotes` anchored on a preceding digit, `clean_name` - `code/bdc_06_normalize.py:53,58-80` | fired |
| 4 | Negative numbers in parentheses | `(1,234)` in a money column | `parse_number` treats `(x)` as negative - `code/bdc_06_normalize.py:103-110` | **not present - untested** |
| 3+4 | The collision | a lone `(11)` beside an em-dash parsed as **-11**; ARCC: 57 rows, tie-out **-0.42%** | `_PURE_FOOTNOTE` discards footnote-only cells before any numeric read - `code/bdc_04_parse_soi.py:124,142` | fired |
| 5 | Scale header far above the table | banner reads `(dollar amounts in millions)`; totals off by exactly 1000x | scale resolved per table, recorded in `source_scale` - `code/bdc_03_extract.py:52,181-186` | fired |
| 6 | Controlled / affiliated sections with their own subtotals | control-status labels appearing as section headings; subtotals between them | same shape-based subtotal rule; **but** the label lands in `industry` | partial - ARCC sections by industry |
| 7 | Non-accrual flagged only by footnote | a legend line "(n) Loan was on non-accrual status as of <period end>"; nothing in the row says non-accrual | footnote number **discovered** from the legend and anchored on the period end, because the comparative SOI carries its own legend - `code/bdc_03_extract.py:314-337` | fired (32 positions, 404.4M) |
| 8 | Mixed rate strings | `SOFR (Q)` + `5.25%`; `9.48% (2.88% PIK)`; `8.00% PIK` with no reference | split into `reference_rate` / `spread_bps` / `all_in_rate_pct` / `pik_rate_pct`; blank reference + a coupon -> `"fixed"` - `code/bdc_06_normalize.py:170-214` | fired (11 rate families) |
| 9 | Blank spacer rows; inherited borrower | fully blank rows; ARCC: 846 of 1,439 positions (59%) have no borrower of their own | blanks skipped, last borrower carried across fragments, post-parse assertion of no blank borrower - `code/bdc_04_parse_soi.py:200-203,232-236,300-303` | fired |
| 10 | Equity/warrant rows with no principal, rate or maturity | rows with a fair value and nothing else; ARCC: 402 with neither coupon nor reference | those fields nullable by schema; never-null enforced only where the plan requires it | fired |
| 11 | Balance-sheet merged cells, spacer and `$` columns | the value sits at index 3 on some rows and 4 on others | header-date -> column-range map built once, asserted, reused - `code/bdc_05_parse_bs.py:68-158` | fired |
| 12 | Header dates in prose; audited qualifiers | `As of June 30, 2026`, `December 31, 2025 (audited)` | `parse_date` strips prose and qualifiers; audited flag recorded in `extract.json` - `code/bdc_09_utils.py:73-94` | fired |
| 13 | **Word boundaries lost inside a cell** | a missing space *inside* a word: `AmortizedCost`, `Percentageof Net Assets`. Stacked `<div>`s in one `<td>` | space inserted at block boundaries - `code/bdc_03_extract.py:89-137` | fired, 2017-2021 (25 filings) |
| 14 | **No Principal / Maturity column; both inside the description** | header has no principal column; descriptions read `($24.6 par due 1/2022)` | description fallback, column always wins - `code/bdc_06_normalize.py:157-186` | fired, 2017-2024 |
| 15 | **Statement date header split across two rows** | bare years `2025` / `2024` in one row, `As of December 31,` above | composed from the filing's own caption - `code/bdc_05_parse_bs.py:68-131` | fired, every 10-K 2017-2025 |
| 16 | **The gate's own ground truth is absent** | every inline-XBRL tag returns zero facts (pre-2019 filings) | checks 5/14/15 SKIP with the condition stated - `code/bdc_08_checks.py:464-486` | fired, all pre-2019 |
| 17 | **SOI continuation pages with no banner** | fragment count far lower than the page count; tie-out short by a large fraction (2005 Q1: **-36.3%**) | chain-based adoption, header required - `code/bdc_03_extract.py:270-325` | fired, 2005-2016 |
| 18 | **CP-1252 punctuation as control characters** | a cell holds `\x97`, not `—`; a reported zero reads as missing | `_CP1252_PUNCT` translation in `_clean` - `code/bdc_03_extract.py:94-108` | fired, pre-2010 |
| 19 | **One combined rate column** | header `Interest`; cell `13.00% (Base Rate + 7.25%/Q)` | combined-rate parser tried before the "fixed" fallback - `code/bdc_06_normalize.py:193-225` | fired, 2005-2016 |
| 20 | **An unmapped column widening its neighbour** | a value that is really a per-unit price appearing as a fair value | map the column, most specific pattern first - `code/bdc_04_parse_soi.py:78-85` | fired, 2005-2016 |
| 21 | **Unit-denominated debt** | a debt row with a Shares/Units count and an empty Principal column | exempt from the principal rule, principal left null - `code/bdc_06_normalize.py:376-397` | fired, 2022-2024 |
| 22 | **A commitment line with no amounts** | cost blank, fair-value region holding only a footnote - not even an em dash | both recorded 0.0, verified by the check 13 tie-out - `code/bdc_06_normalize.py:340-372` | fired, 2022 Q1 |
| 23 | **The filer typed the wrong text into the Investment column** | the instrument cell holds a business description or a borrower name, plus a par fragment; a neighbouring cell may carry the filer's own typo (`Detanl services provider`) | none - the filing never states the instrument, so the run fails and the filing is excluded | fired, 2018-2019 |

Two additional signatures worth knowing, both from real bugs
(`note/trap_log.md:27-51`):

- **PIK-only coupons read as null reference rate.** Signature: fixed-rate count
  implausibly low (ARCC: 16 where the truth was 103). Cause: testing the coupon
  with `parse_number`, which rejects `"14.00% PIK"`. Fix at
  `code/bdc_06_normalize.py:182`.
- **Statement titles matched inside prose.** Signature: stage 03 aborts with
  "expected exactly 1 balance-sheet table, found 5". The abort was correct. The
  fix was the standalone-heading guard (`code/bdc_03_extract.py:163-178`), not
  relaxing the "exactly one" rule.

---

## 6. Repairing yourself on an unfamiliar filing

### 6.1 When a check fails

Work in this order. Do not skip to step 4.

1. **Read the failure, do not re-run it.** Every check prints actual, expected,
   absolute diff and relative diff (`code/bdc_08_checks.py:142-149`). The size
   and sign of the diff names the trap: a large positive overshoot is trap 1
   (subtotals); an exact 1000x is trap 5 (scale); a small negative is footnote
   cells read as negatives; a tie to the prior column is the balance-sheet map
   inverted, and check 13 says so explicitly.
2. **Look at the data, not at the code.** Both real bugs in `note/trap_log.md`
   were found by reading output. `data/interim/soi_rows.csv` carries every row
   including exclusions, with `subtotal_reason`. Find the specific rows that
   move the diff.
3. **Name the representation difference** in one sentence: "this filer labels
   its subtotals", "this filer prints maturity as MM/DD/YYYY", "this filer is an
   LP and tags PartnersCapital". If you cannot write that sentence, you do not
   yet understand the failure.
4. **Locate the shared table from section 2** that should have covered it and
   add the entry there.
5. **Re-run the reference filing and diff the panels byte for byte.** Not "does
   it still pass" - passing is not enough. Copy `data/interim/` aside first,
   then:

   ```bash
   diff -q ref/bdc_quarter_investment.csv data/interim/bdc_quarter_investment.csv
   ```

   This is the step that catches an extension leaking into filings it was not
   meant to touch. A rule intended for undrawn revolvers once wrote
   `principal_amount = 0.0` onto 50 equity and warrant rows of the reference
   filing; every one of the 16 checks passed, because the field is nullable for
   equity and the tie-out was unaffected. **Only the diff saw it.**

   Note the tests are pinned to the 2026-06-30 filing and read
   `data/interim/`, so re-run that filing before `pytest` - a backfill leaves
   interim holding whatever it parsed last, and the failures look alarming and
   mean nothing.
6. **Append to `note/trap_log.md`** (format in 6.3) and, when you made a
   judgement a different reasonable parser could have made differently, add it
   to `note/parsing_decisions.md`.

### 6.2 Never, in order to make a check pass

These are the failure modes that turn a wrong dataset into a green one. None of
them is ever the right fix.

- **Never widen a tolerance.** 0.1% on the tie-out, 0.05%/1 USD on the balance
  sheet identity, 0.5% on NAV per share, 0.1% on the XBRL cross-check. ARCC's
  residual is 0.001022% and `note/trap_log.md:69` records that no tolerance was
  widened anywhere to get there. A tie-out that needs 1% is a parse error.
  Across all 88 ARCC filings none of these has ever moved, and none should.

  A **plausibility bound** is a different object from a tolerance, and exactly
  one has ever been changed: check 16's maturity window, from `[-2y, +30y]` to
  `[-10y, +40y]`. The bar is high and was met only because the offending dates
  were traced back to the filing text first - NECCO's `due 1/2018` (a borrower
  that failed in 2018 and was still held in 2020) and Sunrun's `due 2/2055`
  (35-year solar paper). **The data was right and the bound was wrong.** If you
  cannot quote the filing text that proves the bound wrong, it is not wrong. A
  tolerance is never in this category: it measures agreement between two numbers
  that must agree, so a failure is always a parse error.

  Three further bound corrections have met that bar, each with the filing text
  in hand: the maturity window split so that a warrant expiring `8/2100` is
  allowed while a *loan* maturing in 2100 still fails; the fv/cost ratio gained
  a materiality floor of 10 presentation granules, because a position printed
  as `0.1` against `0.6` in millions is one digit each and its ratio is pure
  rounding; and C4's period-over-period bound became gap-aware. In every case
  the columns involved were already tied out independently on the same run
  (checks 13, 14 and 15), which is what separates "the bound is wrong" from
  "the parse is wrong".

- **An exemption you cannot verify is not an exemption.** Where a rule is
  relaxed, the gate must be able to see the evidence in the panel itself.
  Unit-denominated debt earned its exemption because `shares_units` was added
  to the panel, so check 2 re-derives the exemption independently. By contrast,
  two drawn revolvers in ARCC 2022 Q1 state no principal anywhere and have no
  such evidence - that filing stays excluded rather than take the parser's word
  for it.
- **Never drop, filter, or exclude rows to make a sum tie.** Excluding a row is
  a claim that it is not a position, and that claim must be shape-based and
  written to `soi_rows.csv` with a `subtotal_reason`.
- **Never scale a number to close a gap.** Scale comes from the table's own
  banner or the run fails.
- **Never hardcode** a CIK, a table index, a footnote number, a column index, or
  a row index. All four are discovered at runtime today; keep it that way.
- **Never let an unmapped instrument fall into "other".** `map_investment_type`
  raises for a reason (`code/bdc_06_normalize.py:255-267`); "other" is reserved
  for things explicitly decided to belong there.
- **Never infer `period_end_prior`** as period_end minus a quarter or a year. It
  is read from the column header (`plan_v1.md:78`).
- **Never sum both Schedules of Investments**, and never resolve an ambiguous
  as-of date by picking the first fragment.
- **Never relax an "exactly one" / "exactly two" assertion** to make a run
  proceed. Those aborts are the pipeline refusing to guess. Tighten what feeds
  them instead - that is what the standalone-heading guard did.
- **Never turn a FAIL into a WARN or a SKIP**, and never make the gate's ground
  truth come from the parser. Checks 5, 14 and 15 derive their own values from
  the filing and the XBRL; feeding them parser output makes them tautologies.
- **Never write to `output/` from a stage.** Only the gate promotes, only on
  green (`code/bdc_08_checks.py:912-927`).
- **Never add a per-filer branch, per-filer module, or per-filer override file.**

If a check genuinely does not apply to a filing, it becomes a SKIP with an
explicit stated condition, the way check 14 does when the filing reports no
total cost (`code/bdc_08_checks.py:707-715`). A SKIP is a documented gap, not a
pass, and it belongs in the trap log.

### 6.3 Recording the extension

Every extension gets appended to `note/trap_log.md`, with the filing that forced
it. The log is the only record of what has actually been seen versus what is
merely handled.

```markdown
## <TICKER> <form> period end <YYYY-MM-DD>, accession <nnnnnnnnnn-nn-nnnnnn>

| Field | Value |
|---|---|
| Symptom | the check that failed and its printed diff, verbatim |
| Signature | the observable in the filing that identifies this representation |
| Representation difference | one sentence |
| Extension | table extended, file:line, entry added |
| Serves | why this entry is filer-agnostic and not a branch |
| ARCC re-run | pass / fail after the change |
| Residual | the tie-out delta after the fix, in USD and percent |
| New SKIPs | any check that now skips, and its stated condition |
```

Also update the trap table at the top of `note/trap_log.md` when a filing moves
a trap from "handled, not present" to "fired" - trap 4 (parenthesised negatives)
is the obvious candidate, and it is currently untested against real data.

---

## 7. Assembling many filings into two full panels

`code/bdc_10_backfill.py` runs the whole single-filing pipeline once per filing
and accumulates what the gate promoted. It does not modify any stage.

```bash
python3 code/bdc_10_backfill.py --ticker ARCC                 # every 10-K/10-Q on EDGAR
python3 code/bdc_10_backfill.py --ticker ARCC --from 2013-01-01 --to 2020-12-31
python3 code/bdc_10_backfill.py --ticker ARCC --limit 5       # newest 5, for a smoke test
python3 code/bdc_10_backfill.py --ticker ARCC --force         # ignore resume state
```

Outputs:

| Path | Contents |
|---|---|
| `output/panel/bdc_quarter.csv` (+ `.parquet`) | one row per (cik, period_end) across every filing that passed |
| `output/panel/bdc_quarter_investment.csv` (+ `.parquet`) | every position of every passing filing |
| `note/coverage.json` | every filing on EDGAR and what happened to it, machine-readable |

### Why a driver and not a multi-filing mode in the stages

Each stage reads what the previous stage wrote at a fixed path, and all 16
checks are written against a one-row quarter panel. Making the stages
multi-filing would mean re-expressing every check over a many-row panel, which
is exactly how a per-filing tie-out becomes a cross-filing average that no
longer catches a single bad filing. **Keep the gate single-filing.** One filing
is parsed, gated and promoted in complete isolation; only then is its result
appended.

### The rules the driver must keep

1. **Fail-closed per filing.** A filing that fails the gate or raises in any
   stage contributes **nothing**. It never lands in the panel "with a caveat".
2. **The panel states its own coverage.** Every filing on EDGAR appears in
   `note/coverage.json` with either its residual or its failure reason. A panel
   whose gaps are undocumented is worse than a smaller panel, because a gap
   reads as "the filer did not report".
3. **Never fill a gap by interpolation, by carrying a value forward, or from a
   filing's comparative column.** A `_prior` column is a comparative read, not a
   filed observation of that period (`plan_v1.md:207`). If a period's own filing
   did not pass, that period is absent, full stop.
4. **Resume, do not re-derive.** The driver skips accessions already in the
   panel unless `--force`, so a long backfill survives an interruption. Per
   filing records are carried forward from the previous `coverage.json` and
   merged, because a resumed run that rebuilt the report from only what it
   attempted would list almost nothing - and a missing row reads as "never
   attempted" rather than "already done".
5. **Walk oldest first when you intend to fix things** (`--order oldest`). One
   representation difference spans an era, so processing forward in time makes
   each era's failures arrive as a contiguous block. That ordering is what
   revealed that *every* 10-K 2005-2012 failed one way and *every* 10-K
   2013-2016 failed another - both invisible when interleaved newest-first.
6. **Some filings cannot be fixed, and forcing them is the error.** Three ARCC
   filings put a business description or a borrower name in the Investment
   column - one with the filer's own typo two cells away - so the instrument is
   never named. The row is clearly debt but its lien seniority is unstated, and
   `investment_type` records exactly that. Mapping it to `other` or picking a
   lien would invent the missing fact; dropping the row would break the
   tie-out. Excluding the filing and recording why is the correct outcome.
7. **A failing filing is a finding, not a nuisance.** Work it with section 6:
   the fix is an entry in a shared table that serves every filer, and it goes in
   `note/trap_log.md`. Never add a per-filing skip list.

### Cross-filing checks (C1-C5)

These are checks no single filing can perform, in
`bdc_10_backfill.cross_checks`. A check that evaluated nothing reports **SKIP**,
never PASS.

| # | Check | Why it matters |
|---|---|---|
| C1 | assembled panel unique on (cik, period_end) | two filings claiming one period means a form or period-end collision |
| C2 | each filing's comparative column ties to the panel row parsed independently from that period's own filing | **the strongest check in the whole system**: two different documents, parsed separately, must agree. A column map inverted in one filing cannot survive it |
| C3 | every investment-panel period has a quarter-panel row | an orphaned position set means a partial promotion |
| C4 | consecutive periods plausible: 60% for pairs <= 120 days apart, a 10x band across a coverage gap | catches a scale error confined to a single filing, which per-filing check 9 cannot see. **The gap rule matters**: adjacent rows are not adjacent periods when filings are excluded, and a flat 60% bound flagged ARCC's real growth across a two-year hole |
| C5 | `nav_per_share` in [0, 1000] across every period | a cheap units check over the assembled series |

C2 is the reason to backfill in chronological blocks rather than cherry-picking
periods: it only evaluates where a filing's comparative period is *also* in the
panel, so a scattered panel leaves it mostly unevaluated and it will say so.

### Reading the coverage report

`note/coverage.json` carries per filing: form, period end, accession, gate
statuses by check id, pass/warn/skip counts, the tie-out residual in USD and
percent, and the failure reason for excluded filings. Turn it into
`note/coverage.md` for humans. Group failures **by reason, not by period** - one
representation difference usually explains a contiguous run of filings, and that
run is the extension's test set.

---

## 8. Fast orientation on a new filing

```bash
python3 code/bdc_01_resolve.py --ticker <TICKER>
python3 code/bdc_02_fetch.py
python3 code/bdc_03_extract.py     # read data/interim/extract.json before going further
python3 code/bdc_04_parse_soi.py   # then read data/interim/soi_rows.csv
python3 code/run_all.py            # full run + gate
```

`extract.json` answers most of section 3's questions in one read: SOI fragment
count, all SOI as-of dates, per-table scale, audited flags, and the discovered
non-accrual footnote number. `soi_rows.csv` answers the rest, including every
row the parser chose to exclude and why.
