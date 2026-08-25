#!/usr/bin/env bash
#
# Build a print-ready HTML from the Persian architecture document.
#
# The Markdown file is the single source of truth; this script only renders it
# with RTL typography and print rules (docs/_pdf-style.html). To get a PDF,
# open the generated HTML in a browser and print to PDF — that route keeps
# Persian shaping and ligatures correct, which most Markdown-to-PDF converters
# get wrong.
#
#   ./docs/build-pdf.sh
#   open docs/ARCHITECTURE.fa.html      # then Cmd-P -> Save as PDF

set -euo pipefail

DOCS="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$DOCS/ARCHITECTURE.fa.md"
OUT="$DOCS/ARCHITECTURE.fa.html"

if ! command -v pandoc >/dev/null 2>&1; then
  echo "build-pdf: pandoc is not installed (brew install pandoc)" >&2
  exit 1
fi

pandoc "$SRC" \
  --from gfm \
  --to html5 \
  --standalone \
  --metadata pagetitle="مستندات معماری MidasScript" \
  --metadata lang=fa \
  --metadata dir=rtl \
  --include-in-header "$DOCS/_pdf-style.html" \
  --output "$OUT"

echo "wrote $OUT"
echo "open it in a browser and print to PDF (Cmd-P -> Save as PDF)"
