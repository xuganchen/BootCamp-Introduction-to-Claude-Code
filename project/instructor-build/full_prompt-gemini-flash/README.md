# BDC Private Credit Dataset Pipeline

An automated, reproducible, and strictly validated end-to-end data pipeline that extracts, normalizes, reconciles, and exports private credit datasets from SEC EDGAR filings for Business Development Companies (BDCs), focusing on **Ares Capital Corporation (ARCC, CIK: 0001287750)**.

---

## 1. Project Overview & Deliverables

The pipeline produces two standardized, cross-reconciled panel datasets conforming to strict accounting identities and acceptance criteria:

1. **BDC-Quarter Fund Panel** (`output/bdc_quarter_fund_panel.csv` / `.parquet`):
   - One row per BDC per quarter.
   - Fund-level financial statements (Total Assets, Liabilities, Net Assets, Portfolio Investments at Fair Value & Cost, Cash, NAV per share).

2. **BDC-Quarter-Investment Panel** (`output/bdc_quarter_investment_panel.csv` / `.parquet`):
   - One row per investment position per quarter (1,438 positions for ARCC Q2 2026).
   - Granular deal-level terms: borrower/company name, industry, investment category (First Lien, Second Lien, Subordinated, Preferred, Common), stated coupon, benchmark reference rate (SOFR, SONIA, NIBOR, Base Rate), spread (bps), floor, PIK flag, maturity date, par/principal amount, amortized cost, fair value, and % of net assets.

3. **Validation & Audit Report** (`note/validation_report.md`):
   - Full audit trail of accounting identity balances and fair value reconciliation within 0.1%.

---

## 2. Pipeline Architecture & Directory Structure

```
.
├── README.md                          # Project documentation and usage instructions
├── plan_v0.md                         # Initial project outline
├── plan_v1.md                         # Detailed working plan and acceptance criteria
├── code/
│   ├── bdc_01_download_filing.py      # SEC EDGAR downloader with rate limiting & caching
│   ├── bdc_02_parse_financials.py     # Parses Balance Sheet into interim fund dataset
│   ├── bdc_03_parse_soi.py            # Parses Schedule of Investments (SOI) tables
│   ├── bdc_04_normalize_clean.py      # Cleans text, standardizes units to USD_THOUSANDS, parses rates
│   ├── bdc_05_validate_reconcile.py   # Strict accounting validation & atomic fail-closed export
│   ├── bdc_09_utils.py                # Reusable regex, SEC headers, rate parsers, logging
│   └── test_acceptance_criteria.py    # 25-test unit test suite for validation engine
├── data/
│   ├── raw/                           # Downloaded HTML/JSON/XML SEC filing documents
│   └── interim/                       # Intermediate parsed staging datasets
├── output/                            # Final verified datasets (CSV and Parquet)
│   ├── bdc_quarter_fund_panel.csv
│   ├── bdc_quarter_fund_panel.parquet
│   ├── bdc_quarter_investment_panel.csv
│   └── bdc_quarter_investment_panel.parquet
└── note/
    └── validation_report.md           # Automated validation and reconciliation audit report
```

---

## 3. Execution Instructions

### Prerequisites
- Python 3.10+
- `pandas`, `beautifulsoup4`, `requests`, `lxml`, `pyarrow`

### Run the Pipeline
Run the scripts in sequential order:

```bash
# 1. Download latest SEC filing (ARCC 10-Q)
python3 code/bdc_01_download_filing.py

# 2. Parse Fund Balance Sheet
python3 code/bdc_02_parse_financials.py

# 3. Parse Schedule of Investments (SOI)
python3 code/bdc_03_parse_soi.py

# 4. Clean, Normalize & Standardize Units (USD_THOUSANDS)
python3 code/bdc_04_normalize_clean.py

# 5. Validate Acceptance Criteria & Atomically Export Deliverables
python3 code/bdc_05_validate_reconcile.py
```

### Run the Unit Test Suite
To verify the 25 unit tests covering all acceptance criteria and fail-closed edge cases:

```bash
python3 code/test_acceptance_criteria.py
```

---

## 4. Acceptance Criteria & Validation Results

| Acceptance Criterion | Target Specification | Observed Value (ARCC Q2 2026) | Status |
| :--- | :--- | :--- | :--- |
| **Fund Non-Null Fields** | No nulls in mandatory fields | 1 row verified (0 nulls) | **PASS** |
| **Fund Accounting Identity** | $\vert \text{Liabilities} + \text{Net Assets} - \text{Total Assets} \vert < 1.0$ | $\$16,607,000 + \$13,891,000 = \$30,498,000$ (Diff: $\$0.00$) | **PASS** |
| **Investment Non-Null Fields** | No nulls in mandatory fields | 1,438 positions verified (0 nulls) | **PASS** |
| **Borrower Multiplicity** | $\text{Unique Borrowers} < \text{Total Positions}$ | 592 unique borrowers / 1,438 positions (41.2%) | **PASS** |
| **Fair Value Reconciliation** | $\frac{\vert \sum \text{SOI Fair Value} - \text{Fund Total Investment} \vert}{\text{Fund Total Investment}} \le 0.1000\%$ | $\vert \$29,349,200 - \$29,349,300 \vert = \$100$ ($0.0003\%$) | **PASS** |
| **Date & Entity Consistency** | Strict match across tables | ARCC / CIK 0001287750 / 2026-06-30 | **PASS** |
| **Unit Uniformity** | Single standardized currency unit | `USD_THOUSANDS` across all tables and rows | **PASS** |
| **Fail-Closed Behavior** | Exit non-zero and write no output on failure | Verified in unit test suite | **PASS** |
