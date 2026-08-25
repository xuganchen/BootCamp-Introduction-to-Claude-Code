# BDC Dataset - Working Plan (v1)

Expands `plan_v0.md` into an executable build plan. Scope: one BDC, one filing (most recent 10-Q or 10-K), two panels, hard-gated verification.

## 1. Decisions to lock before coding

| Item | Proposed default | Why |
|---|---|---|
| Target BDC | ARCC (Ares Capital Corp) | Largest listed BDC, longest filing history, cleanest Schedule of Investments (SOI) layout |
| Filing | Most recent 10-Q; fall back to 10-K if the latest period end is annual | Latest SOI plus a balance sheet in the same document |
| CIK resolution | Look up at runtime from `https://www.sec.gov/files/company_tickers.json` | Do not hardcode a CIK that has not been verified |
| Language / stack | Python 3.11+, `requests`, `lxml`, `pandas`, `pytest` | No credentials, no paid data |
| Units | All money fields stored in USD (float, dollars), not thousands or millions | Filings mix thousands and millions across tables; normalize once at parse time and record the source scale |
| Output format | CSV plus a Parquet twin; a JSON run manifest | CSV for inspection, Parquet for types |

Open question for the user: single BDC only, or should the code be written so the BDC is a parameter from day one? The plan below assumes **parameterized, run for one BDC** (same effort, no lock-in).

## 2. Data source and access rules

- SEC EDGAR only. No credentials.
- Endpoints:
  - `https://data.sec.gov/submissions/CIK##########.json` - filing history, form type, accession number, period of report, filing date.
  - `https://www.sec.gov/Archives/edgar/data/<cik>/<accession-no-dashes>/` - filing documents.
  - `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` - XBRL facts, used as an independent cross-check on the fund-level panel.
- Ground rules enforced in code: declare a descriptive `User-Agent` with a contact email, cap at 10 requests/second (sleep-based throttle), cache every fetched byte to `data/raw/` and never refetch a cached URL.
- Raw filings are 10-25 MB. `data/raw/` is gitignored; only the panels and the manifest are committed.

## 3. Schemas

### 3.1 BDC-quarter panel (`bdc_quarter.csv`)

One row per (CIK, period_end).

**Both balance-sheet columns are extracted.** A 10-Q balance sheet reports the quarter end alongside a comparative column, and a 10-K reports the fiscal year end alongside the prior fiscal year end. Taking only one column and labelling it with `periodOfReport` is the one error that every check in section 4 would pass, because the comparative column is internally consistent too. Extracting both makes the column choice explicit and testable rather than assumed.

Identity fields

| Field | Type | Source | Null allowed |
|---|---|---|---|
| bdc_name | str | submissions JSON | no |
| ticker | str | company_tickers.json | yes |
| cik | int | submissions JSON | no |
| period_end | date | `periodOfReport` | no |
| filing_date | date | `filingDate` | no |
| form_type | str | 10-Q / 10-K | no |
| accession | str | submissions JSON | no |
| source_scale | str | "thousands" / "millions" / "units" | no |
| source_url | str | archive URL | no |

Current-period fields, from the balance-sheet column whose header date equals `period_end`

| Field | Type | Source | Null allowed |
|---|---|---|---|
| total_investments_fv | float USD | balance sheet | no |
| total_assets | float USD | balance sheet | no |
| total_liabilities | float USD | balance sheet | no |
| net_assets | float USD | balance sheet | no |
| nav_per_share | float USD | balance sheet | yes |
| shares_outstanding | float | balance sheet | yes |
| total_debt_outstanding | float USD | balance sheet / notes | yes |

Comparative-period fields, from the other balance-sheet column, all suffixed `_prior`

| Field | Type | Source | Null allowed |
|---|---|---|---|
| period_end_prior | date | parsed from that column's own header, never inferred | no |
| period_end_prior_kind | str | "prior_fiscal_year_end" or "prior_quarter_end", derived by comparing `period_end_prior` to the fiscal year end in the submissions JSON | no |
| total_investments_fv_prior | float USD | balance sheet | no |
| total_assets_prior | float USD | balance sheet | no |
| total_liabilities_prior | float USD | balance sheet | no |
| net_assets_prior | float USD | balance sheet | no |
| nav_per_share_prior | float USD | balance sheet | yes |
| shares_outstanding_prior | float | balance sheet | yes |
| total_debt_outstanding_prior | float USD | balance sheet / notes | yes |

