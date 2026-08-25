# BDC Parsing Architecture Decisions

This document outlines key engineering decisions made when constructing the private credit BDC ingestion and validation pipeline.

---

### Decision 1: Standardizing on `USD_THOUSANDS`
- **Context**: BDC SEC filings present Balance Sheets in millions (`USD_MILLIONS`), whereas Schedule of Investments (SOI) displays individual positions in millions or thousands, and shares in exact units.
- **Decision**: Standardize all numerical dollar fields to `USD_THOUSANDS` (multiplying raw millions by 1,000.0).
- **Rationale**: Thousands provide integer-level precision without excessive fractional decimal places while maintaining exact compatibility between fund-level line items and position sums.

---

### Decision 2: Fail-Closed Atomic Validation Engine
- **Context**: Acceptance criteria demand that if any check fails, the pipeline exits non-zero and writes no output file.
- **Decision**: `bdc_05_validate_reconcile.py` runs all checks in memory and stages outputs in a temporary directory (`tempfile.TemporaryDirectory()`). Files are moved to `output/` only upon 100% test passage. On any failure, partial files are deleted and `sys.exit(1)` is triggered.
- **Rationale**: Prevents downstream data consumers from ingesting partial, corrupt, or out-of-balance datasets.

---

### Decision 3: Sub-Agent Isolation for Test Integrity
- **Context**: Ensuring test objectivity and avoiding bias.
- **Decision**: Sub-agent B wrote the test suite (`test_acceptance_criteria.py`) and validator (`bdc_05_validate_reconcile.py`) solely from `plan_v1.md` without viewing the parser implementation in `bdc_01_*.py` through `bdc_04_*.py`.
- **Rationale**: Independent verification ensures that bugs or missed edge cases in the parser are caught by objective tests rather than tailored to fit the implementation.

---

### Decision 4: Regex-Driven Interest Rate Term Parsing
- **Context**: Loan spreads, reference rates, and floors appear in diverse text patterns (e.g., `8.65 % SOFR (Q) 5.00 %`, `10.88 % ( 3.50 % PIK) SOFR (Q) 7.00 %`, `Fixed Rate 12.00%`).
- **Decision**: `bdc_09_utils.py:parse_interest_rate_terms()` breaks raw strings into constituent fields: `interest_rate_type`, `reference_rate`, `spread_bps`, `interest_floor_pct`, `total_coupon_rate_pct`, `is_pik`, and `is_non_accrual`.
- **Rationale**: Enables structured quantitative analysis of private credit spreads and reference benchmark distribution.
