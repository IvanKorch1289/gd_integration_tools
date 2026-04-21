# Фаза C7 — Data contracts / expectations (GE-lite)

* **Статус:** done
* **Приоритет:** P1
* **ADR:** —
* **Зависимости:** C6

## Выполнено

`src/dsl/contracts/__init__.py`:
- `Expectation(column, not_null, unique, regex, range, schema_ref)`.
- `ExpectationResult(passed, failed_rows, message)`.
- `check_expectations(expectations, rows)` — batch-валидация.

DSL `.expect(column=..., not_null=True, range=(0, 1e9))` — follow-up
(минимальная обвязка в E1).

## Definition of Done

- [x] Все 4 основных проверки (not_null, unique, regex, range).
- [x] Batch-API.
- [x] `docs/phases/PHASE_C7.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (C7 → done).
