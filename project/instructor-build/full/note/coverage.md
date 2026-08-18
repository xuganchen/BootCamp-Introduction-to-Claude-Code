# Coverage - ARES CAPITAL CORP (ARCC), CIK 1287750

Produced by `code/bdc_10_backfill.py`, rendered by `code/bdc_11_coverage.py`.
Every filing below was parsed in isolation by the full single-filing
pipeline and gated by the 16 checks. **A filing that failed contributes
nothing to the panel** - no partial rows, no interpolation, no values
borrowed from another filing's comparative column.

## Summary

| | Count |
|---|---|
| 10-K / 10-Q on EDGAR | 88 |
| Targeted this run | 88 |
| **In the panel (gate green)** | **50** |
| Excluded (gate failed or stage raised) | 38 |
| Positions in the investment panel | 37,197 |
| Panel span | 2005-03-31 to 2026-06-30 |

Coverage: **50 of 88 filings (57%)**.

Against the baseline run: **5 -> 50** filings in the panel, 45 gained, 0 lost.

## Cross-filing checks

Checks no single filing can perform. A check that evaluated nothing
reports SKIP, never PASS.

| # | Status | Check | Detail |
|---|---|---|---|
| C1 | PASS | assembled bdc_quarter unique on (cik, period_end) | 50 row(s), 0 duplicated |
| C2 | PASS | comparative column ties to the independently parsed prior filing | 112 comparison(s) across 28 linked filing pair(s), 0 mismatch(es) |
| C3 | PASS | every investment-panel period has a quarter-panel row | 50 period(s) in the investment panel, 0 orphaned |
| C4 | PASS | consecutive periods plausible (60% adjacent, 10x across a gap) | 50 period(s) in sequence, 13 pair(s) span a coverage gap, 0 implausible jump(s) |
| C5 | PASS | nav_per_share within [0, 1000] across every period | 3 non-null nav_per_share value(s), 0 outside the band |

## Coverage by year

| Year | Filings | In panel | |
|---|---|---|---|
| 2026 | 2 | 2 | `##` |
| 2025 | 4 | 4 | `####` |
| 2024 | 4 | 4 | `####` |
| 2023 | 4 | 4 | `####` |
| 2022 | 4 | 3 | `###.` |
| 2021 | 4 | 4 | `####` |
| 2020 | 4 | 4 | `####` |
| 2019 | 4 | 3 | `###.` |
| 2018 | 4 | 2 | `##..` |
| 2017 | 4 | 0 | `....` |
| 2016 | 4 | 1 | `#...` |
| 2015 | 4 | 3 | `###.` |
| 2014 | 4 | 1 | `#...` |
| 2013 | 4 | 0 | `....` |
| 2012 | 4 | 2 | `##..` |
| 2011 | 4 | 3 | `###.` |
| 2010 | 4 | 1 | `#...` |
| 2009 | 4 | 3 | `###.` |
| 2008 | 4 | 2 | `##..` |
| 2007 | 4 | 0 | `....` |
| 2006 | 4 | 1 | `#...` |
| 2005 | 4 | 3 | `###.` |
| 2004 | 2 | 0 | `..` |

## Field completeness inside the panel

Row coverage is not field coverage. A filing can pass every check and
still leave a nullable field empty, because the filing does not print it
in a form this parser reads. Nullable fields are listed here so the gap
is visible rather than discovered later in analysis.

| Panel | Field | Non-null | Of | % |
|---|---|---|---|---|
| quarter | `nav_per_share` | 3 | 50 | 6% |
| quarter | `shares_outstanding` | 50 | 50 | 100% |
| quarter | `total_debt_outstanding` | 46 | 50 | 92% |
| quarter | `total_investments_fv` | 50 | 50 | 100% |
| quarter | `net_assets` | 50 | 50 | 100% |
| investment | `principal_amount` | 25,622 | 37,197 | 69% |
| investment | `cost` | 37,197 | 37,197 | 100% |
| investment | `maturity_date` | 25,899 | 37,197 | 70% |
| investment | `reference_rate` | 25,336 | 37,197 | 68% |
| investment | `spread_bps` | 21,381 | 37,197 | 57% |
| investment | `all_in_rate_pct` | 25,336 | 37,197 | 68% |
| investment | `industry` | 37,197 | 37,197 | 100% |
| investment | `pct_of_net_assets` | 0 | 37,197 | 0% |

