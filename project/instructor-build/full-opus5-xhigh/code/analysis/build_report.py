"""Render output/analysis/report.md to .docx and .pdf.

pandoc is run from inside output/analysis so the relative figure paths in
the markdown (figures/<slug>.png) resolve.  The PDF goes through xelatex
with a LaTeX preamble that matches the institutional-research look of the
reference decks: wide-ish margins, a serif body, booktabs rules, and
figures capped to the text width.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "analysis"
MD = OUT / "report.md"
HEADER = OUT / "_preamble.tex"

PREAMBLE = r"""
\usepackage{booktabs}
\usepackage{longtable}
\usepackage{caption}
\usepackage{float}
% 32 figures floating freely leaves half-empty pages; pin each one where it
% is written so it stays next to the paragraph that reads it.
\floatplacement{figure}{H}
\captionsetup{font=small,labelfont=bf,skip=4pt}
\usepackage{fancyhdr}
\pagestyle{fancy}
\fancyhf{}
\renewcommand{\headrulewidth}{0.4pt}
\fancyhead[L]{\footnotesize\itshape ARCC Private Credit Portfolio, 2018Q3-2026Q2}
\fancyfoot[C]{\thepage}
\usepackage{xcolor}
\definecolor{navy}{HTML}{1F3B63}
\usepackage{sectsty}
\allsectionsfont{\color{navy}}
\setlength{\emergencystretch}{3em}
\usepackage{ragged2e}
\let\oldincludegraphics\includegraphics
% Cap figures at 86% of the text width and centre them: at full width a
% figure plus its stamps rarely leaves room for a second one on the page.
\renewcommand{\includegraphics}[2][]{%
  \centerline{\oldincludegraphics[width=0.86\linewidth,#1]{#2}}}
"""


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=OUT, check=True)


def main() -> int:
    if not MD.exists():
        print(f"missing {MD}", file=sys.stderr)
        return 1
    HEADER.write_text(PREAMBLE)

    # -smart keeps straight quotes and plain hyphens in the output, so the
    # rendered text stays copy-paste safe.  The report's own headings are
    # already numbered ("2. Summary statistics"), so pandoc must NOT add a
    # second numbering scheme on top of them.
    run(["pandoc", "report.md",
         "-o", "ARCC_Private_Credit_Portfolio_Report.docx",
         "--from", "markdown+pipe_tables+yaml_metadata_block-smart",
         "--toc", "--toc-depth=2",
         "--resource-path=.:figures"])

    run(["pandoc", "report.md",
         "-o", "ARCC_Private_Credit_Portfolio_Report.pdf",
         "--from", "markdown+pipe_tables+yaml_metadata_block-smart",
         "--pdf-engine=xelatex",
         "--toc", "--toc-depth=2",
         "-H", "_preamble.tex",
         "-V", "geometry:margin=1in",
         "-V", "fontsize=10pt",
         "-V", "colorlinks=true",
         "-V", "linkcolor=navy",
         "-V", "mainfont=Times New Roman",
         "-V", "sansfont=Helvetica Neue",
         "--resource-path=.:figures"])

    for f in ("ARCC_Private_Credit_Portfolio_Report.docx",
              "ARCC_Private_Credit_Portfolio_Report.pdf"):
        p = OUT / f
        print(f"{f}: {p.stat().st_size/1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