Notes on the prior column:

- `period_end_prior` is read from the column header itself. Do not compute it as `period_end` minus one quarter or one year: for a 10-Q it is normally the prior fiscal year end, not the prior quarter, so an inferred date will usually be wrong.
- The prior column is fund-level only. The investment panel stays current-period only, because the comparative Schedule of Investments, where the filing includes one at all, is a separate table and parsing it is a v2 item (section 8).
- If the filing presents more than two dated columns, fail rather than guess which is comparative.

### 3.2 BDC-quarter-investment panel (`bdc_quarter_investment.csv`)

One row per position per period. A borrower can appear many times.

| Field | Type | Null allowed |
|---|---|---|
| cik, bdc_name, period_end, accession | as above | no |
| position_id | str (deterministic hash of the row key) | no |
| borrower | str | no |
| industry | str | yes |
| investment_type | str (first lien, second lien, subordinated, equity, preferred, other) | no |
| investment_type_raw | str (verbatim from the filing) | no |
| reference_rate | str (SOFR, base rate, fixed) | yes |
| spread_bps | float | yes |
| all_in_rate_pct | float | yes |
| maturity_date | date | yes |
| principal_amount | float USD | yes (equity has none) |
| cost | float USD | yes |
| fair_value | float USD | no |
| pct_of_net_assets | float | yes |
| is_non_accrual | bool | no (default False) |
| is_subtotal_row | bool - kept out of the panel, used only during parsing | n/a |
| source_scale, source_url | as above | no |

`amount` in plan_v0 maps to `principal_amount`; equity positions legitimately have no principal, so the never-null rule from plan_v0 is relaxed for that one field and replaced by "principal_amount is non-null for every debt-type row".

## 4. Verification gate (the part that must not be soft)

Implemented as `bdc_08_checks.py`, run by `pytest`, and also called inline at the end of the pipeline. **If any check fails: log the diff, write nothing to `output/`, exit non-zero.**

Structural
1. `bdc_quarter` is unique on (cik, period_end).
2. Never-null fields per the tables above.
3. `investment` panel has more rows than unique borrowers.
4. Every `investment_type` maps into the controlled vocabulary; unmapped values fail rather than fall into "other" silently.

Column identification (the guard that makes the current/prior split meaningful)

5. The balance sheet exposes exactly two dated columns, and both header dates parse.
6. The current column's header date equals `periodOfReport` exactly. Not "closest to", not "leftmost": equal. This is the check that catches taking the comparative column by mistake.
7. `period_end_prior < period_end`, and the gap is between 80 and 380 days.
8. `period_end_prior_kind` is consistent with the fiscal year end in the submissions JSON: for a 10-Q the expected value is `prior_fiscal_year_end`; a `prior_quarter_end` result is allowed but logged as unusual, since it means this filer presents a non-standard comparative.

Accounting, applied independently to the current and the prior column
9. `total_liabilities + net_assets == total_assets`, tolerance 0.05 percent or 1 USD, whichever is larger.
10. `nav_per_share * shares_outstanding == net_assets`, tolerance 0.5 percent (rounding in reported per-share figures).

A prior-column failure here is as fatal as a current-column failure: it means the two columns were misaligned during parsing, so the current column is suspect too.

Cross-column sanity (fail, not warn)
11. `total_assets` and `total_assets_prior` differ by less than 60 percent, and likewise for `net_assets`. Two columns that look nothing alike usually mean one of them is not a balance-sheet column at all.
12. `total_assets != total_assets_prior`. Identical values across both columns almost always mean the same column was read twice.

Cross-table tie-out (the core check)
13. `sum(investment.fair_value) == bdc_quarter.total_investments_fv`, tolerance 0.1 percent, against the **current** column only. This is the check plan_v0 names, and the one a naive parse fails. It is also a second, independent confirmation that the current column was identified correctly: the SOI sum ties to one column and not the other.
14. `sum(investment.cost)` ties to reported total cost, same tolerance, when the filing reports it.

Independent cross-check
15. Both columns are compared against the XBRL `companyfacts` values for their own dates (`Assets`, `Liabilities`, `StockholdersEquity` at `period_end` and at `period_end_prior`). A mismatch beyond 0.1 percent fails. This catches scale errors that the internal checks cannot, because both sides of check 9 would be wrong by the same factor. Running it on both dates also pins each column to a date from an external source rather than from the header text alone.

