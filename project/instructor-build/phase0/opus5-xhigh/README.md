# ARCC Form 10-Q, parsed

Source: Ares Capital Corporation (ARCC), the largest publicly traded BDC by total assets
($30.5bn at 2026-06-30). CIK 0001287750, Form 10-Q for the quarter ended 2026-06-30,
filed 2026-07-29, accession 0001628280-26-050307.

Primary document `arcc-20260630.htm` (24.8 MB Inline XBRL), downloaded from
`https://www.sec.gov/Archives/edgar/data/1287750/000162828026050307/`.

Rebuild with `python3 code/parse_arcc_10q.py`.

## Table 1 - `financial_statements.csv`

435 facts, tidy long format: one row per reported number. Covers all four primary
statements, both the current and comparative periods.

| statement | facts |
|---|---|
| `balance_sheet` | 64 |
| `statement_of_operations` | 183 |
| `statement_of_stockholders_equity` | 116 |
| `statement_of_cash_flows` | 72 |

| column | meaning |
|---|---|
| `statement` | which statement the fact appears in |
| `row_order` | position of the row within the printed statement |
| `section` | most recent heading above the row (`EXPENSES:`, `OPERATING ACTIVITIES:`). Carried forward; a navigation aid, not a strict grouping key |
| `line_item` | printed row label |
| `xbrl_tag` | us-gaap / arcc element name, the stable identifier for the concept |
| `context_id` | XBRL context the fact was reported under |
| `period_type` | `instant` (balance sheet dates) or `duration` (flows) |
| `period_instant`, `period_start`, `period_end` | reporting date or range |
| `dimensions` | JSON of any dimensional breakdown, e.g. equity component |
| `value_usd` | value in whole USD, signed as printed on the page |
| `value_usd_xbrl_signed` | same magnitude, signed per the XBRL element's own convention |
| `scale`, `decimals` | as tagged in the filing |

`value_usd` and `value_usd_xbrl_signed` differ where the presentation linkbase negates a
concept, which is normal in the cash flow reconciliation. Use `value_usd` to reproduce
the printed statement; use `value_usd_xbrl_signed` to compare against other filers' XBRL.

Per-share amounts (`EarningsPerShareBasic`, `NetAssetValuePerShare`) and share counts sit
in the same table and are in their natural units, not dollars.

## Table 2 - `soi_investments.csv`

2,847 rows, one per investment line in the Consolidated Schedule of Investments:
1,439 as of 2026-06-30 and 1,408 as of 2025-12-31, across 593 and 580 portfolio companies.

Identity: `cik`, `ticker`, `bdc_name`, `form`, `accession`, `period_of_report`,
`filed_date`, `period_end` (the date this line is reported as of), `line_id`.

| column | meaning |
|---|---|
| `industry` | industry heading the line is printed under |
| `portfolio_company` | company name, trailing footnote markers stripped |
| `business_description` | one-line description as printed |
| `investment_type` | tranche description, e.g. `First lien senior secured loan` |
| `coupon_pct`, `pik_pct` | all-in coupon and PIK component, in percentage points |
| `reference_rate` | e.g. `SOFR (Q)`, `SONIA (Q)`; blank for fixed-rate and equity |
| `spread_pct` | spread over the reference rate, percentage points |
| `acquisition_date`, `maturity_date` | as printed, `MM/YYYY`; maturity blank for equity |
| `shares_units` | share or unit count for equity positions |
| `principal_usd`, `amortized_cost_usd`, `fair_value_usd` | whole USD |
| `pct_of_net_assets` | populated on subtotal rows only, so blank here |
| `pct_of_shares_owned` | where disclosed |
| `footnotes`, `company_footnotes` | raw markers on the line and on the company name |
| `affiliation` | `non_controlled_non_affiliated`, `affiliated`, `controlled` |
| `source_table`, `context_id` | provenance back into the filing |

Boolean flags decoded from the footnote markers (legend in `soi_footnote_legend.csv`):
`is_pledged_as_collateral`, `is_affiliated_person`, `is_controlled`,
`is_non_qualifying_asset`, `is_non_accrual`, `has_interest_rate_floor`,
`is_sdlp_certificate`, `has_letters_of_credit_unfunded`,
`has_letters_of_credit_additional`, `fair_value_not_level_3`,
`has_unfunded_loan_commitment`, `has_unfunded_equity_commitment`,
`has_sdlp_coinvest_commitment`, `is_non_income_producing`.

Two of these need care:

- `fair_value_not_level_3` is an inverted marker. Footnote 16 reads "other than the
  investments noted by this footnote, the fair value ... is determined using unobservable
  inputs", so the marker means the line is **not** Level 3.
- `is_non_income_producing` is derived from the absence of any coupon, not from a row
  marker: footnote 3 is referenced from the Coupon column heading rather than from rows.

## Supporting files

- `soi_subtotals.csv` - 825 rows: the issuer subtotals, industry subtotals and the two
  grand totals the filing prints. `covers_line_ids` links each issuer subtotal to the
  `line_id`s it sits under.
- `soi_footnote_legend.csv` - both printed legends, 18 notes each. `soi_section` 0 is the
  2026-06-30 schedule, 1 is 2025-12-31. Both number their notes 1..18 identically; only
  the date-specific wording differs.
- `tieout_report.txt` - the verification below, regenerated on every run.

## Verification

Every check is against a number the filing prints for itself.

| check | 2026-06-30 | 2025-12-31 |
|---|---|---|
| A. sum of parsed lines vs printed Total Investments (cost and fair value) | exact | exact |
| B. each issuer subtotal vs the lines above it | 394/394 agree | 380/380 agree |
| C. SOI total vs balance sheet total investments | within $0.4m rounding | within $0.2m rounding |
| D. affiliation split vs the three balance sheet buckets | within $0.8m rounding | within $0.8m rounding |
| E. total investments / stockholders' equity vs the printed % of net assets | 211.28% vs 211.32% | 205.93% vs 205.93% |

Rounding differences in C, D and E are expected and are not parse errors: the schedule
prints tenths of millions while the balance sheet prints whole millions.

Two independent checks outside the schedule:

- Non-accrual lines are 2.38% of investments at amortized cost and 1.38% at fair value as
  of 2026-06-30, and 1.79% / 1.19% as of 2025-12-31. The filing's MD&A states 2.4% / 1.4%
  and 1.8% / 1.2%.
- The 34 lines flagged `fair_value_not_level_3` total $661.1m, against $662m of Level 1,
  Level 2 and NAV-measured investments in Note 8.

## Known issue in the source filing

Three of the 1,846 coupon facts (Adonis Bidco, Covert HoldCo, Mountaineer Merger) are
tagged `scale="0"` where every other rate carries `scale="-2"`. Taking the XBRL value at
face value reports a 9.48% coupon as 948%. The parser reads rate columns as printed, so
the output is correct; the mis-tagging is in ARCC's filing, not in the parse.
