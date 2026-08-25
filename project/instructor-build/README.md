# The instructor's build

My own implementation, published in full: the three naive runs from Step 0, the
pipeline from Steps 1 to 3, and one control run of the same spec by a different
agent.

**Every line here was written by the agent, and none of it was edited by hand**
(one exception, a local path scrubbed from one Gemini note, flagged where it is).
The code, the tests, the notes and the report are the agent's output exactly as it
landed. The only files I wrote myself are the prompts in `../prompts/` and the
26-line `full_prompt-opus5-xhigh/plan_v0.md`. Nothing was cleaned up afterwards:
the notes have gaps, and a real bug survives in the pipeline (below). That is the
artifact -- what this workflow actually produces, not a tidied version of it.

**Read the outputs and the notes. Leave the code alone until you have written your
own.** Copying `full_prompt-opus5-xhigh/code/` costs you the two things the
session teaches: noticing that a check is needed, and building it.

Raw filings are not included. They are public on EDGAR and each run re-downloads
what it needs. Panels ship as `.csv` only: both full runs also wrote `.parquet`
renders of every panel, which are the same numbers again.

## What is here

| Folder | Approach | Agent |
|---|---|---|
| `naive_prompt-opus5-xhigh` | Step 0. One sentence, nothing specified | Claude Code, Opus 5, xhigh effort |
| `naive_prompt-opus5-medium` | Step 0. The same prompt, unchanged | Claude Code, Opus 5, medium effort |
| `naive_prompt-sonnet5-medium` | Step 0. The same prompt, unchanged | Claude Code, Sonnet 5, medium effort |
| **`full_prompt-opus5-xhigh`** | Steps 1 to 3. `plan_v0.md`, then plan mode, sub-agents, a skill, the report | Claude Code, Opus 5, xhigh effort |
| `full_prompt-gemini-flash` | Steps 1 and 2. The same `plan_v0.md`, byte for byte | Antigravity, Gemini Flash |

**`full_prompt-opus5-xhigh` is the main run**, and the one to read first. It is
what the slides follow from Step 1 onward, and its Step 2 panel is the reference
panel shipped in `../output/`.

Two comparisons are set up here, and each holds one thing constant. The three
Step 0 runs share a prompt and differ only in the agent. The two full runs share
`plan_v0.md`, byte for byte, and differ only in the agent. The sections below
take each in turn.

## `naive_prompt-*/` -- one prompt, three configurations

Run unchanged on 2026-08-16. The prompt is in `../prompts/step0_naive.md`.

| Run | Model | Effort | Parser | Columns in the investment table |
|---|---|---|---|---|
| `naive_prompt-opus5-xhigh` | Opus 5 | xhigh | 803 lines, 1 file | 44 |
| `naive_prompt-opus5-medium` | Opus 5 | medium | 526 lines, 2 files | 22 |
| `naive_prompt-sonnet5-medium` | Sonnet 5 | medium | 504 lines, 2 files | 26 |

All three picked Ares Capital (ARCC), parsed the inline XBRL rather than the
rendered tables, invented a balance-sheet tie-out nobody asked for, and passed it
at 0.001 percent on both dates.

Open the three investment CSVs side by side. The column names barely overlap, so
the three cannot be pooled. Then count distinct borrowers at 2025-12-31: two runs
give 580, `naive_prompt-opus5-medium` gives **1,409, one per row**, with the
instrument type concatenated into the borrower name and the type field empty.
It still ties out exactly.

Each run's `README.md` is what that agent wrote about its own output, unedited.

## `full_prompt-opus5-xhigh/` -- the pipeline, Steps 1 to 3

