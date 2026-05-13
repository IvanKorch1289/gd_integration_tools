# KNOWN_ISSUES.md

## Sprint 2 (V15.3 MVP) — 3 БЛОКЕРА (день 1, 2026-05-13)

> Источник: 10-team plan PLAN.md V18.1. Координатор: K10 DevOps.
> Feature-flag для каждого — см. `src/backend/core/config/features.py`.
> Owner-команда — см. `.claude/team-ownership.toml::[blockers]`.

### ⛔ BLOCKER #1 — TaskIQ removal (R-V15-7)

- **Owner**: K6 AI/RAG
- **ETA**: Sprint 2 Wave 3 (`[wave:s2/k6-w2-taskiq-removal]`)
- **Risk**: high (13 callsites `Invoker.ASYNC_QUEUE`)
- **Feature-flag**: `feature_flags.taskiq_removed` (default-OFF)

**Описание**: Temporal полностью покрывает функциональность TaskIQ
(background/deferred/cron + saga/replay/versioning). Стек после migration:
FastStream (MQ) + APScheduler (простой scheduling) + Temporal (durable).

**DoD checklist**:
- [ ] 0 импортов `taskiq` в `src/` (`rg "^(from|import) taskiq" src/`)
- [ ] 0 ссылок `Invoker.ASYNC_QUEUE` (или enum переименован)
- [ ] 13 callsites замигрированы на Temporal cron / APScheduler
- [ ] Migration shim под feature-flag параллель до flip default-ON
- [ ] `make wave-memory NAME=taskiq-removal TYPE=feedback`
- [ ] `taskiq` удалён из `pyproject.toml::dependencies`

**Coordination**: K6 пишет migration shim, K10 audit'ит callsites,
K3 проверяет, что Temporal cron не ломает observability spans.

---

### ⛔ BLOCKER #2 — Workflow legacy purge (4 файла + 19 импортёров)

- **Owner**: K4 Workflow
- **ETA**: Sprint 2 Wave 1 (`[wave:s2/k4-w1-workflow-purge]`)
- **Risk**: high (19 импортёров, см. ниже)
- **Feature-flag**: `feature_flags.workflow_legacy_disabled` (default-OFF)

**Файлы под удаление**:
- `infrastructure/workflow/state.py` (DEPRECATED V16)
- `infrastructure/workflow/state_store.py` (DEPRECATED V16)
- `infrastructure/workflow/event_store.py` (DEPRECATED V16)
- `infrastructure/workflow/state_projector.py` (DEPRECATED V16)

**19 импортёров** (известны из Sprint 1):
- `pg_runner_backend.py`, `runner.py`, `executor.py`
- `core/di/providers.py`
- `infrastructure/database/models/workflow_instance.py`
- миграция `c3d4e5f6a7b8`
- `plugins/composition/lifecycle.py`
- + 12 файлов (audit через `rg "from .*infrastructure\.workflow\.(state|state_store|event_store|state_projector)" src/`)

**DoD checklist**:
- [ ] 0 ссылок на legacy `infrastructure/workflow/state*`
- [ ] TemporalFacade покрывает все use-cases legacy backend
- [ ] Adapter-pattern на переходный период (если нужен) задокументирован в ADR
- [ ] BPMN sample workflow запускается на новом стеке
- [ ] `pytest tests/workflow/` зелёный
- [ ] `make wave-memory NAME=workflow-purge TYPE=feedback`

**Coordination**: K4 ведёт миграцию, K9 пишет sample BPMN через
`extensions/credit_workflow/`, K8 чистит миграции БД, K10 audit'ит callsites.

**Связь со Sprint 1 deferral**: см. секцию `Sprint 1 Этап 2 — Step 2.2 deferred`
ниже. Объём подтверждён (~5-10 дней). Sprint 2 Wave 1 — атомарное закрытие.

---

### 🟡 BLOCKER #3 — WAF Phase-2 migration (38 callsites)

- **Owner**: K2 Net&WAF
- **ETA**: Sprint 2 Wave 2 (`[wave:s2/k2-w1-waf-migrate]`)
- **Risk**: medium (38 callsites, default-OFF feature-flag параллель)
- **Feature-flag**: `feature_flags.waf_outbound_via_facade` (default-OFF)

**Описание**: Все `:external` HTTP-callsites должны идти через
`OutboundHttpClient` (WAF-фасад). Поэтапная миграция 5-7 callsites/неделя,
flip default-ON только после staging-smoke.

**DoD checklist**:
- [ ] 0 прямых `httpx.AsyncClient()` в `src/` кроме `core/net/`
  (`rg "httpx\.AsyncClient\(\)" src/`)
- [ ] `make check-waf-coverage` blocking в CI (already есть, но не strict)
- [ ] ADR-0053 переведён из Proposed в Accepted
- [ ] staging-smoke результаты в `vault/2026-XX-waf-phase2-rollout.md`
- [ ] `feature_flags.waf_outbound_via_facade` default-ON после smoke
- [ ] `make wave-memory NAME=waf-phase2 TYPE=feedback`

**Coordination**: K2 ведёт миграцию, K1 поставляет mTLS-канал для external,
K6 проверяет cloud LLM маршруты, K10 audit'ит `check-waf-coverage` gate.

---

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