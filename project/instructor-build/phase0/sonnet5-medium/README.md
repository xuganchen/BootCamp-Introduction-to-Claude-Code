# ARCC 10-Q, quarter ended 2026-06-30

Two analysis-ready tables built from Ares Capital Corporation's most recent 10-Q.

| | |
|---|---|
| Company | Ares Capital Corporation (ARCC), CIK 0001287750 |
| Why this one | Largest publicly traded BDC: $30.5bn total assets, $29.3bn investments at fair value |
| Filing | 10-Q, period 2026-06-30, filed 2026-07-29, accession 0001628280-26-050307 |
| Source | SEC EDGAR, free and public, no credentials |

## Run it

```bash
bash code/download.sh      # 6 files, ~41 MB, cached after the first run
python3 code/parse_10q.py  # writes both CSVs, then ties them out
```

Requires `lxml`. The parser exits non-zero if any tie-out fails.

Raw filings are 14-24 MB each. Do not commit `data/raw/`.

## Table 1 -- `output/financial_statements.csv`

1,764 rows. One row per (statement, line item, period, dimension). Long format,
so a balance sheet line at two dates is two rows.

| Column | Notes |
|---|---|
| `statement` | Balance Sheets, Operations, Stockholders' Equity, Cash Flows |
| `statement_no`, `line_order` | Presentation order as filed; sort on `line_order` to rebuild the statement |
| `line_item` | Label as printed in the filing |
| `xbrl_tag` | e.g. `us-gaap:Assets`. The stable key across filers and quarters; `line_item` is not |
| `parent_tag` | Parent in the presentation tree, for subtotal structure |
| `period_start`, `period_end`, `period_type` | `instant` lines have `period_start` blank. Q and YTD columns share `period_end` and differ on `period_start` |
| `dimensions` | `Axis=Member` for disaggregated lines; blank for the consolidated total |
| `is_consolidated_total` | True on the 297 rows that are the face-of-statement figure |
| `value`, `unit` | `USD`, `shares`, or `USD/shares`. Values are as-reported, unscaled |
| `decimals` | XBRL rounding. `-6` means the figure is stated to the nearest million |

Filter `is_consolidated_total == True` for the statements as printed; keep the
rest for the disaggregations (investments by affiliation, equity by component).

## Table 2 -- `output/schedule_of_investments.csv`

2,848 rows: 1,439 holdings at 2026-06-30 and 1,409 at 2025-12-31 (the 10-Q
restates the prior year end in full), across 593 issuers and 24 industries.

| Column | Notes |
|---|---|
| `as_of_date` | `2026-06-30` or `2025-12-31` |
| `issuer`, `business_description`, `industry` | Printed once per issuer block in the filing; carried down to every holding here |
| `affiliation` | Derived from the issuer footnote: `(5)` controlled, `(4)` non-controlled affiliate, else non-affiliate |
| `investment_type` | e.g. First lien senior secured loan, Preferred units |
| `coupon_text` | All-in rate as printed, e.g. `11.62% (4.50% PIK)` |
| `interest_rate_pct`, `pik_rate_pct`, `spread_pct` | From XBRL, in percent |
| `reference_rate`, `reference_rate_reset` | e.g. `SOFR` and `SOFR (Q)` |
| `acquisition_date`, `maturity_date` | `MM/YYYY` as printed |
| `principal_usd`, `amortized_cost_usd`, `fair_value_usd`, `shares_units` | From XBRL, in dollars |
| `footnotes`, `issuer_footnotes` | Raw markers, e.g. `(2)(9)` |
| `investment_identifier`, `context_id` | Join keys back to the XBRL instance |

Expected blanks: equity positions have no coupon, spread, maturity, or
principal; fixed-rate loans have no reference rate or spread; `pik_rate_pct` is
populated for the 13% of positions that pay in kind.

Not included: `% of net assets` is printed only on industry subtotals, never per
holding. Unfunded commitments are disclosed in a separate note keyed by issuer
rather than by holding, so they belong in a third table, not this one.

## Verification

`parse_10q.py` finishes by tying the tables to each other. All six checks pass:

```
  date             n        SOI cost    SOI fair value     BS fair value        diff  status
  2026-06-30    1439       29,674.6M         29,349.3M         29,349.0M       +0.3M  OK
  2025-12-31    1409       29,249.9M         29,484.8M         29,485.0M       -0.2M  OK

  affiliation split (footnotes 4/5) vs. balance sheet
    2026-06-30  Non-controlled affiliate             571.6M vs      572.0M  OK
    2026-06-30  Controlled affiliate               4,494.9M vs    4,495.0M  OK
    2025-12-31  Non-controlled affiliate             600.2M vs      600.0M  OK
    2025-12-31  Controlled affiliate               4,013.4M vs    4,013.0M  OK
  2026-06-30  assets 30,498.0M vs liabilities+equity 30,498.0M  OK
  2025-12-31  assets 31,235.0M vs liabilities+equity 31,235.0M  OK
```

Residuals of 0.2-0.4mn are rounding, not error: the balance sheet is tagged to
the nearest million while the schedule is stated to 0.1mn. Tolerance is 0.5mn.

The affiliation check is the informative one. It is derived independently -- from
footnote markers on the company name -- and still reproduces three separate
balance sheet lines, which would not happen if issuers, footnotes, or the
carry-down of issuer attributes were misaligned.

## Traps this filing sets

Each of these produced a plausible, wrong table before it was caught.

1. **Double-counted affiliates.** 39 positions are restated in the affiliated-
   investments note with the same XBRL tags as the schedule. Collecting fair
   value by tag alone overstates the portfolio by $5.07bn (17%). The parser only
   reads rows inside tables carrying the schedule's header signature.
2. **Rendered statements are lossy.** SEC's `R*.htm` files drop XBRL element
   names and rescale everything to millions, turning NAV per share of $19.35
   into 19,350,000. Table 1 is built from the instance and linkbases instead.
3. **Tags spill across row boundaries.** In ~80 places a holding's fact is
   opened inside the previous `<tr>`. Facts are therefore joined to rows on
   context id, never on row position.
4. **Issuer attributes are printed once.** Company name, business description,
   and the affiliation footnote appear only on the first row of each issuer
   block. Without carrying them down, 60% of holdings lose their issuer.
5. **Industry headings look like issuer rows.** Both put text in the company
   column. The distinguishing feature is that an industry heading is the only
   thing in its row.
6. **Rates are decimals in XBRL, percent in print.** 0.0865 vs 8.65%.
