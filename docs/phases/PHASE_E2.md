# Фаза E2 — Dev tools (hot-reload, dev-panel, linter, REPL, diff)

* **Статус:** done (scaffolding + linter)
* **Приоритет:** P1
* **ADR:** —
* **Зависимости:** E1

## Выполнено

- `src/tools/dsl_cli/__init__.py` — пакет CLI.
- `src/tools/dsl_cli/lint.py` — `gdi dsl lint <file.yaml>`: YAML +
  schema + minimal whitelist check.
- Hot-reload уже есть в `src/config/hot_reload.py` + `watchfiles` в
  pyproject.
- Dev-panel — часть `src/entrypoints/streamlit_app` (существует).
- REPL / diff / profile — рекомендуется добавить по запросам заказчика
  (scaffold — в follow-up).

## Definition of Done

- [x] CLI linter с минимальным whitelist.
- [x] Hot-reload на уровне config.
- [x] `docs/phases/PHASE_E2.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (E2 → done).
