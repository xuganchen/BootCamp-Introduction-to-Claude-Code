# BDC Dataset — Working Plan (v1)

## 1. Executive Summary & Objective

The objective of this project is to build an automated, reproducible, and strictly validated data pipeline that extracts, standardizes, reconciles, and exports two core panel datasets from SEC EDGAR filings for a leading Business Development Company (BDC) (e.g., **Ares Capital Corporation / ARCC**, CIK: `0001279495`, the largest publicly traded BDC):

1. **BDC-Quarter Fund Panel**: Fund-level financial statements (Balance Sheet / Statement of Assets and Liabilities).
2. **BDC-Quarter-Investment Panel**: Position-level Schedule of Investments (SOI) capturing loan-level and deal-level terms.

The pipeline enforces strict acceptance criteria, accounting identities, and fail-closed validation: if any check fails, the pipeline exits with a non-zero exit code and writes no final output.

---

## 2. Target Scope & Source Filings

* **Target BDC**: Ares Capital Corporation (ARCC) — CIK: `0001279495` (or alternative large BDC such as Blue Owl Capital Corp OBDC / CIK: `0001655845`).
* **Filing Type**: Most recent quarterly (Form 10-Q) or annual (Form 10-K) SEC EDGAR filing.
* **Source Endpoints**: SEC EDGAR submissions API and raw filing documents (`.htm` / XBRL / XML).
* **Compliance**: SEC rate-limiting compliance (max 10 requests/sec with standard user-agent header: `User-Agent: <Name> <email>`).

---

## 3. Data Schema Specifications

### 3.1. BDC-Quarter Fund Panel (`bdc_quarter_fund_panel`)
*One row per BDC per quarter.*

| Field Name | Type | Nullable | Description / Rules |
| :--- | :--- | :--- | :--- |
| `bdc_name` | string | No | Legal name of the BDC (e.g., `Ares Capital Corporation`) |
| `bdc_ticker` | string | No | Ticker symbol (e.g., `ARCC`) |
| `cik` | string | No | SEC Central Index Key (10-digit zero-padded) |
| `filing_type` | string | No | Form type (`10-Q` or `10-K`) |
| `fiscal_year` | integer | No | Fiscal year (e.g., `2024`) |
| `fiscal_quarter` | string | No | Fiscal quarter (`Q1`, `Q2`, `Q3`, `Q4`) |
| `period_end_date` | string (YYYY-MM-DD) | No | Period end date of the financial statements |
| `filing_date` | string (YYYY-MM-DD) | No | SEC EDGAR filing date |
| `unit` | string | No | Standardized unit (e.g., `USD_THOUSANDS` or `USD`) |
| `total_investments_fair_value`| float | No | Total portfolio investments at fair value |
| `total_investments_amortized_cost` | float | Yes | Total portfolio investments at amortized cost |
| `cash_and_cash_equivalents` | float | Yes | Cash and cash equivalents |
| `other_assets` | float | Yes | Receivables, deferred charges, other assets |
| `total_assets` | float | No | Total Assets |
| `debt_outstanding` | float | Yes | Credit facilities, notes, secured debt |
| `other_liabilities` | float | Yes | Payables, base/incentive management fees payable |
| `total_liabilities` | float | No | Total Liabilities |
| `net_assets` | float | No | Net Assets / Total Shareholders' Equity |
| `shares_outstanding` | float | Yes | Common shares outstanding |
| `net_asset_value_per_share` | float | Yes | NAV per share |

### 3.2. BDC-Quarter-Investment Panel (`bdc_quarter_investment_panel`)
*One row per investment position per quarter.*

