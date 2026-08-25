---
name: bdc-soi-parse
description: >-
  Expert guide for parsing, standardizing, and reconciling SEC EDGAR Schedule of
  Investments (SOI) and Balance Sheets for any Business Development Company (BDC)
  across any reporting quarter.
---

# BDC Schedule of Investments (SOI) Parsing Skill

This skill provides a systematic runbook for an agent or engineer building or adapting private credit BDC data pipelines for any BDC (e.g. ARCC, OBDC, FSK, BXSL, GBDC) or any reporting quarter.

It points to the reference pipeline implemented in [`code/`](../../code/) and guides reuse, extension, trap detection, self-repair, and strict validation guardrails.

---

## 1. What to Reuse Unchanged

The following components are **filer-agnostic** and should be reused without modification:

1. **Validation & Reconciliation Engine**:
   - Location: [`code/bdc_05_validate_reconcile.py`](../../code/bdc_05_validate_reconcile.py)
   - Functionality: Enforces standard schemas (`FUND_PANEL_SCHEMA`, `INVESTMENT_PANEL_SCHEMA`), non-null constraints, accounting balance identity ($|\text{Liabilities} + \text{Net Assets} - \text{Total Assets}| < 1.0$), fair value reconciliation ($|\sum \text{fair\_value} - \text{Total Investments}| / \text{Total Investments} \le 0.001$), borrower multiplicity, uniform units, and fail-closed atomic export.

2. **Acceptance Criteria Test Suite**:
   - Location: [`code/test_acceptance_criteria.py`](../../code/test_acceptance_criteria.py)
   - Functionality: 25 standalone unit tests verifying all failure modes and invariant constraints.

3. **Core Utility Library**:
   - Location: [`code/bdc_09_utils.py`](../../code/bdc_09_utils.py)
   - Functions to reuse as-is:
     - `get_sec_headers(user_agent)`: SEC EDGAR rate-limit compliant headers.
     - `format_cik(cik)`: 10-digit zero-padded CIK formatter.
     - `parse_number(val)`: Handles currency signs, commas, negative parentheses `(12.3)`, and em-dashes `—`.
     - `normalize_date(date_str)`: Converts `MM/YYYY`, `MM/DD/YYYY`, and ISO dates to standard `YYYY-MM-DD`.
     - `strip_footnotes(text)`: Strips bracketed/parenthetical footnote numbers `(1)`, `(2)(9)`, `[3]` from entity names.
     - `parse_interest_rate_terms(...)`: Extracts reference rates (`SOFR`, `LIBOR`, `Base Rate`, `SONIA`), spread in basis points, floors, stated coupons, and PIK flags.
     - `classify_investment_category(inv_type)`: Categorizes investments into `First Lien Senior Secured`, `Second Lien`, `Subordinated Debt`, `Preferred Equity`, `Common Equity`, `Warrants`.

---

## 2. What to Extend and How

When targeting a new BDC (e.g. Blue Owl `OBDC / CIK 0001655845` or FS KKR `FSK / CIK 0001422183`) or a new fiscal quarter:

1. **BDC Entity Registry** in [`code/bdc_09_utils.py`](../../code/bdc_09_utils.py):
   - Add new constants: `NEW_BDC_CIK`, `NEW_BDC_TICKER`, `NEW_BDC_NAME`.
   - Pass parameters dynamically or via CLI args to `download_filing_for_bdc(cik=..., ticker=...)`.

2. **SEC Filing Downloader** in [`code/bdc_01_download_filing.py`](../../code/bdc_01_download_filing.py):
   - Parse `FilingSummary.xml` dynamically to map the correct `R*.htm` files (e.g., locate the `Report` node where `ShortName` contains `CONSOLIDATED BALANCE SHEETS` and `CONSOLIDATED SCHEDULE OF INVESTMENTS`).

3. **Balance Sheet Line Item Mapper** in [`code/bdc_02_parse_financials.py`](../../code/bdc_02_parse_financials.py):
   - Extend `find_val()` search terms for BDC-specific line item labels (e.g., `Total stockholders' equity` vs `Members' capital` vs `Net assets`).

4. **Table Slicer and Column Indexer** in [`code/bdc_03_parse_soi.py`](../../code/bdc_03_parse_soi.py):
   - Detect the filing representation type (see Section 3) and adapt column offsets.

---

## 3. Detecting Filing Representation

BDC filings in SEC EDGAR follow one of three primary representation architectures:

### Type A: Multi-Table HTML with Repeated Headers (e.g., ARCC 10-Q)
- **Characteristics**: SOI is split across 50–100 individual `<table>` elements. Each table repeats column headers (`Company (1)`, `Business Description`, `Investment`, `Coupon`, `Maturity Date`, etc.).
- **Detection**: `len(soup.find_all('table')) > 20` within the SOI section, and multiple tables contain `<th>` or `<td>` with `Investment`.
- **Parsing Strategy**: Iterate over `table` elements, check header for position columns, track state (`current_company`, `current_industry`) across tables.

