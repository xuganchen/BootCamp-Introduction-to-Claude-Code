#!/bin/bash
# build_section.sh -- compile ONE section of the deck in isolation.
#
#   ./utils/build_section.sh 03_step20
#
# Wraps sections/<name>.tex in the real preamble, compiles it into
# .build/, and prints either the page count or the first LaTeX errors.
# Use it while authoring a section so an error points at your frame
# instead of at the end of a 100-page run.
#
# Run from the slides/ directory.
set -u

NAME="${1:?usage: build_section.sh <section-name-without-.tex>}"
SRC="sections/${NAME}.tex"
OUT=".build"

[ -f "$SRC" ] || { echo "no such section: $SRC"; exit 2; }
mkdir -p "$OUT"

# Non-ASCII notice, no longer fatal. The preamble loads inputenc[utf8],
# so a real quotation mark or accented name compiles fine now. Plain
# ASCII punctuation is still house style: "--" renders the same as an en
# dash and survives being copied into a terminal.
if LC_ALL=C grep -n '[^ -~	]' "$SRC" > "$OUT/${NAME}.nonascii" 2>/dev/null; then
  echo "note: non-ASCII bytes in $SRC (compiles, but prefer -- and ')"
  head -5 "$OUT/${NAME}.nonascii"
fi

cat > "$OUT/${NAME}_main.tex" <<EOF
\\documentclass[11pt,aspectratio=169]{beamer}
\\input{utils/setup_teaching}
\\graphicspath{{./figures/}}
\\title{Section test}\\author{X}\\date{}
\\begin{document}
\\linespread{1.4}
\\input{sections/${NAME}}
\\end{document}
EOF

pdflatex -interaction=nonstopmode -halt-on-error \
         -output-directory="$OUT" "$OUT/${NAME}_main.tex" > "$OUT/${NAME}.log" 2>&1
STATUS=$?

if [ $STATUS -ne 0 ]; then
  echo "FAIL: pdflatex exited $STATUS"
  grep -n -A4 '^!' "$OUT/${NAME}.log" | head -40
  exit 1
fi

PAGES=$(grep -c '^\[[0-9]' "$OUT/${NAME}.log" 2>/dev/null)
echo "OK: $SRC compiled"
pdfinfo "$OUT/${NAME}_main.pdf" 2>/dev/null | grep -E '^Pages' || echo "frames: ~$PAGES"

# Overfull boxes are the usual sign a table or code block is too wide
# for the slide. Not fatal, but worth seeing.
OVER=$(grep -c 'Overfull \\hbox' "$OUT/${NAME}.log" 2>/dev/null)
[ "${OVER:-0}" -gt 0 ] && echo "note: $OVER overfull hbox warnings (content may run off the slide)"
exit 0
