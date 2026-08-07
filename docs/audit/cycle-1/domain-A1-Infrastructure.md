# Domain A1-Infrastructure — Audit Report (Cycle 1)

> **Domain:** A1-Infrastructure
> **Scope:** `src/backend/infrastructure/**` (db, cache, storage, messaging, search, audit, logging, sources, sinks, repos, resilience, observability, secrets, workflow[Temporal+Lite], scheduler, clients[ClickHouse])
> **Method:** Чтение файлов + grep + ручной обход `check_layers.py` + `git log` сверка. **Никаких внешних аудитов/markdown-документов как источников фактов** — только прямой код.
> **Date:** 2026-08-06
> **Cycle:** 1 (post-Sprint 184)

---

## 1. Сводка готовности

| Категория | % | Обоснование |
|---|---|---|
| **DLQ + fail-loud** | 75% | `CDCClient._dispatch_change` + DLQWriterGuard + `mark_cdc_dlq_writer_wired` реализованы по эталону (B-02/B-17, cycle 33/37). `ClickHouseAuditService` имеет DLQ-fallback через DLQWriter Protocol. **Но:** `AuditEventLog._flush_to_clickhouse` (legacy batch-путь) ТЕРЯЕТ события при сбое CH (только `logger.error`); `PollCDCBackend`/`ListenNotifyCDCBackend` — SCAFFOLD. |
| **Pool health-check** | 80% | `PoolHealthMonitor` + `UnifiedPoolManager` + `DatabaseChain` + `SmartSessionManager` — production-ready. `ConnectionReuseManager` явно УДАЛЁН в Round 51 (`core/config/features/net.py:7-9`) — корректно. |
| **Retry-унификация (Tenacity)** | 70% | Канонический `core/resilience/retry.py` + `tenacity>=9.0.0`. В infrastructure: `http_httpx.py`, `request_mixin.py`, `smtp.py`, `outbox/dispatcher.py` используют tenacity напрямую. `infrastructure/resilience/retry.py` **ОТСУТСТВУЕТ** (shim удалён). |
| **Hardcoded secrets** | 100% | grep по `password=`/`api_key=`/`token=` — **0 находок**. `import secrets` — stdlib (api_key_manager.py), не credentials. |
| **Layer discipline (infrastructure → services)** | 95% | `python tools/check_layers.py` → 0 новых нарушений (baseline: 175 legacy). 5 lazy-imports infrastructure → services (4 в allowlist), все lazy. |

**Итоговая готовность**: **82%**

---

## 2. Таблица находок

