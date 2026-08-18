# The instructor's build

My own implementation, published in full: the three naive runs from Step 0, and
the pipeline from Steps 1 to 3.

**Every line here was written by the agent, and none of it was edited by hand.**
The code, the tests, the notes and the report are the agent's output exactly as it
landed. The only files I wrote myself are the prompts in `../prompts/` and the
26-line `full/plan_v0.md`. Nothing was cleaned up afterwards: the notes have gaps,
and a real bug survives in the pipeline (below). That is the artifact -- what this
workflow actually produces, not a tidied version of it.

**Read the outputs and the notes. Leave the code alone until you have written your
own.** Copying `full/code/` costs you the two things the session teaches: noticing
that a check is needed, and building it.

Raw filings are not included. They are public on EDGAR and each run re-downloads
what it needs.

## `phase0/` -- one prompt, three configurations

Run unchanged on 2026-08-16. The prompt is in `../prompts/step0_naive.md`.

| Run | Model | Effort | Parser | Columns in the investment table |
|---|---|---|---|---|
| `opus5-xhigh` | Opus 5 | xhigh | 803 lines, 1 file | 44 |
| `opus5-medium` | Opus 5 | medium | 526 lines, 2 files | 22 |
| `sonnet5-medium` | Sonnet 5 | medium | 504 lines, 2 files | 26 |

All three picked Ares Capital (ARCC), parsed the inline XBRL rather than the
rendered tables, invented a balance-sheet tie-out nobody asked for, and passed it
at 0.001 percent on both dates.

Open the three investment CSVs side by side. The column names barely overlap, so
the three cannot be pooled. Then count distinct borrowers at 2025-12-31: two runs
give 580, `opus5-medium` gives **1,409, one per row**, with the instrument type
concatenated into the borrower name and the type field empty. It still ties out
exactly.

Each run's `README.md` is what that agent wrote about its own output, unedited.

## `full/` -- the pipeline, Steps 1 to 3

| Path | What |
|---|---|
| `plan_v0.md` | The 26-line spec, written before any prompting |
| `plan_v1.md` | What plan mode proposed back: 210 lines, 2 schemas, 16 checks, 12 named traps, a 7-step build order |
| `code/` | The parsing pipeline, 11 modules, 4,009 lines |
| `code/analysis/` | The analysis layer, 7 modules, 4,086 lines |
| `tests/` | The verification gate |
| `note/` | `coverage.md`, `trap_log.md`, `parsing_decisions.md`. The most reusable thing here |
| `output/analysis/` | The 53-page report: `report.md` and its `.pdf` render, 32 figures, 48 tables, and `facts/`, the numbers behind each exhibit. The prompt asked for `.docx` too; the agent produced one and it is not shipped here, being the same content at 5 MB |

Coverage: 50 of 88 ARCC filings, 37,197 positions, 2005-03-31 to 2026-06-30. 30 of
34 from 2018 onward, 14 of 14 from 2023 onward. `note/coverage.md` gives the reason
for every exclusion. The panels are in `../output/`, not duplicated here.

## What this report is not

`full/output/analysis/` is a 53-page report on one BDC's portfolio, and it looks
like equity research. It is not. No human analyst wrote, reviewed or checked it;
an agent produced it in one turn from the panels in `../output/`, and it inherits
the parsing bug described below. It is here as evidence of what the workflow
produces, nothing more.

It is not investment advice, not a recommendation, and not affiliated with or
endorsed by Ares Capital Corporation or Yale University. Do not cite it, forward
it, or make a decision on it.

## Known bug, shipped on purpose

`is_non_accrual` returns zero flags for the FY2022, FY2023 and FY2024 10-Ks, where
neighbouring quarters carry 13 to 22. Those filings contain a second, earlier
footnote legend belonging to an SDLP joint-venture table, and the parser takes the
first legend it finds.

Left unfixed: all sixteen verification checks passed over it, because the broken
field is a boolean and no dollar tie-out reaches it, and Step 3's analysis is what
found it. `note/trap_log.md` does not record it -- the log was written in Step 2
and never updated. That gap is left as it was rather than backfilled.

## Licence

CC BY 4.0, like the rest of the repo. See [../../LICENSE](../../LICENSE).