## Exclusions, grouped by reason

One representation difference normally explains a contiguous block of
filings. The block is the test set for the extension that fixes it.

| Failure family | Filings | Period span | Stage |
|---|---|---|---|
| no balance sheet located | 8 | 2005-12-31 to 2012-12-31 | parse |
| verification gate failed | 8 | 2008-09-30 to 2017-12-31 | gate |
| other: bdc_06_normalize.VocabularyError | 8 | 2013-03-31 to 2019-09-30 | parse |
| no SOI located | 6 | 2004-09-30 to 2016-12-31 | parse |
| SOI header row not recognised | 5 | 2006-06-30 to 2007-09-30 | parse |
| an SOI fragment has no parseable as-of date | 1 | 2004-12-31 to 2004-12-31 | parse |
| other: bdc_04_parse_soi.SOIParseError | 1 | 2012-06-30 to 2012-06-30 | parse |
| debt rows with no principal_amount | 1 | 2022-03-31 to 2022-03-31 | parse |

### no balance sheet located (8 filings)

Periods: 2005-12-31 to 2012-12-31

Representative message:

```
bdc_03_extract.ExtractionError: no balance sheet found (looked for CONSOLIDATED BALANCE SHEET(S) / STATEMENTS OF ASSETS AND LIABILITIES)
```

### verification gate failed (8 filings)

Periods: 2008-09-30 to 2017-12-31

Representative message:

```
gate FAIL on check(s) [13]
```

### other: bdc_06_normalize.VocabularyError (8 filings)

Periods: 2013-03-31 to 2019-09-30

Representative message:

```
bdc_06_normalize.VocabularyError: investment_type_raw values not covered by the controlled vocabulary: [('($23,674 par due 4/2018)', 1), ('Senior secured revolving', 1), ('($17,103 par due 8/2014)', 1), ('($11,350 par due 8/2017)', 1)]
```

### no SOI located (6 filings)

Periods: 2004-09-30 to 2016-12-31

Representative message:

```
bdc_03_extract.ExtractionError: no Schedule of Investments fragments found
```

### SOI header row not recognised (5 filings)

Periods: 2006-06-30 to 2007-09-30

Representative message:

```
bdc_04_parse_soi.SOIParseError: no SOI header row found; required ['company', 'cost', 'fair_value', 'investment'], first row seen: ['Company {1}', '', 'Industry', '', 'Investment', '', 'Interest {13}', '', 'Initial Acquisition Date', '', 'Amortized Cost', '', 'Fair Value', '', 'Fair Value Per Unit',
```

### an SOI fragment has no parseable as-of date (1 filings)

Periods: 2004-12-31 to 2004-12-31

Representative message:

```
bdc_03_extract.ExtractionError: SOI fragments with no parseable as-of date: [15, 16, 17]
```

### other: bdc_04_parse_soi.SOIParseError (1 filings)

Periods: 2012-06-30 to 2012-06-30

Representative message:

```
bdc_04_parse_soi.SOIParseError: 1 position rows have no borrower after carry-forward
```

### debt rows with no principal_amount (1 filings)

Periods: 2022-03-31 to 2022-03-31

Representative message:

```
ValueError: 2 debt-type rows have no principal_amount (plan section 3.2: principal_amount is non-null for every debt-type row)
```

## Every filing