| Field Name | Type | Nullable | Description / Rules |
| :--- | :--- | :--- | :--- |
| `bdc_name` | string | No | Legal name of the BDC |
| `bdc_ticker` | string | No | Ticker symbol |
| `cik` | string | No | 10-digit CIK |
| `period_end_date` | string (YYYY-MM-DD) | No | Report period end date |
| `filing_date` | string (YYYY-MM-DD) | No | SEC filing date |
| `borrower_name` | string | No | Standardized company / portfolio company name |
| `industry` | string | Yes | Industry sector classification |
| `investment_category` | string | Yes | Asset category (e.g., `First Lien Senior Secured`, `Second Lien`, `Subordinated Debt`, `Preferred Equity`, `Common Equity`) |
| `investment_type` | string | No | Granular investment description |
| `interest_rate_type` | string | Yes | `Floating` or `Fixed` |
| `reference_rate` | string | Yes | Base rate index (e.g., `SOFR`, `LIBOR`, `Base Rate`) |
| `spread_bps` | float | Yes | Spread over reference rate in basis points (or rate in %) |
| `interest_floor_pct` | float | Yes | Rate floor percentage (e.g., `1.00` for 1.00%) |
| `total_coupon_rate_pct` | float | Yes | Total all-in coupon rate / stated interest rate |
| `is_pik` | boolean | Yes | Whether interest has Payment-In-Kind (PIK) |
| `is_non_accrual` | boolean | Yes | Non-accrual status flag |
| `maturity_date` | string (YYYY-MM-DD) | Yes | Stated maturity date |
| `unit` | string | No | Standardized unit (e.g., `USD_THOUSANDS` or `USD`) |
| `principal_amount` | float | Yes | Par amount / principal commitment |
| `amortized_cost` | float | Yes | Amortized cost / cost basis |
| `fair_value` | float | No | Fair value of the position |
| `pct_of_net_assets` | float | Yes | Percentage of net assets |

---

## 4. Pipeline Architecture & Modular Scripts

The codebase will follow a sequential, deterministic execution model:

```
project_root/
├── README.md
├── plan_v0.md
├── plan_v1.md
├── code/
│   ├── bdc_01_download_filing.py      # SEC EDGAR downloader & raw storage
│   ├── bdc_02_parse_financials.py     # Parse Balance Sheet / Fund financials
│   ├── bdc_03_parse_soi.py            # Parse Schedule of Investments (SOI)
│   ├── bdc_04_normalize_clean.py      # Harmonization, unit scaling, data typing
│   ├── bdc_05_validate_reconcile.py   # Strict accounting checks & safe atomic export
│   └── bdc_09_utils.py                # Reusable regex, SEC clients, schema models, logger
├── data/
│   ├── raw/                           # Raw downloaded HTML/JSON/XBRL filings
│   └── interim/                       # Intermediate parsed staging tables
├── output/                            # Final verified datasets (CSV / Parquet)
└── note/                              # Parsing notes, footnote edge cases, dictionary
```

### Script Responsibilities

1. **`code/bdc_09_utils.py`**:
   - Configuration constants, CIK registry, SEC headers.
   - Robust number and date parsers (handling `$`, parentheses for negative numbers, footnotes like `(1)`, `(2)`, empty strings).
   - Data validation schemas using Pydantic or Pandas/Polars assertions.
   - Structured logging.

2. **`code/bdc_01_download_filing.py`**:
   - Queries the SEC EDGAR API for the target BDC's latest 10-Q/10-K submission.
   - Downloads primary doc files and metadata.
   - Saves raw files into `data/raw/` with a manifest file (`manifest.json`).

3. **`code/bdc_02_parse_financials.py`**:
   - Locates Consolidated Statements of Assets and Liabilities (Balance Sheet).
   - Extracts assets, liabilities, net assets, and total portfolio investment line items.
   - Saves raw financial statements to `data/interim/fund_financials_raw.csv`.

4. **`code/bdc_03_parse_soi.py`**:
   - Locates and stitches all contiguous Schedule of Investments (SOI) tables across multiple pages/sections.
   - Extracts rows, columns, borrower headers, sub-totals, and footnotes.
   - Filters out non-position summary/header rows while preserving portfolio totals.
   - Saves raw position rows to `data/interim/soi_positions_raw.csv`.

5. **`code/bdc_04_normalize_clean.py`**:
   - Normalizes text: strips footnotes, trims whitespace, standardizes borrower names.
   - Parses rates (Reference rate, spread, floor, PIK toggle).
   - Standardizes financial amounts into a uniform unit (e.g., thousands of USD).
   - Harmonizes date formats (`YYYY-MM-DD`).
   - Produces clean interim datasets: `data/interim/bdc_fund_clean.csv` and `data/interim/bdc_investment_clean.csv`.