| Path | What |
|---|---|
| `plan_v0.md` | The 26-line spec, written before any prompting |
| `plan_v1.md` | What plan mode proposed back: 210 lines, 2 schemas, 16 checks, 12 named traps, a 7-step build order |
| `code/` | The parsing pipeline, 11 modules, 4,009 lines |
| `code/analysis/` | The analysis layer, 7 modules, 4,086 lines |
| `tests/` | The verification gate |
| `skills/` | The Step 2 skill, 544 lines, written by the agent for itself |
| `note/` | `coverage.md`, `trap_log.md`, `parsing_decisions.md`. The most reusable thing here |
| `output/bdc_quarter*.csv` | What Step 1 alone produced: the single 2026-06-30 quarter, 1,439 positions, 593 borrowers |
| `output/analysis/` | The 53-page report: `report.md` and its `.pdf` render, 32 figures, 48 tables, and `facts/`, the numbers behind each exhibit. The prompt asked for `.docx` too; the agent produced one and it is not shipped here, being the same content at 5 MB |

Coverage: 50 of 88 ARCC filings, 37,197 positions, 2005-03-31 to 2026-06-30. 30 of
34 from 2018 onward, 14 of 14 from 2023 onward. `note/coverage.md` gives the reason
for every exclusion. That is Step 2's panel and it lives in `../output/`, not
duplicated here; the two CSVs in `output/` are the one quarter Step 1 stopped at.

## What this report is not

`full_prompt-opus5-xhigh/output/analysis/` is a 53-page report on one BDC's
portfolio, and it looks like equity research. It is not. No human analyst wrote,
reviewed or checked it; an agent produced it in one turn from the panels in
`../output/`, and it inherits the parsing bug described below. It is here as
evidence of what the workflow produces, nothing more.

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

## `full_prompt-gemini-flash/` -- the same spec, a different agent

The same `plan_v0.md`, byte for byte, handed to Gemini Flash in Antigravity
instead of Claude Code. The spec is the constant, the agent is the variable.

| | `full_prompt-opus5-xhigh` | `full_prompt-gemini-flash` |
|---|---|---|
| `plan_v1.md` | 210 lines | 188 lines |
| Pipeline | 11 modules, 4,009 lines | 8 modules, 2,696 lines |
| Its own checks | a 16-check gate | 7 validation checks, all PASS, plus 25 unit tests |
| Step 2 skill | 544 lines | 129 lines |
| Panel in `output/` | 2026-06-30, 1,439 positions, 593 borrowers | 2026-03-31, 1,419 positions, 582 borrowers |
| Investment panel | 21 columns | 22 columns |
| Full panel | 50 quarters, 37,197 positions, in `../output/` | none; the batch never resolved |

Both agents invented a verification layer nobody asked for, both passed their own,
and the two panels still cannot be pooled: 21 columns against 22, sharing barely
any names. That is the Step 0 lesson one level up.

`note/batch_processing_summary.json` is the file to read. The run did attempt all
14 quarters from 2023: 10 passed, 1 failed reconciliation (2023-03-31, 0.304
percent against its own 0.100 percent tolerance), 3 errored out, 13,897 positions
in all. None of it is in `output/`, which holds the single 2026-03-31 quarter --
the pipeline is fail-closed and the batch was never resolved.

Two things to notice before trusting anything in the folder:

- Its `README.md` describes a Q2 2026 run with 1,438 positions and 592 borrowers.
  The panel actually in `output/` is 2026-03-31, 1,419 positions, 582 borrowers.
  That README is the agent's own, unedited, and it outran its outputs.
- Its `plan_v1.md` gives ARCC's CIK as `0001279495`. The correct one is
  `0001287750`, which is what `code/bdc_09_utils.py` ends up using. A wrong fact
  in the plan that the code quietly did not inherit.

No analysis layer here. Step 3 for this run reused the opus5 analysis modules over
the opus5 panel, so there is nothing of its own to publish and neither is copied
in.

One edit to the folder, the only hand edit anywhere in this directory:
`note/validation_report.md` printed my full local path in four table cells, and
those cells now read `output/...`. Row counts, sizes and every other line stand
as the agent wrote them.

## Licence

CC BY 4.0, like the rest of the repo. See [../../LICENSE](../../LICENSE).
