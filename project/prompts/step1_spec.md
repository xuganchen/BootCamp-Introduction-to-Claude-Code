# Step 1. Write a spec, then build

## 1. Write `plan_v0.md` yourself, before prompting anything

26 lines: objective, deliverables, folder structure, acceptance criteria. Verbatim
at `../instructor-build/full-opus5-xhigh/plan_v0.md`.

The acceptance criteria are the part that does the work:

```
# BDC Dataset

* Goal: build a private credit BDC dataset from SEC filings for the most recent filing of one large BDC.
* Deliverable:
    * BDC-quarter panel: one row per BDC per quarter, fund-level financial statements.
    * BDC-quarter-investment panel: one row per investment position per quarter, deal-level terms.
    * Two consistent panel schemas.
* Acceptance criteria:
    * BDC-quarter panel:
        * Each row must be a BDC-quarter observation.
        * These fields are never null: BDC, CIK, period end, filing date.
        * total liabilities + net assets = total assets, or other basic accounting rules.
    * BDC-quarter-investment panel:
        * Each row must be an investment position.
        * These fields are never null: BDC, period end, borrower, investment type, amount, fair value.
        * The sum of extracted fair value equals total investment in the filing, within 0.1%.
        * Unique borrower names should be fewer than rows, because a BDC holds multiple loans per borrowers.
    * The units should be consistent across rows and tables.
    * If any check fails, exit non-zero and write no output file. 
* Folder structure
    * README.md
    * code: filename should be in order, such as "bdc_01_XXX.py", "bdc_09_utils.py", etc.
    * data: 
        * raw: organized raw files.
        * interim: temporary processing files.
    * output: final output.
    * note: other misc notes.
```

## 2. Plan mode

```
Only work on current folder. Based on @plan_v0.md, propose a working plan in @plan_v1.md.
```

## 3. Execute, with the checker separated from the author

```
Execute @plan_v1.md. Sub-agent A writes the parser; sub-agent B writes the test
from the criteria, never seeing the parser.
```
