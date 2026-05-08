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

### Sprint 1 Этап 3 — Step 3.3 (миграция callsites + удаление aliases) deferred (2026-05-08)

**Контекст**: Step 3.2 закоммичен `672b40f` — canonical-реализации в
`core/resilience/{breaker,retry,rate_limiter}.py` готовы;
`infrastructure/resilience/{breaker,retry,retry_budget}.py` — backward-compat
shim'ы (re-export). Step 3.4 закоммичен `e07000b` —
`core/resilience/_pyrate_compat.py` + BoundedInMemoryBucket.

**Что осталось (Step 3.3 Phase 2)**: 12 callsite-файлов всё ещё импортируют
из `infrastructure/resilience/` (через работающие aliases):
- `infrastructure/database/session_manager.py`
- `infrastructure/logging/backends/graylog_gelf.py`
- `infrastructure/clients/transport/{http_upstream,http_httpx}.py`
- `infrastructure/clients/external/circuit_breakers.py`
- `infrastructure/clients/storage/redis.py`
- `infrastructure/clients/messaging/stream.py`
- `dsl/engine/processors/eip/resilience.py`
- `tests/unit/log_sinks/test_log_sinks.py`

**Причина deferral**:
- Aliases работают — система функционально полна (Phase 1 DoD достигнут).
- `http_httpx.py` в working tree активной параллельной команды; миграция
  callsite'а сейчас увеличит merge conflict risk.
- Удаление aliases требует синхронизации с _всеми_ незакоммиченными
  параллельными ветками; безопаснее выполнять одной волной после слияния.

**План разрешения**: после слияния параллельных working tree changes
(`http_httpx.py`, `dsl/builder.py` и др.) — отдельная Wave
`[wave:s1/single-entry-migration]` с массовой заменой импортов
+ удаление shim'ов.

**Feature-flag `new_resilience_v2`** (в `ResilienceSettings`, default `False`)
оставлен как переключатель для Step 3.3.

### Открытый техдолг (после сессии 2026-05-01 PM — pre-Wave 22)