**Marks by spread bucket, latest 8 quarters**

*Period covered: 2024Q3-2026Q2. Computed on 7,019 of 31,067 investment-panel rows (22.6% of the window panel). Debt-like positions in the latest 8 quarters (2024Q3-2026Q2) with a parsed spread and positive cost. Buckets are equal-count quantile cuts on spread_bps; ties at round spread levels collapse the requested 10 cuts into 9 buckets, each holding roughly a tenth of positions and NOT a tenth of fair value. FV/cost inside each bucket is fair-value weighted. Fair-value sums are pooled over 8 quarter ends, so a position held throughout is counted 8 times. Non-accrual positions are absent here by construction: only 0 of 156 non-accrual debt positions in this window carry a parsed spread, so a bucket cut on spread cannot contain them.*

|   bucket | spread_range_bps   |   positions |   spread_bps_min |   spread_bps_max |   median_spread_bps |   fair_value_usd_mm |   fv_over_cost |   pct_marked_below_cost_by_fv |   non_accrual_positions |
|---------:|:-------------------|------------:|-----------------:|-----------------:|--------------------:|--------------------:|---------------:|------------------------------:|------------------------:|
|        1 | 75-450             |    1,097.00 |            75.00 |           450.00 |              450.00 |           17,205.30 |           0.98 |                         46.39 |                    0.00 |
|        2 | 468-475            |    1,111.00 |           468.00 |           475.00 |              475.00 |           20,608.80 |           1.00 |                         36.68 |                    0.00 |
|        3 | 480-500            |      982.00 |           480.00 |           500.00 |              500.00 |           21,250.00 |           1.00 |                         34.63 |                    0.00 |
|        4 | 508-525            |      719.00 |           508.00 |           525.00 |              525.00 |           15,720.00 |           0.99 |                         32.26 |                    0.00 |
|        5 | 533-550            |      763.00 |           533.00 |           550.00 |              550.00 |           14,615.90 |           1.00 |                         31.94 |                    0.00 |
|        6 | 563-575            |      416.00 |           563.00 |           575.00 |              575.00 |            9,687.50 |           0.98 |                         48.91 |                    0.00 |
|        7 | 600-625            |      623.00 |           600.00 |           625.00 |              600.00 |            9,282.40 |           0.97 |                         47.39 |                    0.00 |
|        8 | 650-700            |      681.00 |           650.00 |           700.00 |              650.00 |           19,463.50 |           0.97 |                         48.53 |                    0.00 |
|        9 | 725-1215           |      627.00 |           725.00 |         1,215.00 |              800.00 |           29,297.50 |           0.98 |                         46.70 |                    0.00 |

*Note: Equal-count spread buckets (9 of a requested 10; ties at round spread levels collapse the cuts). FV/cost below 1.00 means the bucket is marked below cost. Read as association, not causation.*

*Source: author's calculations on the ARCC BDC panel built from SEC EDGAR 10-K/10-Q filings.*
