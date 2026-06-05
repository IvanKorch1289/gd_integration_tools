#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# scripts/gen_api_autoapi.sh — v19: generate full auto API reference
# ──────────────────────────────────────────────────────────────────────
#
# Uses sphinx-autoapi to walk `autoapi_dirs` in docs/api/conf.py and
# produce a complete HTML API reference для всех модулей проекта.
#
# Output: docs/api/_build/html/autoapi/index.html
#
# Usage:
#   ./scripts/gen_api_autoapi.sh           # full build
#   ./scripts/gen_api_autoapi.sh --clean   # clean + full build
#
# CI integration (пример):
#   - name: Build API reference
#     run: ./scripts/gen_api_autoapi.sh --clean
#   - uses: actions/upload-pages-artifact@v3
#     with:
#       path: docs/api/_build/html

set -euo pipefail

CLEAN=0
for arg in "$@"; do
  case "$arg" in
    --clean) CLEAN=1 ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown arg: $arg" >&2
      exit 1
      ;;
  esac
done

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCS_API="$PROJECT_ROOT/docs/api"
BUILD_DIR="$DOCS_API/_build/html"

cd "$PROJECT_ROOT"

# Install deps if missing
if ! .venv/bin/python -c "import sphinx_autoapi" 2>/dev/null; then
  echo "→ Installing docs/api/requirements.txt…"
  .venv/bin/python -m pip install -q -r "$DOCS_API/requirements.txt"
fi

# Clean previous build if requested
if [ "$CLEAN" = "1" ]; then
  echo "→ Cleaning $BUILD_DIR…"
  rm -rf "$BUILD_DIR"
fi

# Build
echo "→ Building auto API reference (sphinx-autoapi)…"
.venv/bin/python -m sphinx -b html --keep-going "$DOCS_API" "$BUILD_DIR"

# Verify output
if [ ! -f "$BUILD_DIR/autoapi/index.html" ]; then
  echo "ERROR: autoapi/index.html not generated" >&2
  exit 1
fi

AUTOAPI_COUNT=$(find "$BUILD_DIR/autoapi" -name "index.html" | wc -l)
HTML_SIZE=$(du -sh "$BUILD_DIR" 2>/dev/null | cut -f1)

echo "✓ Built $AUTOAPI_COUNT autoapi/index.html files in $BUILD_DIR ($HTML_SIZE total)"
echo "  Main entry: file://$BUILD_DIR/autoapi/index.html"
