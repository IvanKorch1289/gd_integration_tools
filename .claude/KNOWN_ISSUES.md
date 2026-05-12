# KNOWN_ISSUES.md

## Известные ограничения и quirks

### Sprint 1 Этап 2 — Step 2.2 deferred на Sprint 4 (2026-05-07)

**Проблема**: PLAN.md V16 §4.1 требует `Workflow legacy purged` (DoD Sprint 1).
4 файла под удаление (`infrastructure/workflow/{state,state_store,event_store,state_projector}.py`)
имеют 19 импортёров через `pg_runner_backend.py`, `runner.py`, `executor.py`,
`core/di/providers.py`, `infrastructure/database/models/workflow_instance.py`,
миграцию `c3d4e5f6a7b8`, `plugins/composition/lifecycle.py`.

**Объём миграции**: ~5-10 дней. Полная замена pg-runner стека на TemporalFacade
с переписыванием всех consumers.

**Причина deferral**:
- Объём перекрывается со Sprint 4 Workflow Single-Entry refactor (Temporal
  native migration), который атомарно решит ту же задачу.
- В Sprint 1 параллельная команда активно работает над `runner.py`
  (последний touch 2026-05-07 15:53 при wrap TaskRegistry callsites) —
  пересечение увеличивает риск merge conflict'ов.

**План разрешения**: Sprint 4. Текущие 4 файла остаются помечены DEPRECATED V16
(см. header-комменты `state.py`, `state_store.py`, `event_store.py`, `state_projector.py`).

### Sprint 1 Этап 2 — Step 2.3 (OTel asyncpg) выполняется параллельной командой

В working tree `pyproject.toml` + `src/backend/infrastructure/observability/otel_auto.py`
содержат изменения для `opentelemetry-instrumentation-asyncpg` + функция
`_instrument_asyncpg`. Коммит ожидается от параллельной команды.

### Sprint 1 Этап 3 — Step 3.3 (миграция callsites + удаление aliases) ✅ CLOSED 2026-05-08

**Wave**: `[wave:s1/single-entry-migration]` (PLAN.md V18 §2.5).

**Что сделано**:
- 7 production callsites мигрированы с `infrastructure/resilience/breaker`
  на canonical `core/resilience/breaker`:
  - `infrastructure/clients/external/circuit_breakers.py`
  - `infrastructure/clients/messaging/stream.py`
  - `infrastructure/clients/transport/http_httpx.py`
  - `infrastructure/database/session_manager.py`
  - `infrastructure/logging/backends/graylog_gelf.py`
  - `dsl/engine/processors/eip/resilience.py`
  - `tests/unit/log_sinks/test_log_sinks.py`
- `infrastructure/resilience/__init__.py` перенаправлён на
  `core/resilience/retry_budget` для `RetryBudget` re-export.
- 3 shim-файла удалены:
  - `infrastructure/resilience/breaker.py`
  - `infrastructure/resilience/retry.py`
  - `infrastructure/resilience/retry_budget.py`
- 2 shim-verification теста удалены из:
  - `tests/unit/core/resilience/test_unified_breaker.py`
    (`test_infrastructure_shim_re_exports`, `test_infrastructure_shim_breaker_registry_lazy`)
  - `tests/unit/core/resilience/test_unified_retry.py`
    (`test_infrastructure_shim_re_exports`, `test_infrastructure_retry_budget_shim`)

**Что НЕ затронуто**: `client_breaker.py`, `bulkhead.py`, `rate_limiter.py`,
`unified_rate_limiter.py`, `time_limiter.py`, `coordinator.py`,
`registration.py`, `health.py`, `snapshot_job.py`, `reconnection.py`,
`supervisor.py` — это полноценные реализации, не shim'ы.

**Verify**: `tests/unit/core/resilience/` 16/16 passed; targeted import smoke
для всех 7 callsites OK. `http_upstream.py` импортирует только
`client_breaker.py` (не shim) — не требует миграции.

**Feature-flag `new_resilience_v2`** в `ResilienceSettings`: можно убрать
в Sprint 2 после общей зачистки.

### Открытый техдолг (после сессии 2026-05-01 PM — pre-Wave 22)