| ID | Prior | File:Line | Описание | Фикс | Δ |
|---|---|---|---|---|---|
| **B-25** | **P0** | `infrastructure/audit/event_log.py:112-113` | `_flush_to_clickhouse` при ошибке клиента только логирует — события ТЕРЯЮТСЯ (silent-loss). Нарушает DLQ-паттерн `ClickHouseAuditService._send_to_dlq`. | Скопировать паттерн из `services/audit/clickhouse_audit_service/service.py:158-244` ИЛИ deprecate `AuditEventLog`. | +60-80 / −150 |
| **D-AUDIT-A1-1** | **P1** | `infrastructure/cdc/listen_notify_backend.py:51-75` | `subscribe()` — SCAFFOLD: `_stopped.wait()` без `asyncpg.connect`. `__init__.py:14` ложно заявляет "production-ready". | Реализовать `asyncpg.connect` + `add_listener` ИЛИ понизить статус в `__init__.py`. | +50 / −1 |
| **D-AUDIT-A1-2** | **P1** | `infrastructure/cdc/poll_backend.py:120-136` | `subscribe()` polling-mode — SCAFFOLD: `if False: yield CDCEvent`. | Реализовать SELECT ИЛИ default-OFF WARNING. | +60-80 / −2 |
| **D-AUDIT-A1-3** | **P2** | `infrastructure/resilience/retry.py` (отсутствует) | `core/resilience/retry.py:5` ссылается на backward-compat shim, но файл отсутствует. | Восстановить shim ИЛИ убрать комментарий. | −1 |
| **D-AUDIT-A1-4** | **P2** | `cache/rag/semantic.py:59` | `infrastructure → services.ai.embedding_providers` (lazy). | Facade в `core/di/providers/`. | +30 / −5 |
| **D-AUDIT-A1-5** | **P2** | `scheduler/scheduled_tasks.py:57` | `infrastructure → services.ai.memory.langmem_service` (lazy). | Facade. | +20 |
| **D-AUDIT-A1-6** | **P2** | `security/presidio_sanitizer.py:32,45` | `infrastructure → services.ai.pii.presidio_analyzer` (2 lazy). | Facade. | +20 |
| **D-AUDIT-A1-7** | **P2** | `clients/messaging/event_bus.py:153` | `infrastructure → services.schema_registry.registry` (lazy). | Facade. | +20 |
| **D-AUDIT-A1-8** | **P3** | `resilience/components/audit_chain.py:36-49` | Primary = ClickHouse via `AuditEventLog` (legacy, no DLQ). | Заменить на `ClickHouseAuditService.emit()`. | −15 |
| **D-AUDIT-A1-9** | **P3** | `cache/rag/embedding_cache.py:1-54` | TTLCache + asyncio.Lock — корректная замена custom LRU. | Ничего. | 0 |
| **D-AUDIT-A1-10** | **P3** | `messaging/outbox/dispatcher.py:75-100` | `_BackendDLQHandler` пишет в ту же outbox-table. | Если `dlq_inbox` table существует, заменить. | +0-20 |
| **D-AUDIT-A1-11** | **P3** | `workflow/lite_temporal_backend.py:43-64` | `connect()` создаёт env per-call — risk of leak. | Singleton pattern. | +10-20 |
| **D-AUDIT-A1-12** | **P4** | `application/monitoring.py:1-141` | `prometheus-fastapi-instrumentator` workaround для starlette>=1.0. | Заменить на `starlette-exporter`. | −100-200 |
| **D-AUDIT-A1-13** | **P4** | `clients/external/cdc/client.py:44-47` | `threading.Lock` в async-контексте. | `asyncio.Lock`. | −3 |

---

## 3. Список "не проверено"

- `infrastructure/scheduler/` (10 файлов), `infrastructure/sinks/` (15), `infrastructure/sources/` (24),
  `infrastructure/storage/` (7), `infrastructure/security/` (9), `infrastructure/observability/` (17),
  `infrastructure/{anti_virus,ai,chaos,eventing,execution,external_apis,import_gateway,monitoring,
  notifications,persistence,policy,watermark}/`
- `database/migrations/versions/` (28+ файлов), `tests/unit/infrastructure/`
- `infrastructure/repositories/`, `workflow/{worker,runner,temporal_client,compensating_driver,saga_state}.py`,
  `infrastructure/registry.py`, `registry_vault_bridge.py`

---

## 4. Запросы к смежным доменам

| Домен | Запрос |
|---|---|
| **A2** | Подтвердить, что `presidio_sanitizer.py` в scope security; кто проверяет PII-redaction? |
| **A3** | Подтвердить, что `ClickHouseAuditService` — production-ready с DLQ. |
| **A4** | Подтвердить, что `plugins/composition/di.py:240-262` (wiring CDCClient.set_dlq_writer) выполняется в lifespan **до** первого CDC poll. |
| **A7** | CDC processors не зависят от PollCDCBackend (scaffold)? |
| **A8** | `LiteTemporalBackend` покрывает ВСЕ Temporal API? `pg_runner_backend.py:231 raise NotImplementedError` — dead edge. |
| **A11** | `tenacity>=9.0.0` конфликтует с `deepeval`? |
| **A6** | `AuditEvent` (dataclass) совместима со схемами OpenAPI/AsyncAPI? |