| Form | Period end | Accession | Status | Positions | Tie-out | Note |
|---|---|---|---|---|---|---|
| 10-Q | 2026-06-30 | 0001628280-26-050307 | IN PANEL (1W/0S) | 1,439 | 0.001022% | |
| 10-Q | 2026-03-31 | 0001628280-26-027688 | IN PANEL (1W/0S) | 1,419 | 0.001017% | |
| 10-K | 2025-12-31 | 0001287750-26-000006 | IN PANEL (1W/0S) | 1,408 | -0.000678% | |
| 10-Q | 2025-09-30 | 0001287750-25-000046 | IN PANEL (1W/1S) | 1,383 | -0.001394% | |
| 10-Q | 2025-06-30 | 0001287750-25-000038 | IN PANEL (1W/1S) | 1,354 | 0.001434% | |
| 10-Q | 2025-03-31 | 0001287750-25-000020 | IN PANEL (1W/1S) | 1,322 | 0.001106% | |
| 10-K | 2024-12-31 | 0001287750-25-000007 | IN PANEL (1W/1S) | 1,301 | -0.001871% | |
| 10-Q | 2024-09-30 | 0001287750-24-000054 | IN PANEL (1W/1S) | 1,249 | 0.000772% | |
| 10-Q | 2024-06-30 | 0001287750-24-000039 | IN PANEL (1W/1S) | 1,235 | 0.001602% | |
| 10-Q | 2024-03-31 | 0001287750-24-000028 | IN PANEL (1W/1S) | 1,184 | 0.001297% | |
| 10-K | 2023-12-31 | 0001287750-24-000011 | IN PANEL (1W/1S) | 1,157 | -0.001312% | |
| 10-Q | 2023-09-30 | 0001287750-23-000045 | IN PANEL (1W/1S) | 1,117 | -0.002280% | |
| 10-Q | 2023-06-30 | 0001287750-23-000036 | IN PANEL (1W/1S) | 1,161 | 0.002326% | |
| 10-Q | 2023-03-31 | 0001287750-23-000021 | IN PANEL (1W/1S) | 1,032 | 0.000000% | |
| 10-K | 2022-12-31 | 0001287750-23-000010 | IN PANEL (1W/1S) | 1,021 | -0.000918% | |
| 10-Q | 2022-09-30 | 0001287750-22-000052 | IN PANEL (1W/1S) | 991 | -0.002343% | |
| 10-Q | 2022-06-30 | 0001287750-22-000040 | IN PANEL (2W/3S) | 973 | 0.000945% | |
| 10-Q | 2022-03-31 | 0001287750-22-000021 | excluded | - | - | debt rows with no principal_amount |
| 10-K | 2021-12-31 | 0001287750-22-000007 | IN PANEL (2W/3S) | 850 | 0.002499% | |
| 10-Q | 2021-09-30 | 0001287750-21-000074 | IN PANEL (2W/3S) | 791 | -0.001697% | |
| 10-Q | 2021-06-30 | 0001287750-21-000063 | IN PANEL (2W/3S) | 786 | -0.000584% | |
| 10-Q | 2021-03-31 | 0001287750-21-000035 | IN PANEL (2W/3S) | 791 | 0.000648% | |
| 10-K | 2020-12-31 | 0001287750-21-000005 | IN PANEL (2W/3S) | 793 | 0.000645% | |
| 10-Q | 2020-09-30 | 0001287750-20-000038 | IN PANEL (2W/3S) | 753 | 0.000000% | |
| 10-Q | 2020-06-30 | 0001287750-20-000031 | IN PANEL (2W/3S) | 766 | -0.000722% | |
| 10-Q | 2020-03-31 | 0001287750-20-000022 | IN PANEL (2W/3S) | 819 | 0.001392% | |
| 10-K | 2019-12-31 | 0001287750-20-000008 | IN PANEL (2W/3S) | 745 | -0.001386% | |
| 10-Q | 2019-09-30 | 0001287750-19-000029 | excluded | - | - | other: bdc_06_normalize.VocabularyError |
| 10-Q | 2019-06-30 | 0001287750-19-000021 | IN PANEL (2W/3S) | 821 | 0.001539% | |
| 10-Q | 2019-03-31 | 0001287750-19-000013 | IN PANEL (2W/3S) | 844 | -0.003062% | |
| 10-K | 2018-12-31 | 0001287750-19-000004 | IN PANEL (2W/3S) | 792 | -0.002416% | |
| 10-Q | 2018-09-30 | 0001287750-18-000025 | IN PANEL (2W/3S) | 770 | -0.004456% | |
| 10-Q | 2018-06-30 | 0001287750-18-000020 | excluded | - | - | other: bdc_06_normalize.VocabularyError |
| 10-Q | 2018-03-31 | 0001287750-18-000015 | excluded | - | - | other: bdc_06_normalize.VocabularyError |
| 10-K | 2017-12-31 | 0001287750-18-000007 | excluded | - | - | verification gate failed |
| 10-Q | 2017-09-30 | 0001287750-17-000017 | excluded | - | - | verification gate failed |
| 10-Q | 2017-06-30 | 0001287750-17-000012 | excluded | - | - | verification gate failed |
| 10-Q | 2017-03-31 | 0001628280-17-004707 | excluded | - | - | verification gate failed |
| 10-K | 2016-12-31 | 0001047469-17-000808 | excluded | - | - | no SOI located |
| 10-Q | 2016-09-30 | 0001104659-16-153937 | excluded | - | - | verification gate failed |
| 10-Q | 2016-06-30 | 0001104659-16-136353 | excluded | - | - | verification gate failed |
| 10-Q | 2016-03-31 | 0001104659-16-117420 | IN PANEL (1W/3S) | 472 | 0.000000% | |
| 10-K | 2015-12-31 | 0001047469-16-010353 | excluded | - | - | no SOI located |
| 10-Q | 2015-09-30 | 0001104659-15-075535 | IN PANEL (1W/3S) | 437 | 0.000000% | |
| 10-Q | 2015-06-30 | 0001104659-15-055586 | IN PANEL (1W/3S) | 422 | 0.000000% | |
| 10-Q | 2015-03-31 | 0001104659-15-033385 | IN PANEL (1W/3S) | 415 | 0.000000% | |
| 10-K | 2014-12-31 | 0001047469-15-001240 | excluded | - | - | no SOI located |
| 10-Q | 2014-09-30 | 0001104659-14-076197 | IN PANEL (1W/3S) | 416 | 0.000000% | |
| 10-Q | 2014-06-30 | 0001104659-14-056618 | excluded | - | - | other: bdc_06_normalize.VocabularyError |
| 10-Q | 2014-03-31 | 0001104659-14-034914 | excluded | - | - | other: bdc_06_normalize.VocabularyError |
| 10-K | 2013-12-31 | 0001047469-14-001349 | excluded | - | - | no SOI located |
| 10-Q | 2013-09-30 | 0001104659-13-080832 | excluded | - | - | other: bdc_06_normalize.VocabularyError |
| 10-Q | 2013-06-30 | 0001104659-13-060139 | excluded | - | - | other: bdc_06_normalize.VocabularyError |
| 10-Q | 2013-03-31 | 0001104659-13-037917 | excluded | - | - | other: bdc_06_normalize.VocabularyError |
| 10-K | 2012-12-31 | 0001047469-13-001751 | excluded | - | - | no balance sheet located |
| 10-Q | 2012-09-30 | 0001104659-12-073940 | IN PANEL (0W/4S) | 360 | 0.000000% | |
| 10-Q | 2012-06-30 | 0001104659-12-054906 | excluded | - | - | other: bdc_04_parse_soi.SOIParseError |
| 10-Q | 2012-03-31 | 0001104659-12-034123 | IN PANEL (0W/4S) | 353 | 0.000000% | |
| 10-K | 2011-12-31 | 0001047469-12-001679 | excluded | - | - | no balance sheet located |
| 10-Q | 2011-09-30 | 0001104659-11-061830 | IN PANEL (0W/4S) | 340 | 0.000000% | |
| 10-Q | 2011-06-30 | 0001104659-11-043387 | IN PANEL (0W/4S) | 379 | 0.000000% | |
| 10-Q | 2011-03-31 | 0001104659-11-025059 | IN PANEL (0W/4S) | 411 | 0.000000% | |
| 10-K | 2010-12-31 | 0001047469-11-001575 | excluded | - | - | no balance sheet located |
| 10-Q | 2010-09-30 | 0001104659-10-055721 | excluded | - | - | verification gate failed |
| 10-Q | 2010-06-30 | 0001104659-10-042122 | IN PANEL (0W/4S) | 460 | 0.000000% | |
| 10-Q | 2010-03-31 | 0001104659-10-027004 | excluded | - | - | no balance sheet located |
| 10-K | 2009-12-31 | 0001047469-10-001312 | excluded | - | - | no balance sheet located |
| 10-Q | 2009-09-30 | 0001104659-09-062699 | IN PANEL (0W/4S) | 279 | 0.000000% | |
| 10-Q | 2009-06-30 | 0001104659-09-047554 | IN PANEL (0W/4S) | 282 | 0.000000% | |
| 10-Q | 2009-03-31 | 0001104659-09-030209 | IN PANEL (0W/4S) | 289 | 0.000000% | |
| 10-K | 2008-12-31 | 0001047469-09-002049 | excluded | - | - | no balance sheet located |
| 10-Q | 2008-09-30 | 0001104659-08-068375 | excluded | - | - | verification gate failed |
| 10-Q | 2008-06-30 | 0001104659-08-050548 | IN PANEL (0W/4S) | 266 | 0.000000% | |
| 10-Q | 2008-03-31 | 0001104659-08-030933 | IN PANEL (0W/4S) | 255 | 0.000000% | |
| 10-K | 2007-12-31 | 0001047469-08-001879 | excluded | - | - | no SOI located |
| 10-Q | 2007-09-30 | 0001104659-07-080878 | excluded | - | - | SOI header row not recognised |
| 10-Q | 2007-06-30 | 0001104659-07-060422 | excluded | - | - | SOI header row not recognised |
| 10-Q | 2007-03-31 | 0001104659-07-037848 | excluded | - | - | SOI header row not recognised |
| 10-K | 2006-12-31 | 0001047469-07-001639 | excluded | - | - | no balance sheet located |
| 10-Q | 2006-09-30 | 0001104659-06-072872 | excluded | - | - | SOI header row not recognised |
| 10-Q | 2006-06-30 | 0001104659-06-052686 | excluded | - | - | SOI header row not recognised |
| 10-Q | 2006-03-31 | 0001104659-06-031759 | IN PANEL (0W/4S) | 111 | -0.000000% | |
| 10-K | 2005-12-31 | 0001104659-06-012366 | excluded | - | - | no balance sheet located |
| 10-Q | 2005-09-30 | 0001104659-05-055036 | IN PANEL (0W/4S) | 67 | 0.000000% | |
| 10-Q | 2005-06-30 | 0001104659-05-037290 | IN PANEL (0W/4S) | 61 | 0.000000% | |
| 10-Q | 2005-03-31 | 0001104659-05-020153 | IN PANEL (0W/4S) | 55 | 0.000000% | |
| 10-K | 2004-12-31 | 0001104659-05-013856 | excluded | - | - | an SOI fragment has no parseable as-of date |
| 10-Q | 2004-09-30 | 0001104659-04-036539 | excluded | - | - | no SOI located |

## What this panel is not

- Not a complete history. Excluded periods are absent, not estimated.
- The `_prior` columns are comparative reads from a filing, not filed
  observations of that period. They are never used to fill a gap.
- Positions are current-period only for each filing; no comparative SOI
  is parsed (plan section 8).
- Cross-check C2 only evaluates where a filing's comparative period is
  itself in the panel, so a panel with gaps leaves it partly unevaluated.
