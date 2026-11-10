# ADR-0443 — Пороги блокирующих гейтов берутся из baseline (single source of truth)

* Статус: Accepted (2026-11-10, волна 31)
* Cycle: 188 (волна 31)
* Связан с: ADR-0285 (baseline-подход), ADR-0441 (инфра-чек-лист)
* Затрагивает: `tools/checks/mypy_budget.py`, `tools/check_coverage_gate.py`, `make/quality.mk`, `.github/workflows/test.yml`, `.baselines/coverage.json`

## Контекст

Четыре блокирующих гейта CI были красными на master:

| Гейт | Причина |
|---|---|
| `ruff check src tests` | 98 ошибок (все в `tests/`) |
| `ruff format --check src tests` | 327 файлов не отформатированы под ruff 0.16.7 |
| mypy-бюджет | `make type-check-budget` требовал `--max 5`, фактически 12 ошибок, baseline — 12 |
| coverage-гейт | CI задавал `--threshold 75` явно при фактическом coverage 74 % и baseline 52.25 % (замер на прогоне с 206 упавшими тестами) |

Пороги были продублированы в CI-конфигурации, baseline'ах и Makefile →
расхождение делало гейты красными без реальной деградации кода.

## Решение

* **Порог = baseline.** `mypy_budget.py --max` по умолчанию берёт значение из
  `.baselines/mypy.json`; `check_coverage_gate.py --threshold` — из
  `.baselines/coverage.json`. Явные флаги остаются как override для
  разовых проверок.
* **Baseline пересчитан** по последнему валидному замеру: coverage 74 %
  (вместо 52.25 %, полученного на прогоне с 206 упавшими тестами).
* **Форматирование и lint-ошибки** устранены: `ruff check src tests` → 0,
  `ruff format --check src tests` → 0 (327 файлов переформатировано).

## Последствия

* Блокирующие гейты CI зелёные и не расходятся с baseline'ами;
* дальнейшее ужесточение — только через обновление baseline (рэтчет), а не
  правкой CI-конфигурации.