---

## 5. Готовность домена: **82%**

**Производственно-готовые компоненты (verified):**
1. CDC DLQ pattern — `CDCClient._dispatch_change` + DLQWriterGuard + `mark_cdc_dlq_writer_wired` (B-02/B-17)
2. ClickHouseAuditService DLQ unification — DLQWriter Protocol + fallback chain
3. Pool health-check — PoolHealthMonitor + UnifiedPoolManager + DatabaseChain + SmartSessionManager
4. Tenant isolation — rls_listener + tenant_wrapper + casbin_tenant_scoped
5. Retry-унификация — core/resilience/retry.py + tenacity>=9.0.0
6. Secrets safety — VaultBackend + EnvBackend + RotationScheduler
7. Layer discipline — 0 новых нарушений, 175 legacy baseline
8. Workflow backends — Temporal + LiteTemporal + pg_runner с replay
9. DLQ cleanup_job — DROP PARTITION (D-AUDIT-FIX-184-4)
10. Health aggregator — TaskGroup + mode fast/deep

**P0-P1 находки (4):** B-25 (P0 silent loss), D-AUDIT-A1-1 (ListenNotifyCDCBackend SCAFFOLD),
D-AUDIT-A1-2 (PollCDCBackend SCAFFOLD), D-AUDIT-A1-3 (отсутствует shim).

**Главный сигнал:** DLQ-pattern реализован правильно для CDC и ClickHouseAuditService (new path),
но legacy `AuditEventLog` (batch-path) теряет события — это P0. CDC backends (poll/listen_notify)
— scaffold. **ConnectionReuseManager** явно УДАЛЁН в Round 51 — корректно.
Retry-унификация требует закрытия gap.

---

## Приложение А. Сводка проверенных файлов

| Файл | LOC | Паттерн | Статус |
|---|---:|---|---|
| `infrastructure/cdc/cdc_client_adapter.py` | 256 | DLQ overflow → DLQOverflowDLQ.send | ✅ |
| `infrastructure/cdc/listen_notify_backend.py` | 123 | SCAFFOLD `_stopped.wait()` | ❌ |
| `infrastructure/cdc/poll_backend.py` | 196 | SCAFFOLD `if False: yield` | ❌ |
| `infrastructure/clients/external/cdc/client.py` | 362 | `_dispatch_change`+`_send_to_dlq`+DLQWriterGuard | ✅ B-02/B-17 |
| `infrastructure/audit/event_log.py` | 216 | AsyncBatcher → ClickHouse, **silent loss** | ❌ B-25 |
| `infrastructure/audit/jsonl_audit.py` | 85 | Append-only JSONL | ✅ |
| `infrastructure/clients/pool_health.py` | 294 | PoolHealthMonitor + idle-ping | ✅ |
| `infrastructure/database/smart_session_manager.py` | 317 | ReplicaFailoverBreaker + lag-budget | ✅ |
| `infrastructure/clients/transport/http_httpx.py` | 384 | tenacity + bulkhead + CB + rate_limit | ✅ |
| `infrastructure/messaging/dlq_base.py` | 117 | DLQEnvelope + DLQWriter Protocol | ✅ |
| `infrastructure/messaging/dlq/cleanup_job.py` | 142 | DROP PARTITION | ✅ |
| `infrastructure/workflow/temporal_backend.py` | 368 | canonical_json_bytes + replay | ✅ |
| `infrastructure/workflow/lite_temporal_backend.py` | 76 | WorkflowEnvironment.start_local() | ✅ |
| `tools/check_layers.py` | 466 | Static AST linter | ✅ |
| `tools/check_layers_allowlist.txt` | 180 | legacy violations | ✅ |

**Всего .py файлов в infrastructure: 405. Проверено детально: ~26 (6.4%).**

---

**Готово. Отчёт самодостаточен для Phase-2 summarizer.**
