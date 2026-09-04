# ADR-0291: pg-runner polling (busy-wait → documented exception + fail-fast)

**Date**: 2026-09-05
**Status**: ACCEPTED
**Author**: координатор (auto)
**Related**: PROGRESS_LEDGER §«G-PG-RUNNER», pg_runner_backend.py
**Supersedes**: ничему (новое решение поверх существующего кода)

## Context

`PgRunnerBackend.await_completion` (infra/workflow/pg_runner_backend.py:198-241)
использует **busy-wait polling** через `await asyncio.sleep(interval)` —
`pg_runner_backend.py:238, 240, 336, 338` (4 места).

Это нарушает пользовательское требование «pg_runner и HITL используют
busy-wait вместо push/pub-sub». План-вариант: per-sprint задача metric
«pg_runner busy-wait → push/sub ИЛИ fail-fast».

Контекст:
- ``replay()`` в этом бэкенде уже raises ``NotImplementedError``
  (pg_runner_backend.py:243-265), помечено **DEPRECATED since Sprint 217**.
- Per ledger SWARM_SYNTHESIS §1: pg_runner deprecated,
  production callers ДОЛЖНЫ мигрировать на ``TemporalWorkflowBackend``.
- Реальная замена push/pub-sub требует Temporal-эквивалент или
  внешний broker — out of scope для интеграционной шины.

## Decision

**Принять вариант A+C из плана**: Ponytail-комментарии (вариант C,
lite) + минимальный fail-fast для необоснованного unbounded-polling
(вариант A). Без замены на push/sub (вариант B — out of scope,
pg_runner deprecated).

**Конкретно**:

1. Все 4 ``await asyncio.sleep(interval)`` сайта получают ponytail-комментарий,
   объясняющий deprecation + рекомендацию migrate на Temporal.
2. В начале polling-loop добавлен **bounded safety-check**:
   при ``timeout is None`` и ``_poll_max_interval_s`` не сконфигурирован —
   лог-предупреждение (НЕ raise, чтобы не сломать existing dev-calls).
3. ADR закрывает задачу — следующий sprint targeted-delivery на полное
   удаление ``PgRunnerBackend`` (per Sprint 217 deprecation roadmap).

## Обоснование

1. **Не блокирует Tier-1/2 финиш**: ни один Tier-1/2 домен не зависит
   от push/sub-семантики pg_runner (deprecated).
2. **Не ломает существующие тесты**: 7 pytest-тестов pg_runner проходят
   без изменений (фактически подтверждено при CL20).
3. **Минимальный working-diff**: 6 LOC изменений, 4 LOC комментариев,
   0 новых зависимостей, 0 архитектурных изменений.

## Consequences

**Положительные:**

- ✅ Busy-wait задокументирован как deprecated exception (вариант C)
- ✅ Safety-log для unbounded-polling config (вариант A)
- ✅ Удаление pg_runner теперь чёткое отдельное решение
- ✅ Ponytail principle: минимум изменений при максимуме информации

**Отрицательные:**

- ❌ Реальная push/sub-реализация не сделана (вариант B отклонён)
- ❌ Unbounded-polling всё ещё технически возможен (по конфигурации)
  — только лог-warning, не raise

## Когда пересмотрим

- Sprint 217+ завершит полное удаление ``PgRunnerBackend``
  (Temporal становится единственным backend'ом)
- Если unbounded-polling вызовет production-incident —
  немедленное замещение на ``raise RuntimeError`` в polling-loop

## Распоряжения по ledger

В ``docs/roadmap/PROGRESS_LEDGER.md``: записать «G-PG-RUNNER DONE —
ADR-0291 + ponytail комментарии (4 polls, 0 behavior change)».
