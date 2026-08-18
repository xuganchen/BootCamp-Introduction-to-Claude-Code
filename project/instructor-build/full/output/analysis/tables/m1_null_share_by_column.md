**Field completeness: null share by column, in-window investment panel**

*Period covered: 2018Q3-2026Q2. Computed on 31,067 of 31,067 investment-panel rows (100.0% of the window panel). Null share is computed on every in-window row of the panel.*

| column              |   non_null_rows |   null_rows |   null_share_pct |
|:--------------------|----------------:|------------:|-----------------:|
| pct_of_net_assets   |               0 |       31067 |           100.00 |
| shares_units        |            5761 |       25306 |            81.46 |
| spread_bps          |           19137 |       11930 |            38.40 |
| all_in_rate_pct     |           21776 |        9291 |            29.91 |
| reference_rate      |           21776 |        9291 |            29.91 |
| principal_amount    |           21896 |        9171 |            29.52 |
| maturity_date       |           22195 |        8872 |            28.56 |
| source_scale        |           31067 |           0 |             0.00 |
| is_non_accrual      |           31067 |           0 |             0.00 |
| fair_value          |           31067 |           0 |             0.00 |
| cost                |           31067 |           0 |             0.00 |
| cik                 |           31067 |           0 |             0.00 |
| bdc_name            |           31067 |           0 |             0.00 |
| investment_type_raw |           31067 |           0 |             0.00 |
| investment_type     |           31067 |           0 |             0.00 |
| industry            |           31067 |           0 |             0.00 |
| borrower            |           31067 |           0 |             0.00 |
| position_id         |           31067 |           0 |             0.00 |
| accession           |           31067 |           0 |             0.00 |
| period_end          |           31067 |           0 |             0.00 |
| source_url          |           31067 |           0 |             0.00 |

*Note: pct_of_net_assets is 100% null and must never be used. industry carries 68 raw labels that collapse to 57 once punctuation and taxonomy variants are normalized (industry_norm); use the normalized column. In the quarter panel nav_per_share is 90% null (27 of 30 quarters), so NAV per share is derived as net_assets / shares_outstanding throughout this report. The 2018Q3-2026Q2 stamp is not continuous: 30 of the 32 calendar quarters in that span are present; 2019Q3 and 2022Q1 are absent from the panel and contribute no rows here.*

*Source: author's calculations on the ARCC BDC panel built from SEC EDGAR 10-K/10-Q filings.*
