# Introduction to Claude Code

Session 3 of the Yale MAM Orientation BootCamp.

We build a **private credit dataset from raw SEC filings**: pick a publicly traded
BDC, parse its Schedule of Investments, and turn unstructured HTML into two
research panels. The throughline is judgment, not syntax.

## Before class

1. Get a terminal agent running on your own laptop. **[SETUP.md](SETUP.md)** has
   two options, and one of them is free for students. Do this early: setup
   friction is what eats class time. Paul Goldsmith-Pinkham's
   [Getting Started with Claude Code](https://paulgp.substack.com/p/getting-started-with-claude-code)
   is good optional background.
2. Clone this repo:
   ```
   git clone https://github.com/xuganchen/BootCamp-Introduction-to-Claude-Code.git
   ```

That is the whole pre-work. You do not need a Python environment in advance; we
build one with the agent in class.

## Agenda

| Block | What |
|---|---|
| Part 1 | Where AI fits in a finance research workflow; a tour of Claude Code |
| Part 2 - Step 0 | Naive baseline: one prompt, three runs, three passing checks, one broken dataset |
| Part 2 - Step 1 | Write a spec, then build. Plan mode; sub-agents for independent verification |
| Break | |
| Part 2 - Step 2 | Generalize across quarters. Skills; the tie-out as a test suite |
| Part 2 - Step 3 | Analysis and report. Grounding in your own references |
| Part 3 | Working tips revisited, transfer, AI safety |
| Part 4 | Advanced usage demos and Q&A |

Each step introduces the concept it needs, at the point the work demands it.

## Repo map

| Path | What |
|---|---|
| `SETUP.md` | Get an agent running before class. **Do this first.** |
| `project/` | The hands-on project. **Start here.** |
| `slides/` | The deck (`slide.pdf`) and its full LaTeX source |
| `syllabus/` | The session syllabus |

## No code ships here

You build the downloader, the parser, and the verification check yourself, with
the agent. That is the session. What you get instead: the target schema, the
EDGAR ground rules, every prompt used in class, and reference panels so the
analysis works regardless of how far your parser got.

My own implementation is published in full under `project/instructor-build/`.
Read its outputs and notes freely; leave its code alone until you have written
your own.

Everything in there, including the 53-page portfolio report, was written by an
agent and reviewed by no one. It is a record of what this workflow produces, not
research, and not investment advice.

## Licence

CC BY 4.0, except the third-party screenshots listed in [LICENSE](LICENSE),
which also says how to attribute.

Builds on Paul Goldsmith-Pinkham's
[A Series on Claude Code](https://paulgp.substack.com/).
