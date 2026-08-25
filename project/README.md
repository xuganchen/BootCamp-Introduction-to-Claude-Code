# The project: a private credit dataset from SEC filings

Take one publicly traded business development company (BDC), pull its raw SEC
filings, and turn them into two research panels. Nothing here is pre-cleaned.

## What you build

| Panel | Grain | Contents |
|---|---|---|
| `bdc_quarter` | one row per BDC per quarter | NAV, leverage, yield, non-accruals, portfolio size |
| `bdc_quarter_investment` | one row per position per quarter | borrower, seniority, spread, maturity, principal, cost, fair value |

Both come from the **Schedule of Investments**, the table in every BDC's 10-K and
10-Q listing every loan it holds.

Pick any large BDC. ARCC and MAIN are gentle; GBDC and TSLX are a fight. Stay with
the one you pick: managers format their filings differently, so your neighbour's
parser will not work on your filing, and that is the point. Parse from 2023-01-01
onward, roughly 14 filings and 280 MB.

## The four steps

| Step | What you do | The concept it forces |
|---|---|---|
| 0 | Ask for what you want in one sentence, and see what comes back | It will invent a balance-sheet check you never asked for, and pass it. Watch what the check does not cover. |
| 1 | Write a real spec, then build against it | Plan mode, so the agent shows its approach before writing. A sub-agent writes the test, so the checker is not the author. |
| 2 | Package the parser as a skill, sweep every quarter | It breaks on the older filings. The tie-out becomes a test suite, and the coverage statement is as much a deliverable as the panel. |
| 3 | Analysis and report | Ground the write-up in a style you supply, not one the agent picks. Using the data turns out to be a check of its own. |

## How you know you are right

The Schedule of Investments has to foot to the balance sheet: sum the fair value
of every position and it must equal "total investments at fair value" in the same
filing.

That is the whole game, and it is not enough. In my own run, the naive prompt
produced a parse that tied out at 0.001 percent on both dates and had merged the
instrument text into the borrower name for every row of the comparative period,
turning 580 borrowers into 1,409 and erasing lien seniority. The tie-out validates
dollars. It says nothing about structure, and nobody chose that scope on purpose.

So write the tie-out, then ask what it does not look at: row counts, distinct
keys, null rates.

**You write that check yourself.** There is no `tie_out.py` here and there will
not be one. Running a script somebody handed you teaches you to run a script.

A second free check is worth finding on your own: every 10-Q reports two dates,
and the prior-period column of one filing must match the current column of the
filing before it.

## A known bug in the reference panel

`output/bdc_quarter_investment.csv` carries one, on purpose. `is_non_accrual`
returns **zero flags for the quarters ending 2022-12-31, 2023-12-31 and
2024-12-31**, where every neighbouring quarter carries 13 to 23. Those three are
fiscal-year 10-Ks containing a second, earlier footnote legend belonging to a
joint-venture table, and the parser takes the first legend it finds.

If you plot non-accruals over time from this panel, you will draw three holes and
they are not real. It is shipped unfixed because it is the best artifact in the
project: sixteen verification checks passed over it, since the broken field is a
boolean and no dollar tie-out reaches a boolean. Step 3's analysis is what caught
it.

Every other field is unaffected. Details in `instructor-build/README.md`.

## Things that will bite you

Real properties of the filings, not exercises we invented.

1. **Subtotal rows** interleaved with position rows. Sum everything and you double count.
2. **Unit scale.** Some BDCs report in millions, most in thousands, some use both in one document.
3. **Two dates per filing.** Parse both without separating them and you double count again.
4. **Blank company names** on continuation rows, so a borrower's second and third loans orphan.
5. **Duplicated columns** from the HTML layout: 42 columns for 14 real fields.
6. **Repeated sections** for non-controlled, affiliated and controlled investments, each with its own subtotals.
7. **Fiscal calendars differ.** One major BDC closes its year in September, so key on the period end date, not the quarter label.
8. **Footnote markers glued to values**, so numeric conversion silently drops rows.
9. **Equity positions** carry share counts instead of principal.
10. **Foreign currency loans** priced off SONIA or EURIBOR rather than SOFR.

## EDGAR ground rules

Your downloader must follow these or SEC will refuse it.

- Declare a `User-Agent` header identifying you, e.g. `Your Name your@email`.
  Requests without one get a 403.
- Stay under 10 requests per second.
- Cache locally. Filings never change once filed, so download each one once.

## Folders

| Path | What |
|---|---|
| `prompts/` | Every prompt used in class, in order, exactly as run |
| `output/` | The reference panels, so Step 3 works however far your parser got |
| `instructor-build/` | My own implementation, all four steps, published in full |

The two CSVs in `output/` are the **reference** panels, mine. They are here so
Step 3 works even if your parser stalled. Overwrite them with your own once yours
tie out, or keep both and point Step 3 at whichever you trust.

Your own work goes in folders you create alongside them. The Step 1 spec asks for
this layout, and it is not decoration: the Step 2 prompt reads `note/` back before
it does anything.

| Folder | What goes in it |
|---|---|
| `code/` | Numbered modules in run order: `bdc_01_resolve.py` ... `run_all.py` |
| `output/` | Your panels, then Step 3's figures, tables and report |
| `note/` | `coverage.md`, `trap_log.md`, `parsing_decisions.md` |

`instructor-build/` is published on purpose and is a trap if you use it wrong.
Read `instructor-build/full_prompt-opus5-xhigh/note/` -- the trap log and the
coverage report -- before you read a line of its code. Copying the parser gets
you a panel and teaches you nothing; the notes are where the judgment is.

Step 3 grounds the report's style in three published private-markets research
reports (McKinsey, NVCA, PitchBook). They are third-party and not redistributed
here; download your own, or substitute any writing whose style you want copied.

## The point

End with a re-runnable artifact, not a one-off chat: a parser plus a test that
regenerates your panels from raw filings, and still works next quarter.
