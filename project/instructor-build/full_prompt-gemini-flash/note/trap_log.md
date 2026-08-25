# BDC Parsing Trap Log

This document records each trap encountered during parsing of SEC EDGAR filings for BDC datasets, the exact signature that detects it, why it occurs, and how to repair it without violating data integrity.

---

### Trap 1: The Summary / Auxiliary Table Trap
* **Signature**: Initial tables in the HTML section contain investment totals or high-level roll-forwards (e.g., Table 0/1 containing `Non-controlled/non-affiliate company investments: $24,282`, `Controlled affiliate: $4,495`) rather than position-level rows.
* **Failure Mode**: Extracting these tables introduces duplicate high-level aggregate numbers or crashes the column parser with missing deal terms.
* **Detection**: Table header inspection — headers lack column terms like `Maturity Date`, `Spread`, `Acquisition Date`, or contain text `As of June 30, 2026 and December 31, 2025` with only 2–3 aggregate numbers.
* **Repair**: Check table headers for `Company (1)`, `Investment (18)`, `Acquisition Date`, `Maturity Date`. Filter out tables that do not contain position-level headers (e.g. slice `tables[2:69]`).

---

### Trap 2: HTML Column Shift due to Embedded Currency (`$`) Cells
* **Signature**: In SEC HTML tables, the first position row under a category or table includes a standalone `<td>$</td>` cell preceding numbers, shifting column indexes by +1 or +4.
* **Failure Mode**: 
  - First row of table: Principal at `td[16]`, Cost at `td[20]`, Fair Value at `td[24]`.
  - Subsequent loan rows (no `$`): Principal at `td[15]`, Cost at `td[18]`, Fair Value at `td[21]`.
  - Equity rows (no Principal): Shares at `td[14]`, Cost at `td[17]`, Fair Value at `td[20]`.
* **Detection**: Parsing by fixed `td` index yields `$` string in numeric columns or causes Fair Value sum to drop by 20–30%.
* **Repair**: Implement multi-branch column resolution based on `len(tds)` and whether `cell_texts[15] == '$'`.

---

### Trap 3: Subtotal and Industry Header Rows Ingestion
* **Signature**: Tables contain company-level subtotals (e.g., `Amortized Cost: 17.4`, `Fair Value: 17.6`), industry headers (e.g., `Software and Services`), and portfolio grand totals (`Total Investments: $29,349.3`).
* **Failure Mode**: Ingesting subtotals inflates position count and doubles the extracted Fair Value sum (e.g. $58B instead of $29B).
* **Detection**: Rows where `len(non_empty) <= 3` with all numeric values and no investment description, or rows containing `Total`.
* **Repair**: Filter out rows matching `Total` and rows where `len(non_empty) <= 3` with pure numeric entries.

---

### Trap 4: Footnote and Unfunded Commitment Auxiliary Tables
* **Signature**: Tables at the end of the Schedule of Investments (Tables 70–82) contain derivative contracts (Interest Rate Swaps, Hedged Items) and Unfunded Revolving/Delayed Draw Commitments.
* **Failure Mode**: Ingesting commitments creates non-investment rows with negative fair values or notional amounts.
* **Detection**: Table headers containing `Hedged Item`, `Counterparty`, `Notional Amount`, `Total revolving and delayed draw loan commitments`, `Less: funded commitments`.
* **Repair**: Explicitly terminate SOI parsing at the `Total Investments` row in Table 68, or filter out commitment keywords.

---

### Trap 5: Multi-Period Filing Boundaries
* **Signature**: 10-Q and 10-K filings contain two full Schedule of Investments (e.g., Current period: June 30, 2026, and Prior year-end: December 31, 2025).
* **Failure Mode**: Parsing the entire document without period boundaries extracts both quarters combined, doubling row counts.
* **Detection**: Grep for `As of December 31, 2025` or check date distribution in extracted rows.
* **Repair**: Locate the start of the current period SOI and slice the HTML strictly up to the prior period header (`dec_soi_start`).
