# Slides

The session deck: `slide.pdf` (82 pages) and its full Beamer source.

## Build

```bash
latexmk -pdf slide.tex
./utils/build_section.sh 03_step20    # one section, while drafting
```

**Use `pdflatex`, not `xelatex` or `lualatex`.** The preamble is a
`fontenc[T1]` + `inputenc[utf8]` setup. Verified against MacTeX / TeX Live 2024.

Build one section on its own while editing it: a LaTeX error in an 82-page beamer
run points at the end of the file rather than at your frame.

## Layout

| Path | Role |
|---|---|
| `slide.tex` | Main file: title page plus one `\input` per section. Nothing in `sections/` depends on anything else in `sections/`. |
| `utils/setup_teaching.tex` | **The whole preamble.** Theme, colours, macros, code blocks, frame furniture. The only file to edit for styling. |
| `sections/*.tex` | One file per block, in session order. Plain sequences of frames, each with a header comment recording its shape and sources. |
| `figures/` | Session screenshots, report exhibits, and the Part 4 app screenshots. |

| File | Block | Frames |
|---|---|---|
| `01_intro.tex` | Part 1: Introduction | 14 |
| `02_project_intro.tex` | Part 2 opener | divider + 3 |
| `03_step20.tex` | Step 0. The naive baseline | 14 |
| `04_step21.tex` | Step 1. Write a spec, then build | 17 |
| `05_step22.tex` | Step 2. Generalize across quarters | 7 |
| `06_step23.tex` | Step 3. Analysis and report | 9 |
| `07_concepts.tex` | Part 3: More useful concepts | divider + 3 |
| `08_demos.tex` | Part 4: Advanced usage examples | 11 |

## The one rule that will bite you

**Any frame containing code needs `[fragile]`:**

```latex
\begin{frame}[fragile]{Title}      % REQUIRED for prompt / pycode / shellout
```

Without it, beamer scans the frame body before `listings` can claim it, the
`\end{...}` is never seen, and the run dies pages later with an error pointing at
the end of the file.

## Conventions

- **Emphasis macros**, in descending order of attention: `\yb{} \ybb{}` (Yale
  blue), `\ylb{} \ylbb{}` (lighter blue), `\yo{} \yob{}` (orange, for warnings and
  the thing that broke). `\blue`, `\red` and `\green` are deliberately undefined
  so a copy-paste from another deck fails loudly.
- `\takeaway{...}` is the one sentence a slide exists to deliver. At most one per
  frame, and deliberately not on every frame.
- **Provenance lives in comments, not on the slide.** Parts 2 to 4 print no source
  line; each frame carries a `% Source:` comment instead.
- **Each step section opens with the same four-row step table, that step's row
  tinted.** Five copies exist. Edit a row in one, edit it in all five.
- **Text inside `prompt` and `shellout` is a quotation** of what was actually run
  or returned, typos included. Do not tidy it.
- **Frames cut from the plan are commented out, not deleted**, with a note saying
  why and what would restore them.
- ASCII punctuation by house style (`--`, `'`), and ``` ``...'' ``` for quotation
  marks: a straight `"` typesets as two closing quotes.

## Reuse

CC BY 4.0, except the third-party screenshots in `figures/` -- see
[../LICENSE](../LICENSE). Built to be updated in future years: keep the
source documented, and keep the prompts in `../project/prompts/` in sync with the
slides that quote them.
