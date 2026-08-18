# Introduction to Claude Code

Session 3 of the Yale MAM Orientation BootCamp.

We build a **private credit dataset from raw SEC filings**: pick a publicly traded
BDC, parse its Schedule of Investments, and turn unstructured HTML into two
research panels. The throughline is judgment, not syntax.

## Before class

1. Install Claude Code and confirm it runs on your own laptop. Follow
   [docs.claude.com](https://docs.claude.com/en/docs/claude-code/overview), or
   Paul Goldsmith-Pinkham's
   [Getting Started with Claude Code](https://paulgp.substack.com/p/getting-started-with-claude-code).
   Windows needs WSL. Do this early: setup friction is what eats class time.
2. Clone this repo:
   ```
   git clone https://github.com/xuganchen/BootCamp-Introduction-to-Claude-Code.git
   ```

That is the whole pre-work. You do not need a Python environment in advance; we
build one with the agent in class.

## Agenda

| Block | Time | What |
|---|---|---|
| Part 1 | 20m | Where AI fits in a finance research workflow; a tour of Claude Code |
| Step 0 | 15m | Naive baseline: one prompt, three runs, three passing checks, one broken dataset |
| Step 1 | 30m | Write a spec, then build. Plan mode; sub-agents for independent verification |
| Break | 10m | |
| Step 2 | 30m | Generalize across quarters. Skills; the tie-out as a test suite |
| Step 3 | 23m | Analysis and report. Grounding in your own references |
| Part 3 | 28m | Working tips revisited, transfer, AI safety |
| Part 4 | 24m | Advanced usage demos and Q&A |

Each step introduces the concept it needs, at the point the work demands it.

## Repo map

| Path | What |
|---|---|
| `project/` | The hands-on project. **Start here.** |
| `slides/` | The deck (`slide.pdf`, 82 pages) and its full LaTeX source |
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