Sanity bounds (fail, not warn)
16. `fair_value >= 0`; `fair_value / cost` within [0, 3] for debt rows; maturity dates within [period_end - 2y, period_end + 30y].

## 5. Known traps to handle explicitly

Each gets a named handler and a unit test with a fixture row.

1. Subtotal and total rows inside the SOI (per industry, per investment type, and the grand total) - double counting is the single most likely cause of a failed tie-out.
2. Multi-page SOI tables split across HTML tables in the same document.
3. Footnote markers glued to numbers (`1,234(5)`) and to borrower names.
4. Negative numbers in parentheses.
5. Scale headers ("in thousands, except per share data") appearing once, far above the table.
6. Non-controlled / affiliated / controlled sections repeated with their own subtotals.
7. Non-accrual positions flagged only by footnote.
8. Rate columns mixing "SOFR + 5.25%" strings, fixed rates, and PIK components.
9. Blank spacer rows and rows where the borrower name is inherited from the row above (one borrower, several tranches).
10. Equity and warrant rows with no principal, no rate, and no maturity.
11. Balance-sheet column alignment: the two dated headers sit in merged cells spanning several physical columns, often with an empty spacer column and a stray dollar-sign column between them. Mapping a value to the wrong header is silent, so the header-to-column map is built once, asserted against checks 5 to 8, and reused for every row rather than re-derived per row.
12. Header dates written in prose ("December 31, 2025 (audited)", "As of June 30, 2026") and a comparative column marked audited while the current one is not. Strip the qualifiers, keep the date, and record the audited flag in `note/`.

## 6. Folder structure

```
project_full/
  README.md              # what this is, how to run, what the checks mean
  plan_v0.md
  plan_v1.md
  requirements.txt
  code/
    bdc_01_resolve.py    # ticker -> CIK, pick the target filing
    bdc_02_fetch.py      # throttled, cached EDGAR download -> data/raw/
    bdc_03_extract.py    # locate SOI tables and the balance sheet in the document
    bdc_04_parse_soi.py  # position rows -> data/interim/
    bdc_05_parse_bs.py   # balance-sheet fields -> data/interim/
    bdc_06_normalize.py  # units, types, controlled vocabularies
    bdc_07_panels.py     # assemble the two panels
    bdc_08_checks.py     # the verification gate
    bdc_09_utils.py      # http client, throttle, cache, logging, number parsing
    run_all.py           # orchestrates 01-08, exits non-zero on any failure
  data/
    raw/                 # gitignored, filings as downloaded
    interim/             # gitignored, per-stage intermediates
  output/                # written only when every check passes
  tests/                 # pytest, fixtures cut from the real filing
  note/                  # parsing decisions, trap log, run manifest notes
```

## 7. Build order

| Step | Deliverable | Done when |
|---|---|---|
| 1 | `bdc_09_utils.py`, `bdc_01`, `bdc_02` | The target filing is on disk, cached, with a manifest recording URL, accession, and SHA-256 |
| 2 | `bdc_05_parse_bs.py` | Both columns extracted with their own header dates; checks 5 to 12 and 15 pass |
| 3 | `bdc_03` + `bdc_04` first pass | Position rows extracted, tie-out check 13 expected to **fail** initially |
| 4 | Trap handlers from section 5 | Check 13 passes at 0.1 percent against the current column |
| 5 | `bdc_06`, `bdc_07` | Both panels written to `data/interim/` with final schemas |
| 6 | `bdc_08` + `tests/` | Full gate green; deliberately corrupted fixtures make each check fail |
| 7 | `README.md`, `note/` | A cold reader can rerun end to end from the README alone |

Step 3 failing is expected and is worth recording verbatim: it is the difference between a plausible parse and a correct one.

## 8. What is out of scope for v1

- More than one BDC, more than one filing.
- The comparative Schedule of Investments. The `_prior` fields are fund-level only; there is no prior-period investment panel, so `total_investments_fv_prior` has nothing to tie out against within v1.
- Treating the `_prior` fields as a second observation. They stay as suffixed columns on the current row and are not reshaped into their own panel row, because a comparative column is not a filed period observation of its own and its fields are a subset of what the filing for that period actually reported.
- Time-series linking of positions across quarters (same borrower, same tranche).
- Any analysis, charting, or write-up on top of the panels.
- Anything requiring a login or a paid data source.
