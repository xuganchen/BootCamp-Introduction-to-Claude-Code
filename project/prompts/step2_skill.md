# Step 2. Generalize across quarters

## 1. Package the parser as a skill

```
Read code/, note/trap_log.md and note/parsing_decisions.md.

First, tell me which parts of this pipeline are filer-agnostic and which encode
something specific to this BDC. Quote the lines.

Then write skill bdc-soi-parse so that an agent facing a BDC or
a quarter we have never parsed knows: what to reuse unchanged, what to extend and
how, how to detect which representation a filing uses, the acceptance criteria,
and each trap with the signature that detects it. It must also say how to repair
itself, and what it must never do in order to make a check pass.

Do not paste the engine into the skill. Point at it.
```

## 2. Parameterize

```
/bdc-soi-parse ARCC prior 10-Q (2026-03-31)
```

## 3. Sweep

```
/bdc-soi-parse every 10-K and 10-Q ARCC has filed with a period end on or after
2023-01-01. Work oldest to newest so failures cluster visibly.

Then assemble all successful filings into a single BDC-quarter panel and check
that (cik, period_end) is unique. Report what you find before fixing it.
```
