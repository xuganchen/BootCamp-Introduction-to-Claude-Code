**Null share of rate and term fields by investment type**

*Period covered: 2018Q3-2026Q2. Computed on 31,067 of 31,067 investment-panel rows (100.0% of the window panel). Every in-window position row is classified into exactly one investment type.*

| investment_type   |   positions |   share_of_positions_pct |   share_of_pooled_fair_value_pct |   null_reference_rate_pct |   null_spread_bps_pct |   null_all_in_rate_pct_pct |   null_maturity_date_pct |   null_principal_amount_pct |
|:------------------|------------:|-------------------------:|---------------------------------:|--------------------------:|----------------------:|---------------------------:|-------------------------:|----------------------------:|
| first lien        |       18868 |                    60.73 |                            50.01 |                      6.50 |                 10.70 |                       6.50 |                     1.70 |                        0.00 |
| equity            |        6231 |                    20.06 |                            14.43 |                     96.20 |                100.00 |                      96.20 |                    99.90 |                      100.00 |
| second lien       |        1982 |                     6.38 |                            16.07 |                      5.10 |                 10.40 |                       5.10 |                     0.00 |                        0.10 |
| preferred         |        1979 |                     6.37 |                             7.88 |                     45.90 |                 93.60 |                      45.90 |                    94.30 |                      100.00 |
| subordinated      |        1041 |                     3.35 |                            11.37 |                      9.80 |                 63.40 |                       9.80 |                     0.10 |                        0.70 |
| other             |         966 |                     3.11 |                             0.24 |                     99.80 |                 99.90 |                      99.80 |                    47.50 |                       98.70 |

*Note: Positions are counted equal-weight. share_of_pooled_fair_value_pct is weighted by fair value POOLED over all 30 quarter-ends, so a position held for k quarters enters k times; read it as a share of position-quarter fair value, not as a portfolio weight at any one date. Null shares use each type's own position count as the denominator. Nulls in equity and preferred are structural, not parse failures: those instruments carry no coupon or stated maturity in the Schedule of Investments. The 2018Q3-2026Q2 stamp is not continuous: 30 of the 32 calendar quarters in that span are present; 2019Q3 and 2022Q1 are absent from the panel and contribute no rows here.*

*Source: author's calculations on the ARCC BDC panel built from SEC EDGAR 10-K/10-Q filings.*
