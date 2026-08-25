# BDC Dataset Validation & Reconciliation Report

**Generated at**: `2026-08-20 16:26:58`  
**Overall Status**: `PASSED`

---

## 1. Validation Matrix Summary

| Validation Check | Specification Threshold | Observed Value | Status |
| :--- | :--- | :--- | :--- |
| Fund Panel Non-Null Integrity | No nulls in mandatory fields | 1 rows verified | `PASS` |
| Fund Accounting Identity | |Liab + Net Assets - Assets| < 1.0 | Diff = 0.0000 | `PASS` |
| Investment Panel Non-Null Integrity | No nulls in mandatory fields | 1419 positions verified | `PASS` |
| Borrower Multiplicity | Unique Borrowers < Total Positions | 582 borrowers / 1419 positions (41.0%) | `PASS` |
| Date & Entity Consistency | Exact match across Fund & SOI | Entities: Ares Capital Corporation (2026-03-31) | `PASS` |
| Fair Value Reconciliation | Relative Diff <= 0.1000% | Diff = 900.00 (0.0031%) | `PASS` |
| Unit Uniformity | Standardized unit across tables | Fund: `USD_THOUSANDS`, SOI: `USD_THOUSANDS` | `PASS` |

---

## 2. Detailed Accounting & Reconciliation Audit

### 2.1. Balance Sheet Accounting Identity (Fund Panel)
```
Total Assets:       $     30,679,000.00 (USD_THOUSANDS)
Total Liabilities:  $     16,614,000.00 (USD_THOUSANDS)
Net Assets:         $     14,065,000.00 (USD_THOUSANDS)
Liab + Net Assets:  $     30,679,000.00 (USD_THOUSANDS)
Absolute Difference: $            0.0000
Accounting Balance: BALANCED (< 1.0 unit diff)
```

### 2.2. Schedule of Investments (SOI) vs. Balance Sheet Reconciliation
```
Balance Sheet Portfolio Fair Value: $     29,499,300.00 (USD_THOUSANDS)
SOI Sum of Position Fair Values:   $     29,498,400.00 (USD_THOUSANDS)
Absolute Discrepancy:              $            900.00
Relative Discrepancy:                          0.0031%
Tolerance Threshold:                                 0.1000%
Reconciliation Status:              RECONCILED (Within Tolerance)
```

### 2.3. Portfolio Diversity & Multiplicity Metrics
- **Total Investment Positions**: `1419`
- **Unique Portfolio Companies / Borrowers**: `582`
- **Multiplicity Ratio (Borrowers / Positions)**: `41.01%`
- **Average Positions per Borrower**: `2.44`

## 3. Exported Final Deliverables

| File Path | Format | Row Count | File Size |
| :--- | :--- | :--- | :--- |
| `output/bdc_quarter_fund_panel.csv` | .CSV | 1 | 0.50 KB |
| `output/bdc_quarter_fund_panel.parquet` | .PARQUET | 1 | 12.30 KB |
| `output/bdc_quarter_investment_panel.csv` | .CSV | 1,419 | 367.11 KB |
| `output/bdc_quarter_investment_panel.parquet` | .PARQUET | 1,419 | 48.82 KB |

