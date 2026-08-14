# API Reference (mkdocs canonical)

**Tool:** [mkdocstrings-python](https://mkdocstrings.github.io/python/) +
[mkdocs-material](https://squidfunk.github.io/mkdocs-material/)

**Status:** Canonical since B2/M10.2 (commit `7499f0a`, 2026-07). Active in
`mkdocs.yml` via `mkdocstrings` plugin.

## Назначение

Auto-generated Python API reference для всех публичных модулей
`gd_integration_tools`. Генерируется mkdocstrings при `mkdocs build`
из docstring'ов исходного кода (Google/NumPy style).

## Где смотреть

* **Локальная сборка:** `make docs-mkdocs` → `site/reference/`
* **Dev server:** `make docs-mkdocs-serve` → http://127.0.0.1:8000
* **Публикация:** CI workflow `docs-publish.yml` (mkdocs + mike)

## История

* v19 (Sprint 39, 2026-06-05): первоначальная версия на sphinx-autoapi.
* B2 (M10.2, commit `7499f0a`, 2026-07): миграция на mkdocs.
* Cycle 201 (P2-001 RESIDUAL, 2026-08-14): удалён мёртвый sphinx tooling
  (`docs/api/`, `tools/gen_api_docs.sh`, `tools/gen_api_autoapi.sh`).
  Sphinx/sphinx-autoapi/sphinx-rtd-theme НЕ в `pyproject.toml` deps —
  скрипты падали бы при запуске.
