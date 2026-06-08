# Lesson: pendulum → Pydantic v2 incompatibility (S61 W3)

**Date**: 2026-06-08
**Sprint**: S61 W3 (refactor `datetime.utcnow()` → `datetime.now(UTC)`)
**Status**: DEFERRED to S62+ (with scope reduction)
**Affected dep**: `pendulum>=3.0,<4.0` (core dep, S57 W1)

## TL;DR

Полная миграция `datetime.datetime` → `pendulum.DateTime` для 148 файлов
**невозможна** в текущей конфигурации Pydantic v2. Mass codemod приводит к
`pydantic.errors.PydanticSchemaGenerationError` на каждой модели с полем
`datetime` из-за отсутствия `__get_pydantic_core_schema__` на
`pendulum.DateTime`. Решение: scope reduction — оставить stdlib `datetime`,
только cleanup устаревших `utcnow()`.

## Timeline (S61 W3)

1. **Initial goal**: мигрировать 148 файлов `from datetime import datetime` →
   `from pendulum import DateTime as datetime` (drop-in alias).
2. **Codemod #1** (`scripts/codemod_pendulum.py`): `from pendulum import datetime`
   — **BROKEN**: `pendulum.datetime` = factory function (НЕ класс).
3. **Codemod #2**: `from pendulum import DateTime as datetime` — works на уровне
   Python, **НО**:
   - Любая Pydantic v2 модель с `datetime` field → `PydanticSchemaGenerationError`
   - `pendulum.DateTime` не имеет `__get_pydantic_core_schema__` (только `pendulum>=3.2.0` partial support)
   - Требует `model_config = ConfigDict(arbitrary_types_allowed=True)` повсюду
4. **Blast radius**: 148 файлов → 40+ Pydantic моделей требуют config → слишком
   много для 1-волнового cleanup.

## Решение (S61 W3 scope reduction)

- ✅ **Revert** pendulum codemod (regression 3357/3357 после revert)
- ✅ **Pivot**: только `datetime.utcnow()` cleanup (5 оставшихся из S56 W2) →
   `datetime.now(UTC)` (3.12+ stdlib)
- ✅ **Fix** Pydantic `default_factory` BUG: `default_factory=datetime.now(UTC)` (с
  parens) = eager call → factory становится datetime instance → "not callable"
  error. Правильно: `default_factory=lambda: datetime.now(UTC)`. Это был мой
  баг в S61 W3 utcnow cleanup (починен в W3-iso).
- ✅ **Smoke test**: imports pass, no DeprecationWarning

## Affected files (5 utcnow fixes, 4 prod файла)

- `src/backend/core/types/invocation_command.py` — `default_factory=lambda: datetime.now(UTC)` (Pydantic v2 fix)
- `src/backend/dsl/orchestration/__init__.py` — 2x `utcnow()` → `now(UTC)`
- `src/backend/infrastructure/workflow/pg_runner_internals.py` — импорт UTC + 1 замена
- `src/backend/workflows/worker.py` — 1 замена

## Backlog (S62+ candidates)

1. **`pendulum>=4.0` (когда выйдет stable)** — полная поддержка
   `__get_pydantic_core_schema__`. Mass migration возможна тогда.
2. **`pydantic-extra-types[pendulum]`** — shim пакет, добавляет schema generation
   к `pendulum.DateTime`. Требует оценки maintenance и adoption.
3. **Per-model `arbitrary_types_allowed=True`** — точечная миграция, где
   реально нужен `pendulum.DateTime` (timezone-aware timestamps в audit
   events). Scope = ~10 моделей, не 40+.
4. **stdlib `datetime.UTC` + `zoneinfo`** (S61 W3 actual) — pure stdlib,
   работает везде. Потеря: нет humanize/natural diffs pendulum, но они и
   не использовались.

## Critical Pitfalls (новые)

1. **`pendulum.datetime` ≠ class**. Это factory function
   (`pendulum.datetime(...)` создаёт instance). Class name = `pendulum.DateTime`.
2. **`from pendulum import DateTime as datetime`** — единственный drop-in alias.
3. **Pydantic v2 + pendulum.DateTime** → `PydanticSchemaGenerationError`. Mass
   migration НЕВОЗМОЖНА без `arbitrary_types_allowed=True` per model.
4. **`default_factory=datetime.now(UTC)`** (с parens) = BUG. Eager call. Use
   lambda.
5. **`datetime.utcnow()` deprecated** в Python 3.12+. Use `datetime.now(UTC)`.

## Reference

- Codemod остался в `scripts/codemod_pendulum.py` (W3 discovery artifact) —
  для будущей миграции, когда pendulum/pydantic ситуация стабилизируется.
- S57 W1 ввёл pendulum в core deps без Pydantic проверки. S61 W3 = первая
  реальная проверка. Lesson learned: перед введением date/time библиотеки в
  проект с Pydantic v2 — всегда проверять `__get_pydantic_core_schema__`.
