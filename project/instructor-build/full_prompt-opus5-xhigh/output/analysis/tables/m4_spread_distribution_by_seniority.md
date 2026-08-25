**Fair-value weighted spread distribution by seniority**

*Period covered: 2018Q3-2026Q2. Computed on 19,009 of 31,067 investment-panel rows (61.2% of the window panel). Debt-like positions only (21,891 rows); of those 19,009 carry a parsed spread_bps. Quantiles are fair-value weighted. Equity and preferred positions are excluded by construction, which is why they do not appear as missing spreads here.*

| scope                   | seniority    |   positions |   positions_with_spread |   median_spread_bps |   p25_spread_bps |   p75_spread_bps |   iqr_bps |   fv_with_spread_usd_mm |   fv_coverage_pct_of_cell |   fv_coverage_pct_of_debt_book |
|:------------------------|:-------------|------------:|------------------------:|--------------------:|-----------------:|-----------------:|----------:|------------------------:|--------------------------:|-------------------------------:|
| pooled 2018Q3-2026Q2    | first lien   |       18868 |                   16853 |              565.00 |           500.00 |           640.00 |    140.00 |              288,246.10 |                     93.42 |                          60.32 |
| pooled 2018Q3-2026Q2    | second lien  |        1982 |                    1775 |              788.00 |           700.00 |           850.00 |    150.00 |               92,912.90 |                     93.70 |                          19.44 |
| pooled 2018Q3-2026Q2    | subordinated |        1041 |                     381 |              800.00 |           750.00 |           800.00 |     50.00 |               53,366.00 |                     76.07 |                          11.17 |
| latest quarter (2026Q2) | first lien   |         965 |                     883 |              525.00 |           475.00 |           575.00 |    100.00 |               16,606.60 |                     95.81 |                          73.65 |
| latest quarter (2026Q2) | second lien  |          25 |                      18 |              675.00 |           633.89 |           775.00 |    141.11 |                1,090.20 |                     84.28 |                           4.84 |
| latest quarter (2026Q2) | subordinated |          53 |                      31 |              676.33 |           650.00 |           784.58 |    134.58 |                3,191.50 |                     81.37 |                          14.15 |

*Note: Quantiles are fair-value weighted over positions with a parsed spread. 'fv_coverage_pct_of_cell' is the share of that seniority bucket's fair value that carries a spread; the subordinated bucket is the weak cell and its median should be read as indicative only.*

*Source: author's calculations on the ARCC BDC panel built from SEC EDGAR 10-K/10-Q filings.*