### Type B: Single Monolithic Table (e.g., OBDC / GBDC)
- **Characteristics**: Entire Schedule of Investments is enclosed in one giant `<table>` (thousands of `<tr>` elements).
- **Detection**: Single `<table>` containing over 500 `<tr>` rows with `Maturity Date` or `Spread`.
- **Parsing Strategy**: Stream process `<tr>` elements sequentially with a single state machine.

### Type C: Inline XBRL (`ix:nonFraction`)
- **Characteristics**: HTML spans contain machine-readable tags: `<ix:nonFraction name="us-gaap:InvestmentOwnedAtFairValue" ...>`.
- **Detection**: `len(soup.find_all(re.compile(r'ix:nonfraction', re.IGNORECASE))) > 100`.
- **Parsing Strategy**: Use tag attributes (`name`, `scale`, `contextRef`) to directly verify or extract numeric facts.

---

## 4. Acceptance Criteria Checklist

Before exporting any final dataset to `output/`, the pipeline must satisfy:

1. **Fund Panel Integrity**:
   - Non-null: `bdc_name`, `cik`, `period_end_date`, `filing_date`, `total_assets`, `total_liabilities`, `net_assets`.
   - Accounting identity: $|\text{Total Liabilities} + \text{Net Assets} - \text{Total Assets}| < 1.0$ (unit-adjusted).
2. **Investment Panel Integrity**:
   - Non-null: `bdc_name`, `period_end_date`, `borrower_name`, `investment_type`, `fair_value`.
   - Multiplicity: $\text{Count(Distinct Borrower)} < \text{Count(Rows)}$.
3. **Cross-Table Reconciliation**:
   - $\frac{|\sum \text{Position Fair Value} - \text{Fund Total Investment Fair Value}|}{\text{Fund Total Investment Fair Value}} \le 0.001$ ($\le 0.1\%$).
   - `period_end_date`, `cik`, `bdc_name` strictly match.
4. **Unit Uniformity**:
   - Standardized unit (e.g. `USD_THOUSANDS`) identical across all rows and tables.
5. **Fail-Closed Guarantee**:
   - Any check failure triggers immediate cleanup of `output/` and exits with code `1`.

---

## 5. Trap Catalog & Detection Signatures

Refer to [`note/trap_log.md`](../../note/trap_log.md) for full context:

| Trap | Detection Signature | Root Cause | Self-Repair Procedure |
| :--- | :--- | :--- | :--- |
| **Trap 1: Summary Table Ingestion** | Initial tables have $\le 5$ rows with names like `Investments at fair value: Non-controlled` | Summary / footnote roll-forward preceding the SOI | Inspect table headers; require presence of `Maturity Date`, `Coupon`, or `Acquisition Date` before extracting positions. |
| **Trap 2: `$` Sign Column Shift** | `cell_texts[15] == '$'` on row 0; Fair Value sum drops by 20–30% | First row under header has explicit currency cells `<td>$</td>` | Implement branch logic: if `cell_texts[15] == '$'`, read values from `[16, 20, 24]`; else read `[15, 18, 21]`. |
| **Trap 3: Subtotal Row Ingestion** | Row count inflated; Fair Value sum is $\approx 2\times$ Balance Sheet | Rows with `Total ...` or 2–3 standalone numbers without deal terms | Exclude rows where `Total` appears in text, or where `len(non_empty) <= 3` with all numeric values. |
| **Trap 4: Auxiliary / Footnote Tables** | Position rows have negative fair values or contain `Counterparty`, `Delayed Draw` | Tables at end of SOI describe unfunded commitments or swap derivatives | Terminate parsing upon reaching the `Total Investments` row in the SOI. |
| **Trap 5: Prior Period Overlap** | Extracted positions contain two distinct `period_end_date`s | 10-Q/10-K includes both current quarter and prior year-end SOI | Slice HTML string strictly between current quarter SOI anchor and prior period header (`As of December 31, ...`). |

---

## 6. What the Agent Must NEVER Do

To ensure data integrity and avoid false-positive passes:

1. **NEVER hardcode, fudge, or plug reconciliation numbers**:
   - Do NOT insert a fake "reconciliation adjustment" position row to bridge discrepancy between SOI sum and Balance Sheet.
   - If sum is off by $> 0.1\%$, find the missing tables, skipped rows, or shifted columns.
2. **NEVER loosen tolerance thresholds**:
   - Do NOT increase tolerance from $0.1\%$ to $1.0\%$ or $10\%$ to force a pass.
3. **NEVER drop mandatory non-null constraints**:
   - Do NOT fill missing borrower names with `"N/A"` or `"Unknown"` just to satisfy non-null checks.
4. **NEVER bypass fail-closed atomic write**:
   - Do NOT write directly into `output/` during intermediate parsing steps.
   - Always write to a temporary directory and atomically move to `output/` ONLY after validation passes.