6. **`code/bdc_05_validate_reconcile.py`**:
   - Executes the acceptance criteria validation matrix.
   - **Reconciliation Check**: Asserts `abs(Sum(fair_value) - total_investments_fair_value) / total_investments_fair_value <= 0.001` (within 0.1%).
   - **Accounting Identity**: Asserts `total_liabilities + net_assets == total_assets` (within floating point rounding).
   - **Non-null Integrity**: Asserts all mandatory fields contain valid values.
   - **Borrower Multiplicity**: Asserts `unique(borrower_name) < total_positions`.
   - **Fail-Closed Write**: Only when 100% of checks pass, writes:
     - `output/bdc_quarter_fund_panel.csv` (and `.parquet`)
     - `output/bdc_quarter_investment_panel.csv` (and `.parquet`)
   - If any check fails: raises descriptive `AssertionError`, exits non-zero (`sys.exit(1)`), and deletes any partial output files.

---

## 5. Acceptance Criteria & Validation Rules

| Level | Validation Rule | Threshold / Condition | Action on Failure |
| :--- | :--- | :--- | :--- |
| **Fund** | Non-null required fields | `bdc_name`, `cik`, `period_end_date`, `filing_date`, `total_assets`, `total_liabilities`, `net_assets` $\neq \text{Null}$ | Fail & Abort |
| **Fund** | Fundamental Accounting Balance | $\vert \text{Total Liabilities} + \text{Net Assets} - \text{Total Assets} \vert < 1.0$ (unit-adjusted) | Fail & Abort |
| **Position** | Non-null required fields | `bdc_name`, `period_end_date`, `borrower_name`, `investment_type`, `fair_value` $\neq \text{Null}$ | Fail & Abort |
| **Position** | Borrower Multiplicity Sanity | $\text{Count(Distinct Borrower)} < \text{Count(Rows)}$ | Fail & Abort |
| **Cross-Table** | Fair Value Reconciliation | $\frac{\vert \sum \text{Position Fair Value} - \text{Fund Total Investment Fair Value} \vert}{\text{Fund Total Investment Fair Value}} \le 0.001$ (0.1%) | Fail & Abort |
| **Cross-Table** | Date & Entity Consistency | `period_end_date`, `cik`, `bdc_name` strictly match across both panels | Fail & Abort |
| **System** | Uniform Currency Units | Single unit standard applied across all rows and tables | Fail & Abort |
| **System** | Atomic Write / Clean State | No partial or corrupt files written to `output/` upon error | `sys.exit(1)` |

---

## 6. Implementation Roadmap & Milestones

1. **Milestone 1: Project Setup & SEC Ingestion (`bdc_01_download_filing.py`, `bdc_09_utils.py`)**
   - Implement folder skeleton.
   - Build robust SEC downloader with rate limit compliance and local caching.
   - Download the latest 10-Q/10-K for target BDC (ARCC).

2. **Milestone 2: Fund Financials Extraction (`bdc_02_parse_financials.py`)**
   - Parse Balance Sheet HTML table.
   - Extract and verify `Total Assets`, `Total Liabilities`, `Net Assets`, and `Total Investments at Fair Value`.

3. **Milestone 3: Schedule of Investments (SOI) Extraction (`bdc_03_parse_soi.py`)**
   - Parse multi-table SOI structures.
   - Handle nested company rows, multi-tranche loans, and footnote references.

4. **Milestone 4: Data Normalization & Feature Engineering (`bdc_04_normalize_clean.py`)**
   - Parse interest rate mechanics (SOFR / Base rate, spreads, floors, PIK).
   - Standardize dates and numerical fields.

5. **Milestone 5: Reconciliation Engine & Export (`bdc_05_validate_reconcile.py`)**
   - Implement automated validation test suite.
   - Test reconciliation tolerance (< 0.1%).
   - Implement fail-closed atomic write to `output/`.

6. **Milestone 6: Documentation & Validation Report (`README.md`, `note/`)**
   - Document execution steps, data dictionary, and reconciliation summary.
