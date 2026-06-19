# S168 W11 P2-11: Decision: mkdocs-material (primary) + Sphinx (deprecated)

## Status: Accepted (S168 W11)

## Context

Project has TWO documentation stacks running in parallel:

1. **mkdocs-material** (`mkdocs.yml`, 1.5KB, 8→16 nav sections per S168 W10 P1-11)
   - Material theme, mkdocstrings Python handler
   - Modern, fast, well-maintained
   - Auto-generated nav from filesystem
   - 9 docs sections + 16 nav entries (post-P1-11)

2. **Sphinx + sphinx-autoapi** (`docs/conf.py`, `make/docs.mk:10-12`)
   - `uv run sphinx-build -b html -W --keep-going`
   - Legacy, dual-stack with mkdocs
   - AutoAPI for Python docstrings

Per master prompt v8 P2-11: "Choose one of two. mkdocs-material (Material) + mkdocstrings OR Sphinx + sphinx-autoapi. Both have content currently."

## Decision

**mkdocs-material is the PRIMARY docs stack.** Sphinx is deprecated.

### Rationale

- mkdocs P1-11 expansion (16 nav sections) already covers all docs
- mkdocstrings provides auto-generated Python docs (same function as sphinx-autoapi)
- Material theme is modern, mobile-friendly
- Per Ponytail minimum: keep both running (no breaking change), but
  STOP adding new content to Sphinx

### Migration plan (separate WIP)

1. Stop running `make docs` (Sphinx build) in CI — keep only `mkdocs build`
2. Move any Sphinx-only content (RST files) to Markdown
3. After 1 quarter, delete `docs/conf.py` + `make/docs.mk` Sphinx targets
4. Update CI to only run mkdocs

## Consequences

- New docs MUST be in Markdown, NOT RST
- New doc structure: use `docs/<section>/<file>.md` (per mkdocs nav)
- Old RST files (if any) — convert to Markdown per S169+ migration

## Related

- Master prompt v8 P2-11
- S168 W10 P1-11: mkdocs nav extension
- docs/ARCHITECTURE.md (canonical content)
- docs/adr/ (ADR index — 201 files)

## Date: 2026-06-18
