# KNOWN_ISSUES.md

## Sprint 21 GAP-backlog status — 2026-05-22 (active)

**Активный спринт** (coordinator-self mode, без worktree-агентов): Sprint 21 Resilience & Multi-tenancy Hardening.

**Источник**: `gap-analysis/DEEP-RESEARCH-gd_integration_tools-2026-05-20.md` + PLAN.md V22.2 FINAL §4.

**Wave-расписание** (11 коммитов):
1. `[wave:s21/backbone]` — 8 default-OFF feature-flags + team.s21 + KNOWN_ISSUES.
2. `[wave:s21/k1-w1-rls-postgres]` — Alembic RLS policy для workflow_instance + SET LOCAL listener.
3. `[wave:s21/k1-w2-tenant-cache-wrapper]` — `TenantCacheBackend(CacheBackend)`.
4. `[wave:s21/k2-w1-rpa-resilience-wrapper]` — `RPACallPolicy` Single Entry для 5 callsites.
5. `[wave:s21/k2-w2-scheduler-dlq]` — APScheduler EVENT_JOB_ERROR → DLQ + admin endpoint.
6. `[wave:s21/k2-w3-webhook-resilience]` — WebhookSink + webhook_scheduler через RPACallPolicy.
7. `[wave:s21/k3-w1-desktop-rpa-pool]` — `DesktopRPASessionPool` с persistent httpx + session affinity.
8. `[wave:s21/k3-w2-browser-cookies-redis]` — `save_cookies/restore_cookies` через Redis hash.
9. `[wave:s21/k3-w3-workflow-state-persist]` — `WorkflowState` model + alembic + pg_runner integration.
10. `[wave:s21/k5-w1-streamlit-tenant-admin]` — Streamlit page 81 tenant inspection.
11. `[wave:s21/closure]` — finale + DoD verify + memory note.

### Sprint 21 carryover (включён в W8)

- **S17 K-OPS-1 saga_state_store** — реализация перенесена в `[wave:s21/k3-w3-workflow-state-persist]` под тем же feature-flag `saga_state_persistence_enabled` + новый `workflow_state_sqlite_persist`. После W8 carryover ⇒ `[Resolved: S21 W8 carryover]`.

### Открытые риски Sprint 21

1. **W1 ограничен 1 таблицей** (`workflow_instance`) — `orders/users/files` НЕ имеют колонки `tenant_id`. Полный RLS откладывается в S22 (требует preceding migration на добавление колонок).
2. **Alembic offline-режим** — applied миграции valid через `alembic upgrade head --sql`; фактическая RLS verifiable только в integration test с реальным Postgres.
3. **LiteTemporalBackend** уже использует builtin SQLite через `WorkflowEnvironment.start_local()` — explicit aiosqlite wrapper НЕ создаётся; W8 фокус на saga compensating model.
4. **Параллельная сессия** может изменять carryover-файлы (`saga_state.py`) — `git commit -- <pathspec>` обязателен.

---

## GAP-аудит 2026-05-21 — 10-слойный pre-production аудит (L1–L10)

**Контекст**. Сквозной аудит платформы перед production-rollout по 10 архитектурным слоям × 4 вектора (читаемость / надёжность / расширяемость / функциональность). Среднее по слоям — **5.7/10**. Слабые слои — **L6 Data&State (3.0)** и **L7 Observability (5.0)**, оба заблокированы Python 2-стилем except-clauses в **70+ файлах** (точный grep `-l` = 71; первоначальная оценка «47» переоценивала локализацию L6/L7 — реальный охват шире, включает `dsl/`, `services/`, `entrypoints/`). Сильный слой — **L8 Security (7.0)** с defence-in-depth (CapabilityGate + WAF + AI Safety).

**Источник findings**: 10 параллельных Explore-агентов, протокол `ОТЧЁТ:[ID]:[СЛОЙ]`. Полный синтез — coordinator session 2026-05-21.

### 🔴 КРИТИЧЕСКИЕ блокеры (P0 → Sprint 17, объём — все 17)

**Группа SYNTAX (Python 2-style `except E1, E2:`) — CI gate провалится при импорте**
- `K-SYN-1` `infrastructure/observability/tracing.py:60,87` → DSL tracing разрушается на import
- `K-SYN-2` `core/ai/workspace_manager.py:248` → AI Safety lifespan не запускается
- `K-SYN-3` `entrypoints/mcp/mcp_server.py:142` → FastMCP server падает на init
- `K-SYN-4` `dsl/engine/processors/rpa.py:816` → RPA processors неимпортируемы
- `K-SYN-5` `infrastructure/database/database.py:246,281`, `pool_monitor.py:97` + 10+ файлов в `clients/storage/logging/secrets/` (всего **70+ файлов** repo-wide; точный grep `-l` = 71; помимо L6/L7 затронуты `dsl/`, `services/`, `entrypoints/`)
- **Исправление**: `tools/codemods/fix_except_clause.py` (libcst) + единый wave-коммит `[wave:s17/k1-w0-python3-except-clause-sweep]`.

**Группа TLS-VIOLATION (V1 hotfix)**
- `K-TLS-1` `infrastructure/clients/transport/ftp.py:52-54,83-85` → FTPS с `ssl.CERT_NONE` (V1 violation)
- `K-TLS-2` `infrastructure/sources/email.py` → IMAP CERT_NONE (V1 legacy)
- `K-TLS-3` `entrypoints/email/imap_monitor.py` → фоновый мониторинг почты без TLS-verification
- **Исправление**: заменить на `ssl.create_default_context()` + `verify_mode=CERT_REQUIRED`; unit-test `assert ctx.verify_mode == CERT_REQUIRED`.

**Группа ARCHITECTURE (V22 centralization)**
- `K-ARCH-1` AuthorizationGateway отсутствует (R-V15-6) — см. [ADR-NEW-1](DECISIONS.md#adr-new-1)
- `K-ARCH-2` CapabilityGateway Protocol в `core/interfaces/` отсутствует — см. [ADR-NEW-4](DECISIONS.md#adr-new-4)
- `K-ARCH-3` Routes (`routes/<name>/`) не проходят capability-gate — `services/routes/loader.py:70` нет `gate.declare()` вызова перед pipeline_registrar
- `K-ARCH-4` Tenant-aware routes не работают — `RouteManifestV11.tenant_aware` читается, но `RouteLoader` не пробрасывает `TenantContext.current_tenant()` в DSL-шаги (data leak между тенантами)
- `K-ARCH-5` `call_function_modules` dev fallback — `dsl/engine/processors/function_call.py:118-119` пропускает проверку при пустом whitelist (RCE в production)

**Группа OPERATIONAL (pre-prod-check + DR)**
- `K-OPS-1` Saga state store отсутствует — нет модели для compensations / rollback-events
- `K-OPS-2` K8s manifests неполные — есть только HPA для temporal-worker, нет Deployment/Service/PDB/Ingress/HPA для main app
- `K-OPS-3` `make pre-prod-check v2 (38/38)` не реализован — V22 DoD блокируется
- `K-OPS-4` БД migrations не интегрированы в deploy-flow — нет init-container в docker-compose/k8s
- `K-OPS-5` Backup/DR procedures отсутствуют — нет `ops/backup/` scripts, нет runbook'ов для pg_dump/redis-persist/clamav-update/restore
- `K-OPS-6` CI/CD deployment pipeline отсутствует — `.github/workflows/release.yml` только dry-run

### 🟡 СЕРЬЁЗНЫЕ пробелы (P1 → Sprint 18–S19)

**L1 Gateway**
- `S-L1-1` Plugin-registry для middleware отсутствует (см. [ADR-NEW-2](DECISIONS.md#adr-new-2))
- `S-L1-2` Per-route middleware override невозможен — TimeoutMiddleware один global
- `S-L1-3` Unified RequestContext отсутствует (см. [ADR-NEW-3](DECISIONS.md#adr-new-3))
- `S-L1-4` IdempotencyHeaderMiddleware крашится при Redis-miss — нет graceful fallback на MemoryBackend
- `S-L1-5` DataMaskingMiddleware placement выше AuthRequiredMiddleware — masking фейлит до auth → нечитаемая 500-я

**L2 Core**
- ~~`S-L2-1`~~ **REVISED 2026-05-21**: `Exchange.stopped` НЕ баг — реализован как property через `properties["_stopped"]` (`exchange.py:92-160`). Pipeline корректно вызывает `set_stopped()` / `is_stopped()`. Phase A verification (code-grep) подтвердила: AttributeError не воспроизводится. Перенесено в НЕЗНАЧИТЕЛЬНЫЕ ниже как readability nuance.
- `S-L2-2` Lifecycle не идемпотентна — `register_provider()` перезаписывает без check (двойной startup при hot-reload)
- `S-L2-3` ActionMetadata не содержит retry-policy поля → W14.1 Gateway не достроен
- `S-L2-4` `providers.py` (149 функций) все возвращают `Any` — mypy не видит контракты

**L2 НЕЗНАЧИТЕЛЬНЫЕ (readability/maintainability, не блокеры)**
- `S-L2-1nano` (бывший S-L2-1): `Exchange.stopped` — design choice через `properties` dict вместо first-class dataclass field. Корректно работает, но снижает self-documentation Exchange API. Опционально: вынести в `__slots__` или dataclass field — задача S+2 после стабилизации DSL. Не блокирует production.

**L4 AI Pipelines**
- `S-L4-1` `KycAmlVerifyProcessor` / `AntiFraudScoreProcessor` / `CreditScoringRagProcessor` — empty shells (только `exchange.set_property(...)`); banking domain non-functional
- `S-L4-2` Guardrails pre-LLM enforcement отсутствует — `rebuff_client/lakera_client` есть, но не подключены в LLMCallProcessor
- `S-L4-3` LangMem `consolidate()` — stub-placeholder
- `S-L4-4` Multipart bulk-ingest endpoint для RAG отсутствует (только Python API через `rag_bulk_ingest.py`)
- `S-L4-5` MCP tool_handler не имеет видимой auth-check перед `_action_bridge`

**L5 RPA**
- `S-L5-1` Browser context leak при exception — `rpa_browser.py:104-111` не release контекст обратно в pool
- `S-L5-2` Browser RPA нет session persistence (каждый запрос = новый login)
- `S-L5-3` RPA browser requests не идут через WAF (V15 R-V15-5 violation)
- `S-L5-4` Desktop RPA selector не валидируется (selector injection)

**L6 Data&State**
- `S-L6-1` ConnectionReuseManager отключён по умолчанию (`feature-flag=False`)
- `S-L6-2` DLQ TTL/vacuum отсутствует — записи копятся бесконечно
- `S-L6-3` ClickHouse audit retention без TTL партиций
- `S-L6-4` Read-replica failover полунеполный — только одна replica, нет multi-replica failover, нет replication-lag monitoring
- `S-L6-5` Outbox worker stuck-detection отсутствует
- `S-L6-6` Vault rotation не zero-downtime (прямая смена secret без graceful reconnect)

**L7 Observability**
- `S-L7-1` ClickHouse audit без retry/DLQ → `_flush_to_clickhouse()` только логирует ошибку, batch теряется
- `S-L7-2` OTel `trace_id` не пробрасывается в structlog event_dict (logs/traces разъединены)
- `S-L7-3` Graylog GELF socket не закрывается → FD leak под нагрузкой (≥10K RPS)
- `S-L7-4` Нет global fallback-sink при сбое всех logging sinks
- `S-L7-5` Кросс-сервисная trace_id propagation в Kafka/RabbitMQ headers отсутствует
- `S-L7-6` Prometheus labels без `tenant_id` (per-tenant billing нет)

**L8 Security**
- `S-L8-1` Casbin tenant-scoped реализован, но `CapabilityPolicy` интеграция отсутствует
- `S-L8-2` OPA-client есть, но нет runtime-query в DSL/auth-guard
- `S-L8-3` ServiceDSLRegistry не валидирует capability-subset при `@service_dsl` регистрации
- `S-L8-4` PII masker нет global response-middleware (только per-DSL шаг)
- `S-L8-5` JWT jti-blacklist неполная (не batch-revoke при ключе rotation)
- `S-L8-6` OWASP ZAP gate в CI non-blocking (`make audit-zap` warns only)

**L9 DevOps**
- `S-L9-1` Granian RSGI graceful_timeout не сконфигурирован
- `S-L9-2` docker-compose без `mem_limit/cpus` (runaway memory)
- `S-L9-3` Multi-environment configs (dev/staging/prod.yml) отсутствуют
- `S-L9-4` Blue/Green script — stub-реализация (nginx config-generator отсутствует)
- `S-L9-5` Observability stack (Prometheus/Grafana/Graylog) не в docker-compose

**L10 Test Coverage**
- `S-L10-1` Public testkit/ API для extensions отсутствует
- `S-L10-2` Property-based testing (hypothesis) 0% использования
- `S-L10-3` Mutation testing (mutmut) отсутствует
- `S-L10-4` E2E тестов только 1 файл (нужно 5+ smoke-маршрутов)
- `S-L10-5` Plugin/extension coverage <10% (62 из 662 файлов)

### 🟢 СИЛЬНЫЕ СТОРОНЫ (production-grade, цитировать в docs)

- **L8 Security (7/10)** — CapabilityGate (LRU-кэш + subset-проверка) + WAF strict (`OutboundHttpClient` + `check_waf_coverage` CI gate) + AI Safety workspace (TTL + per-tenant quota) + webhook HMAC + immutable audit-log (HMAC-chain)
- **L1 Auth (централизована)** — `AuthRequiredMiddleware` 6 методов (JWT + API-key + mTLS + SAML + joserfc + jwks-cache); маршруты auth-агностичны
- **L1 Идемпотентность** — `IdempotencyHeaderMiddleware` + Redis NX (атомарная блокировка pending-ключа)
- **L1 WAF + payload scanner** — async `ClamAVPayloadScanner` через TCP (Sprint 16 B-3 finale)
- **L2 Protocol-oriented design** — 8 `@runtime_checkable` Protocol-ов в `core/protocols.py` (LLMProvider, MemoryBackend, BrowserAutomation и др.)
- **L2 Camel-style Exchange/Pipeline** — `Exchange(meta/in_message/out_message/properties/status/error)` + `Pipeline` с processor-chain
- **L3 V11 Plugin Manifest** — полная TOML-декларация (name/version/requires_core/capabilities[]/provides{}) с capability-gate ДО import
- **L3 RouteBuilder API 95%** — 150+ методов в миксинах; `.crud_*` / `.get_setting()` / `.validate_response()` / `.invoke_workflow()` / `.call_function()`
- **L3 Hot-Swap runtime** — graceful shutdown → module reload → capability re-allocation
- **L4 AI Safety workspace isolation** — `AIFsFacade` с path-traversal trap + `fs.read.<path>` / `fs.create_new.<workspace>` capability-gates
- **L4 PII masking reversible** — 6 паттернов (email/phone/INN/SNILS/passport/card) с восстановлением через `replacements` dict
- **L7 OTel auto-instrumentation** — 9 компонентов (FastAPI/httpx/SQLAlchemy/asyncpg/Redis/Kafka/RabbitMQ/MongoDB/gRPC); fail-graceful
- **L7 Structured logging** — structlog JSON + 3 backend routing (console/disk/Graylog) + batching wrapper + circuit-breaker
- **L7 11 Grafana dashboards** — AI cost / latency / DB pool / DLQ / resilience / Temporal / workflow SLA
- **L9 Multi-stage Docker** — slim-bookworm + nonroot (UID 10001) + tini init + 750 permissions + SUID removal
- **L9 Graceful shutdown** — `TaskRegistry.shutdown_all()` + DSLYamlWatcher → WorkflowRuntime → PluginLoader cascade
- **L9 Health endpoints** — `/liveness` / `/readiness` / `/startup` / `/components` (K8s probes-семантика)
- **L9 Blue/Green pattern** — `docker-compose.bluegreen.yml` + state file + nginx router stub
- **L10 Test breakdown** — 3639 collected; 662 файлов; 178 fixtures; 26 chaos сценариев; 11 backend'ов покрыты (Redis/Postgres/Kafka/RabbitMQ/MongoDB/ES/S3/Temporal/Vault/Graylog/ClickHouse/NATS)

### Аудит Gateway-централизации (15/22 функций централизованы, 68%)

Полная таблица см. в Phase 2 синтезе coordinator-session 2026-05-21. P0/P1 функции, требующие доработки:
- **P0**: rate-limit global middleware (нет в `setup_middlewares.py`); timeout per-route (`TimeoutMiddleware` глобален)
- **P1**: correlation→OTel trace_id binding в structlog; response-validation middleware; circuit-breaker enforcement в DSL; metrics cardinality (tenant_id label); audit retry+DLQ для ClickHouse; PII auto-mask response middleware

### Связь с PLAN.md

- **Sprint 17 (replace V22 GAP-driven)** — все 17 KРИТИЧЕСКИХ блокеров + ADR-NEW-1..4 architectural backbone
- **Sprint 18** — Operational/Security (S-L1, S-L7, S-L8) + 10 функциональных предложений из Phase 3 диалога
- **Sprint 19** — DSL/AI расширения (S-L4) + 6 функциональных предложений (workflow versioning, route composition, route authz, multipart RAG, reranking, RPA sessions)
- **Sprint 20** — Coverage finale + pre-prod-check v2 38/38 + DR & Backup verified
- **Sprint 21-23 (NEW V22.2 FINAL, post-production)** — 28 пунктов из `gap-analysis/DEEP-RESEARCH-gd_integration_tools-2026-05-20.md` + 5 follow-up. См. секцию «Sprint 21-23 GAP-backlog» ниже.

---

## GAP-анализ V2 (2026-05-21) — уточнения после цикла самокритики

**Контекст**. После первого анализа (V1, 668 LOC, 10 суб-агентов) запущен цикл
итеративной самокритики: Critic + Devil's Advocate + Integration Bus Expert.
Принято 14 замечаний из 17. QUALITY_SCORE: 51 → 74/100 (Δ ~41%).
Полный отчёт: `gap-analysis/GAP-ANALYSIS-V2-gd_integration_tools-2026-05-21.md`.

### Ключевые уточнения V2 vs V1

| ID | Изменение | Источник |
|----|-----------|---------|
| B-01 | Снижен до G-01 (auth chain — defense-in-depth, не блокер) | Адвокат D1 |
| B-03 | TenantNamespacedCache УЖЕ СУЩЕСТВУЕТ (`core/tenancy/cache.py`) — проблема в интеграции | Критик NK-03 |
| DLQ | "Отсутствует" → "infrastructure ЕСТЬ, не подключена к CDC/webhook/filewatcher" | Критик NA-05 |
| L2 | 8/10 → 7/10 (активный B-04 блокер) | Критик CD-02 |
| B-02 | Усилена формулировка: CDC `_dispatch_change` ТЕРЯЕТ события без DLQ | Шина-эксперт |
| B-11 | Добавлен: Idempotency только middleware-level, processor-level отсутствует | Шина-эксперт |
| G-17 | Добавлен: BrowserPool ad-hoc context leak при contention | Шина-эксперт |
| P0 | Убран TenantMiddleware из P0 (SPOF-риск) | Адвокат D2 |

### Финальные блокеры V2 (11 штук)

#### 🔴 B-02 [L5] Resilience-примитивы не применяются к RPA/CDC
**Файлы:** `src/backend/services/rpa/browser_pool.py`, `src/backend/entrypoints/cdc/cdc.py:497`,
`src/backend/services/ops/file_watcher.py`, `src/backend/services/ops/webhook_scheduler.py`
**Проблема:** CDC `_dispatch_change` ловит `except Exception` и просто ЛОГИРУЕТ →
событие ТЕРЯЕТСЯ. Resilience infrastructure ЕСТЬ, но не применяется.
**Статус:** Открыта | В работе: `s21/k2-w1-rpa-resilience-wrapper`

#### 🔴 B-03 [L6] Tenant cache isolation — TenantNamespacedCache не интегрирован
**Файлы:** `src/backend/infrastructure/cache/redis_cluster.py` (а НЕ `redis_cluster_adapter.py`),
`src/backend/infrastructure/storage/s3_cache.py` (а НЕ `s3_cache_adapter.py`)
**Инфраструктура:** `src/backend/core/tenancy/cache.py::TenantNamespacedCache` (96 строк) — УЖЕ СУЩЕСТВУЕТ.
**Проблема:** Кеш-адаптеры НЕ используют TenantNamespacedCache. Redis keys без tenant prefix.
**Статус:** Открыта | В работе: `s21/k1-w2-tenant-cache-wrapper`

#### 🔴 B-04 [L2] Hot-swap одного плагина делает shutdown_all()
**Файл:** `src/backend/core/plugin_runtime/hot_swap.py:213`
**Проблема:** `loader.shutdown_all()` убивает ВСЕ плагины, не только целевой.
**Статус:** Открыта | Планируется: `s19/k3-w6-plugin-hot-swap-v2`

#### 🔴 B-05 [L6] Workflow state не персистится
**Файл:** `src/backend/core/orchestration/temporal_backend.py`
**Проблема:** LiteTemporalBackend — only for development. In-flight workflows теряются.
**Статус:** Открыта | В работе: `s21/k3-w3-workflow-state-persist`

#### 🔴 B-06 [L8] DataMaskingMiddleware не использует core PII masker
**Файл:** `src/backend/entrypoints/middlewares/data_masking.py`
**Проблема:** Partial redaction, но `core/security/pii_masker.py::default_masker()` (8 типов PII) не используется.
**Статус:** Открыта | В работе: `s22/k1-w2-pii-masker-unify`

#### 🔴 B-07 [L8] SecurityHeadersMiddleware race condition
**Файл:** `src/backend/entrypoints/middlewares/security_headers.py`
**Проблема:** BaseHTTPMiddleware применяет заголовки после ASGI-цепочки.
**Статус:** Открыта | В работе: `s22/k1-w1-security-headers-asgi`

#### 🔴 B-08 [L10] Smoke-тестов критически мало (2 файла)
**Файлы:** `tests/smoke/test_sentry_init.py`, `tests/smoke/test_yaml_hot_reload.py`
**Проблема:** 2 smoke-теста вместо 15. CI/CD не верифицирует что приложение поднимается.
**Масштаб:** ~1 спринт, не архитектурная проблема.
**Статус:** Открыта | В работе: `s22/k2-w1-smoke-tests`

#### 🟡 B-09 [L5] Desktop RPA создаёт новый Application() каждый запрос
**Файл:** `windows_worker/handlers/desktop_rpa_handler.py`
**Статус:** Открыта | В работе: `s21/k3-w1-desktop-rpa-pool`

#### 🟡 B-10 [L4] Multi-agent supervisor — stub
**Файл:** `src/backend/services/ai/agents/multi_agent.py:_compile_graph`
**Статус:** Открыта | В работе: `s23/k4-w1-multiagent-supervisor-llm`

#### 🟡 B-11 [L3] Idempotency только middleware-level — processor-level отсутствует
**Файл:** `src/backend/dsl/engine/processors/eip/idempotency.py`
**Проблема:** EIP IdempotencyProcessor не связан с IdempotencyMiddleware.
**Статус:** Открыта | Планируется

### Новые улучшения V2 (добавлены)

#### 🟡 G-01 [L1] Auth chain централизована, но не декларативно переопределяема
**Файл:** `src/backend/entrypoints/middlewares/setup_middlewares.py`
**Примечание:** Defense-in-depth архитектурный выбор, не баг. Перенесено из B-01.
**Статус:** Открыта | Планируется: `s17 ADR-NEW-2`

#### 🟡 G-17 [L5] BrowserPool ad-hoc context leak при contention
**Файл:** `src/backend/services/rpa/browser_pool.py:164-170`
**Проблема:** При acquire() когда все в use — создаётся unmanaged context, НЕ в пуле.
**Статус:** Открыта

---

## Sprint 21-23 GAP-backlog (DEEP-RESEARCH 2026-05-20) — post-production без дат

**Контекст**. После Sprint 20 (`v1.0.0-production`) начинается post-production backlog S21-S23 (PLAN.md V22.2 FINAL §4) для закрытия 28 нерешённых GAP-пунктов из `gap-analysis/DEEP-RESEARCH-gd_integration_tools-2026-05-20.md` (668 LOC, Hermes Agent ultrathink, 10 L1–L10 субагентов).

**Финальная оценка готовности** до S21-S23: **6.3/10** → после S21-S23: **≥ 8.5/10** (production-grade).

**Решения пользователя 2026-05-21**:
1. 3 спринта S21-S23 (Resilience+Multi-tenancy / Observability+Testing / AI/DSL/DX).
2. Новый scope + follow-up к частично покрытым в S17-S20.
3. БЕЗ дат — не блокирует release v1.0.0.

### Покрыто в S17-S20 (НЕ дублируется в S21-S23)

| GAP | Локация в PLAN.md V22.2 |
|-----|--------------------------|
| B-01 Middleware auth-agnostic | S17 ADR-NEW-2 |
| G-01 RequestContext | S17 ADR-NEW-3 |
| G-11 WAF strict default | S18 W1 WAF-allowlist tightening |
| G-12 28 CVEs | S18 W1 supply-chain-finale |
| F-13 Secret rotation | S16 W7 vault-rotation |
| ADR-NEW-9 Multi-tenancy reduce | S18 W6 |
| B-04 Hot-Reload disable | S19 W6 ADR-NEW-7 (disable вариант) |

### Частично покрыто — follow-up в S21-S23

| GAP | Текущее покрытие | Follow-up |
|-----|-------------------|-----------|
| B-06 PII masker | S18 W1 PII response MW | S22 К1 W2 (unification всех слоёв) |
| G-04 Guardrail enforcement | S18 W18 enforcer | S23 К4 W2 (framework F-04) |
| G-05 AI Sandbox NoOp | S18 R1.20 sandbox strategy | S23 К4 W3 (e2b finalize) |
| F-08 Workflow versioning | S19 K3 workflow-versioning-routes | S23 К3 W3 (migration runtime) |
| F-15 Chaos CI | S20 W6 chaos-finale | S23 К5 W3 (PR-gate) |

### НЕ покрыто (28 пунктов) → wave-ids в S21-S23

| Sprint | Команда | GAP-пункты | Wave-ids |
|--------|---------|------------|----------|
| **S21** | К1 | B-03 Tenant cache (A-03), G-08 RLS | `s21/k1-w1-rls-postgres`, `s21/k1-w2-tenant-cache-wrapper` |
| **S21** | К2 | B-02 RPA resilience (A-05), G-07 Webhook resilience, G-09 Scheduler DLQ | `s21/k2-w1-rpa-resilience-wrapper`, `s21/k2-w2-scheduler-dlq`, `s21/k2-w3-webhook-resilience` |
| **S21** | К3 | B-05 Workflow state (A-04), B-09 Desktop RPA pool, G-06 Browser cookies | `s21/k3-w1-desktop-rpa-pool`, `s21/k3-w2-browser-cookies-redis`, `s21/k3-w3-workflow-state-persist` |
| **S21** | К5 | Streamlit page 81 | `s21/k5-w1-streamlit-tenant-admin` |
| **S22** | К1 | B-06 PII unify (A-07), B-07 SecurityHeaders ASGI (A-06) | `s22/k1-w1-security-headers-asgi`, `s22/k1-w2-pii-masker-unify` |
| **S22** | К2 | B-08 Smoke tests, G-15 MW integration tests, G-16 Property-based tests, F-10 Obs tests, G-10 AlertManager | `s22/k2-w1-smoke-tests`, `s22/k2-w2-middleware-integration-tests`, `s22/k2-w3-hypothesis-suite`, `s22/k2-w4-observability-test-suite`, `s22/k2-w5-alertmanager-rules` |
| **S22** | К3 | G-02 Processor DI | `s22/k3-w1-processor-di` |
| **S22** | К4 | F-11 Semantic cache heatmap | `s22/k4-w1-semantic-cache-heatmap` |
| **S22** | К5 | F-02 CB Dashboard, F-09 Rate-limit Dashboard, F-14 SLA Dashboard | `s22/k5-w1-cb-dashboard`, `s22/k5-w2-ratelimit-dashboard`, `s22/k5-w3-sla-dashboard` |
| **S23** | К1 | G-14 Docker registry push | `s23/k1-w1-docker-registry-push` |
| **S23** | К3 | G-03 Workflow hot reload, F-01 Schema Registry, F-03 Route Marketplace, F-05 Webhook retry declarative | `s23/k3-w1-workflow-hot-reload`, `s23/k3-w2-schema-registry-rest`, `s23/k3-w3-blueprints-marketplace`, `s23/k3-w4-webhook-retry-policy` |
| **S23** | К4 | B-10 Multi-agent supervisor, F-04 AI Guardrails framework, F-06 Plugin Sandbox e2b | `s23/k4-w1-multiagent-supervisor-llm`, `s23/k4-w2-ai-guardrails-framework`, `s23/k4-w3-plugin-sandbox-e2b` |
| **S23** | К5 | G-13 Backend HPA, F-07 Multi-region scaffold, F-15 Chaos CI PR-gate | `s23/k5-w1-backend-hpa`, `s23/k5-w2-multi-region-scaffold`, `s23/k5-w3-chaos-ci-pr-gate` |

### 4 новых ADR (ADR-NEW-12..15)

См. `.claude/DECISIONS.md::## ADR из DEEP-RESEARCH Sprint 21-23 (post-production gap-backlog)`:
- **ADR-NEW-12** — RLS Strategy (PostgreSQL Row-Level Security + SET LOCAL) — S21 W1.
- **ADR-NEW-13** — RPACallPolicy (единый resilience wrapper для RPA/CDC/FileWatcher/Webhook/DesktopRPA) — S21 W3.
- **ADR-NEW-14** — Workflow State Persistence (SQLite LiteTemporal + Temporal Cloud) — S21 W8.
- **ADR-NEW-15** — Chaos PR-gate (on-PR triggered chaos tests with label `needs-chaos`) — S23 W11.

### Backlog после S23 (если потребуется V23+)

См. PLAN.md §9:
- Schema Registry V2 — production hardening после S23 W3.
- Multi-region production rollout (Consul + DNS-based discovery) — после S23 W10 scaffold.
- e2b cost optimization + AWS Firecracker fallback — после S23 W8.
- DSPy LLM optimization pipeline (cost-aware prompt compression).
- Distributed tracing для AI inference pipeline (LangFuse + Phoenix Arize).
- Per-tenant cryptographic isolation (M-C use case) — revert ADR-NEW-9.

---

## Sprint 17 — GAP P0 Closure + Centralization Hardening (открыто 2026-05-21)

**Источник:** GAP-аудит 2026-05-21 (10 слоёв × 4 вектора, среднее 5.7/10), ADR-NEW-1..4, PLAN.md V22 §S17 (197–256).
**Срок:** 2026-06-05 → 2026-06-18 (2 недели, 5 команд).
**Backbone:** [wave:s17/backbone] — 12 default-OFF feature-flags + `[team.k1..k10]` (новый team-ownership.toml) + эта секция KNOWN_ISSUES.

### Wave в работе текущей сессии (2026-05-21)

Запланировано 7 коммитов (опционально +1):

1. `[wave:s17/backbone]` — 12 flags + ownership + KNOWN_ISSUES (этот раздел).
2. `[wave:s17/k3-w0-routes-capability-gate]` — K-ARCH-3 закрытие.
3. `[wave:s17/k1-w3-call-function-whitelist-strict]` — K-ARCH-5 закрытие.
4. `[wave:s17/k5-w3-db-migration-init-container]` — K-OPS-4 закрытие.
5. `[wave:s17/k1-w2-authorization-gateway]` — ADR-NEW-1+4 scaffold (Protocol + Gateway).
6. `[wave:s17/k3-w1-unified-request-context]` — ADR-NEW-3 scaffold (frozen dataclass + MW).
7. `[wave:s17/k2-w1-metrics-registry]` — D11 backbone (idempotent counter/histogram/gauge).
8. Optional: `[wave:s17/k2-w3-task-registry-coverage]` — миграция orphan asyncio.create_task.

### Wave-карриовер S17 → следующие сессии

- `[wave:s17/k1-w0-python3-except-clause-sweep]` — codemod 70+ файлов (отдельная wave, F-A-4 pre-test gate на 5+ callsites).
- `[wave:s17/k1-w1-tls-cert-required]` — требует S16 DoD-3 closure.
- `[wave:s17/k3-w0-routes-tenant-aware]` — K-ARCH-4 (после backbone готова).
- `[wave:s17/k3-w2-middleware-registry]` — ADR-NEW-2.
- `[wave:s17/k1-w4-config-validator]` — D14.
- `[wave:s17/k2-w2-metrics-migrate]` — sweep 52 inline callsites (после k2-w1).
- `[wave:s17/k2-w4-apscheduler-observability]` — D13b.
- `[wave:s17/k3-w3-correlation-id-end-to-end]` — D12 (после RequestContext landed).
- `[wave:s17/k7-w1-observability-fixes]` — S-L7-1..3.
- `[wave:s17/k5-w1-tenant-feature-toggle-ui]` — D9.
- `[wave:s17/k2-w5-resilience-coordinator-class]` — требует fix circular import `core/resilience/__init__.py`.
- `[wave:s17/k3-w4-saga-state-store]` — K-OPS-1.
- `[wave:s17/k5-w2-k8s-manifests]` — K-OPS-2.
- `[wave:s17/k9-w1-pre-prod-check-v2-scaffold]` — K-OPS-3 (после backbone готов).
- `[wave:s17/k1-w5-backup-dr-scaffold]` — K-OPS-5.
- `[wave:s17/closure]` — финал Sprint 17 (DoD verify + memory + CONTEXT/ARCHITECTURE update).

### Active blockers (см. `.claude/team-ownership.toml::[blockers]`)

- ~~**b1_circular_import_degradation**~~ — **RESOLVED 2026-05-21** в `b1f68b97 [wave:s17/k2-w0-fix-circular-degradation]`. Reorder в `core/resilience/__init__.py` (degradation ПЕРЕД decorators); `pytest --co tests/unit/infrastructure/workflow/test_lite_temporal_backend.py` 7 collected, 95/95 resilience-тестов passing.
- **b2_s16_dod3_tls_cert_none** (owner: k1) — **PARTIAL CLOSURE 2026-05-21** в `a6a9a098 [wave:s17/k1-w1-sftp-known-hosts-strict]`: SFTP-вектор закрыт через `_resolve_known_hosts()` + `TRANSPORT_SFTP_KNOWN_HOSTS_PATH`. Carryover: 6 callsites CERT_NONE в FTP/IMAP/POP3 → `[wave:s17/k1-w1-tls-cert-required]` (требует asyncssh pool migration + testcontainers FTP/IMAP).
- **b3_s16_dod9_pybreaker_finalize** (owner: k2) — **PARTIAL CLOSURE 2026-05-21** в `69a19197 [wave:s17/k2-w4-pybreaker-restore]`: `make_pybreaker_adapter` factory + `v11.pybreaker_enabled=False` feature-flag + DoD-9 restart acceptance test (state=open после restore, fail_counter=5) на InMemory-векторе. Carryover: pybreaker SDK dependency + RedisBreakerStateStorage + integration в `ResilienceCoordinator` → `[wave:s17/k2-w4-pybreaker-replace]` (S17 W1).
- **b4_gap_audit_p0_remediation** (owner: k1) — K-SYN/K-TLS/K-ARCH/K-OPS общая координация (70+ файлов техдолга; `ftp.py:170` snapped в b2 partial). ETA: S17.

### Closure DoD (см. PLAN.md V22 §S17 строки 240–256)

- 15 DoD-критериев (K-SYN/K-TLS/K-ARCH/K-OPS/D9..D14/coverage 77%/mypy=0).
- Memory: `feedback_sprint17_gap_closure_centralization`.
- CONTEXT.md / ARCHITECTURE.md обновлены слои L1–L10.

---

## Sprint 15 kickoff — 2026-05-20 (DX Tooling + Innovation, Production-Ready Final)

**Активные задачи** (28 atomic commits — backbone + 25 wave + 6 closure):

* **Backbone**: 5 feature-flags (sandbox_amortised_psutil / arch_map_llm_search_enabled /
  ai_pr_review_enabled / dsl_visual_editor_drag_drop / changelog_autogen_enabled),
  team_s15.k1..k5 секции в team-ownership.toml.
* **Phase A — Production-Gates**:
  - F-2 sandbox overhead reduction (carryover S14).
  - mypy=0 (DoD #9).
  - Final security audit (OWASP ZAP + API top 10).
  - Perf bench ratchet (p95≤80ms, RPS≥1500).
  - `manage.py diagnose` aggregator.
* **Phase B — DSL/LSP**: F-5 .pyi fidelity (carryover S14), LSP server, YAML schema,
  Visual Editor finale.
* **Phase C — DX Scaffolding**: VSCode extension+sign, make new-adr, CLI completions,
  changelog autogen, AI PR review.
* **Phase D — Documentation**: Arch Map (page 83) + LLM search, ADR-tab, dep-map HTML,
  tutorial progress, changelog diff (page 85).

**DoD finale**: 11/11 (см. план §8).

---

## Sprint 12 closure (Workflow Enhancement) — 2026-05-20

**Закрыто** (17 atomic wave + backbone + closure в одной coordinator-self сессии):

* **Backbone** — 18 feature-flags + 5 team_s12.k1..k5 секций.
* **K1 Security** (2 wave): workflow_audit_log extended + admin inventory;
  Temporal mTLS Vault PKI + cert rotation + docker runbook.
* **K2 Resilience+Perf** (2 wave): SLA Grafana dashboard 99% SLO + Prometheus
  counter; TemporalWorkerScaler HPA exporter + K8s manifest.
* **K3 DSL/Workflow** (8 wave): visual diff (Graphviz) + cron builder UI +
  pre-run cost estimator + reactive event-driven triggers + 10 workflow
  templates с semantic search + saga compensation viewer + .cancel_workflow()
  DSL step + versioning UI (pin/rollback).
* **K4 AI/Data** (2 wave): 3 production AI examples
  (RAG saga / multi-agent / code-interpreter loop); LLM cost breakdown с
  Anthropic 4.x/OpenAI pricing.
* **K5 Frontend+Ext** (3 wave): page 33 templates + Mermaid; page 72 HITL
  History tab + CSV export; page 14 Cron Dashboard.

### Открытые carryover (S12 → S13/S14)

* AI workflow examples — declarative-only; нужны bound handler'ы
  в `services.ai.*` (S13+).
* `feedback_cron.register` lifecycle wiring (S11 carryover остаётся).
* Protocol-extraction 29 acknowledged baseline (отдельный S14+).
* Integration smoke для mTLS требует Vault + docker-compose.bluegreen.yml
  (default-OFF flag).
* `dspy_feedback_loop` cron registration в lifecycle.py.

---

## Sprint 11 closure (AI/RAG Completion) — 2026-05-20

**Закрыто** (22 atomic wave в одной coordinator-self сессии):

* Phase 0 (1): `[wave:s11/backbone]` — 10 feature-flags + 7 capabilities +
  multimodal-rag extra + KNOWN_ISSUES.
* Phase 1 (6 carryover S10/S9) — все pre-prod-check gates 01/04/06/08/11 → PASS:
  * `uv-resolver-fix` — mlflow pyarrow override + ai-voice py3.14 marker.
  * `layer-violations-zero` — Protocol extraction (quotas) + 28 acknowledged baseline.
  * `docstring-cli-args` — gate 11 + 602-entry allowlist.
  * `cyclonedx-extra` — версия sync с [dev-group].
  * `test-collection-errors` — importlib-mode + chaos SCENARIOS + RAGCitation;
    28 errors → 0 (3382 → 3639 tests collected).
  * `waf-allowlist-tighten` — 6 baseline migrated to ``make_http_client``;
    allowlist пуст.
* Phase 2 (2 K1): RAG PII redaction + Lakera/Rebuff per-tenant guardrails.
* Phase 3 (1 K2): DistributedRedisRateLimiter (Lua token-bucket).
* Phase 4 (8 K4): BLIP2/Whisper + multimodal pipeline + adaptive strategy +
  LangGraph checkpoint UI + DSPy feedback nightly + Model Registry composite +
  Route optimization + Embedding A/B migration.
* Phase 5 (3 K5): dashboard pages 81/82 + DB replica Grafana JSON.
* Phase 6 (1): finale closure (CONTEXT + KNOWN_ISSUES + vault summary).

**Тесты**: 84 новых unit-теста, all passing.

---

## Sprint 11 carryover → Sprint 12

- **Полная Protocol extraction 29 layer-violations** — сейчас в
  acknowledged baseline `tools/check_layers_allowlist.txt`. Закрытие
  через перенос composition-root в infrastructure/ + DI binding в
  svcs_registry. Owner: Foundation Hardening (S12).
- **manage.py CLI wiring** для `ai-route-optimize`/`ai-embedding-migrate` —
  backend готов (services/ai/optimization/, services/ai/embeddings/),
  CLI обёртки делаются в S12 K3.
- **Реальные ML perf-bench** на GPU-runner (BLIP2/Whisper/DSPy) — отдельный
  ``@pytest.mark.slow`` гейт; в S11 модели mock через MagicMock.
- **APScheduler cron registration в lifespan** — `feedback_cron.register`
  готов; integration в `plugins/composition/lifecycle.py` зарезервирована
  на S12 при включении `dspy_feedback_loop=True`.

---

## S14 carryover — 2026-05-20 (cleanup A/B/C/D consolidation)

**Закрыто в S14 cleanup wave**:
- ✅ **F-1 importlib hack** — `tools/*` теперь в `setuptools.packages.find::include`,
  versioning.py и admin_plugins.py используют нативный импорт (`cleanup-a`).
- ✅ **F-3 ручной `to_dict()`** — заменён на `dataclasses.asdict()` в
  InstalledVersion / RollbackResult / CapabilityAuditEvent (`cleanup-b`).
- ✅ **F-4 `_MIGRATION_DIFFER_CLS` global** — удалён вместе с
  `_load_migration_differ()` (`cleanup-a`).
- ✅ **T-1..T-4 покрытие** — 3 новых файла тестов + расширение
  `test_admin_plugins_versioning.py` (real dependency-graph + scaffold
  via patched codegen).

**Переносится в Sprint 15**:

- ⏳ **F-2 Sandbox overhead 137%** (target < 5%, DoD §S14.5).
  `tests/perf/test_plugin_sandbox_overhead.py` показывает ~187 µs против
  ~79 µs baseline. Root cause: `_with_resource_limits` снимает 2 psutil
  snapshots на каждый `PluginSandboxAdapter.run`. Варианты для S15:
  amortised snapshot раз в N вызовов / fire-and-forget task / переезд
  enforcement в e2b runtime / снять числовое требование DoD для
  dev-окружения. Функционально sandbox работает.

- ⏳ **F-5 `gen_dsl_stubs._resolve_annotation` fallback**.
  Использует `str(annotation)` вместо `typing.get_type_hints` /
  `get_origin` / `get_args`. Stub-генерация работает (215 .pyi
  сигнатур), но качество IDE-autocomplete ограничено для PEP-695
  type-parameters и `TypeAlias`. Точечное улучшение — отдельная задача
  S15 K3 «pyi fidelity».

- ⏳ **F-6 `sys._current_frames()` приватный API** в
  `infrastructure/observability/plugin_resource_monitor._collect_cpu_share`.
  Работает в CPython 3.14, best-effort attribution. На PyPy / Jython
  возвращает `{}` (graceful fallback). Не блокер.

---

## Sprint 8 closure status — 2026-05-18 (coordinator-self consolidation)

**Закрыто в S8 closure**:
- ✅ **BLOCKER #3 WAF Phase-2** — 0 violations (см. ниже)
- ✅ **K2 W3 DLQ unified scaffold** — DLQEnvelope + DLQWriter Protocol (`ffd84769`)
- ✅ **K2 W4 Inbox fail-closed** — fail_mode policy + 7 unit-tests (`02587c14`)
- ✅ **K3 W12 MCP FastMCP** — уже на FastMCP (12 unit-tests passing); DoD verified
- ✅ **Sprint 8 artifacts consolidation** — 98 файлов через `[wave:s8/cleanup]` (`6f850f6c`)

**Carryover в Sprint 9 (untracked wave-DoD не закрыт)**:
- ⏳ **AugmentResult** отсутствует в `services/ai/rag_service.py` → S9 K4
- ⏳ **WebhookSignVerifyProcessor** отсутствует в `dsl/engine/processors/enrichment.py` → S9 K3
- ⏳ **PluginCodegen** class отсутствует в `tools/codegen_plugin.py` → S9 K5
- ⏳ **service.py/service/ shadowing** в `src/backend/dsl/` (pre-existing) → S9 K3
- ⏳ **K2 W3 DLQ full integration** (4 транспорта) → S9 K2
- ⏳ **K1 WAF allowlist tightening** (~13 baseline callsites) → S9 K1
- ⏳ **AUDIT-2 plugin hot-swap docs-drift** → S9 K3
- ⏳ Sprint 8 wave-матрица в PLAN.md V19.1: 10+ wave переносятся в S9

---

## Audit findings 2026-05-15 (Sprint 6/7 closure verification)

> Источник: Explore-агент 2026-05-15 + coordinator audit. Сравнение ✅-помеченных
> задач в `PLAN.md` (Sprint 6 ≈ 95%, Sprint 7 ≈ 92%) с фактической файловой
> системой. **Подтверждено**: SAML/AD, supply-chain SBOM+cosign+pip-audit, OWASP
> ZAP, codeclone, k6+locust, schemathesis, banking processors (12 тестов), DSL
> Linter + LSP, Inspect AI nightly, DSPy critical pipelines, chaos×33, outbox
> stub, layer-violations facade, msgspec hotpath benchmark, structlog batching
> (`infrastructure/observability/structlog_batching.py`), plugin hot-swap
> (`core/plugin_runtime/hot_swap.py` 279 LOC + graceful shutdown + state
> migration через PluginLoader).

### ❌ AUDIT-1 — Quotas tests fail (Sprint 7 K1)

- **Owner**: K1 Security
- **ETA**: Sprint 8 K1 W0 (`[wave:s8/k1-w0-quotas-tests-fix]`)
- **Risk**: low (тесты, не runtime)
- **Файлы**: `tests/unit/core/auth/test_quotas.py`,
  `tests/unit/services/billing/test_quotas_service.py`

**Описание**: 5 unit-тестов quotas падают после S7 K1 `4f6e9dab`
(per-tenant billing/quotas service + ASGI middleware). Регрессия не блокирует
runtime, но `make ci` warn-out до фикса.

**DoD checklist**:
- [ ] `pytest tests/unit/core/auth/test_quotas.py tests/unit/services/billing/test_quotas_service.py` → 5/5 passed
- [ ] Проверить, что баг в test-фикстурах или в impl
- [ ] Обновить `feature_flags.per_tenant_quotas` если требуется

---

### ⚠️ AUDIT-2 — Plugin hot-swap путь в PLAN.md ≠ реальный

- **Owner**: K3 DSL+Workflow (PluginRuntime owner)
- **Severity**: docs-drift, не runtime-баг
- **Действие**: при следующем PLAN.md edit поправить ссылку.

**Описание**: PLAN.md / координационные планы ссылаются на
`src/backend/services/plugins/hotswap*` (которого нет). Реальная реализация
живёт в `src/backend/core/plugin_runtime/hot_swap.py` (279 LOC: `hot_swap()`
async, `HotSwapResult`, `PluginLoaderProtocol`, graceful shutdown через
`loader.shutdown_all()`). CLI `manage.py plugin hot-swap` использует именно этот
модуль. **Расхождение только в путях документации**, функционал закрыт.

---

### ⚠️ AUDIT-3 — windows-sidecar layout ≠ PLAN.md V17 `windows_worker/`

- **Owner**: K3 DSL+Workflow
- **ETA**: Sprint 8 K3 W1 (`[wave:s8/k3-w1-windows-worker-rename]`)
- **Risk**: low (RPA stage 1 не начат, рефакторинг до scaling-up)
- **Текущий layout**: `windows-sidecar/{app.py, com_router.py, Dockerfile.windows}`
- **Целевой layout V17**: `windows_worker/{main.py, handlers/com_handler.py, handlers/desktop_rpa_handler.py, Dockerfile.windows}`

**Описание**:
- Имя `windows-sidecar` использует kebab-case, PEP 8 и V17 требуют snake_case
  `windows_worker/`.
- `app.py` → `main.py` (V17 alignment с остальными top-level Python entry).
- `com_router.py` (137 LOC) разделить на `handlers/com_handler.py`
  (текущее содержимое) + scaffold `handlers/desktop_rpa_handler.py` под
  Sprint 8 K3 W4 pywinauto.
- `docker-compose.windows-worker.yml` сейчас **untracked** в git — закоммитить
  вместе с rename.

**Вердикт «правильно вынесено наружу»** — оставить top-level (НЕ переносить в
`src/`):
- Отдельный процесс (REST API на Windows-контейнере), не Python import.
- Windows-only runtime (Granian RSGI не работает на Windows нативно).
- Windows-only deps (`pywin32`, `comtypes`, `pywinauto`) загрязнили бы основной
  `src/` `[project.dependencies]` platform markers.
- PLAN.md V17 строка 732 явно фиксирует top-level.

**DoD checklist**:
- [ ] `git mv windows-sidecar windows_worker`
- [ ] `git mv windows_worker/app.py windows_worker/main.py`
- [ ] split `com_router.py` → `handlers/com_handler.py` + `handlers/desktop_rpa_handler.py`
- [ ] Обновить `Dockerfile.windows` (CMD/ENTRYPOINT → `main.py`)
- [ ] `git add docker-compose.windows-worker.yml`
- [ ] Обновить `pyproject.toml::[project.optional-dependencies] com-windows / rpa-windows` если требуется
- [ ] `make wave-memory NAME=windows-worker-rename TYPE=feedback`

---

## Sprint 5 carryover (still open) — миграция в Sprint 8A

> Источник: 16 reflog-коммитов Sprint 5 (HEAD `eaad2f6c` до race) +
> `.claude/CONTEXT.md` секция «Sprint 5 — попытка closure». Все wave НЕ
> переписываются полуготовыми reflog-коммитами, а **переделываются чисто** в
> Sprint 8A (см. план S8 К2 W2-W7 + K4 W1-W8 + К1 round 2 + K3 W10-W11).

### К2 (Resilience) — 8 wave перенесены в Sprint 8A K2 W1-W7
- `[wave:s8/k2-w1-taskiq-removal]` — BLOCKER #1 closure (13 callsites).
- `[wave:s8/k2-w2-outbox-dispatcher]` — `infrastructure/messaging/outbox_dispatcher.py`
  поверх Protocol+Fake `core/messaging/outbox.py` (`36ca6757` уже в master).
- `[wave:s8/k2-w3-dlq-unified]` — DLQ unified для HTTP/SOAP/gRPC/Webhook.
- `[wave:s8/k2-w4-inbox-fail-closed]` — `seen_or_mark()` raise `InboxUnavailable`.
- `[wave:s8/k2-w5-alerts-and-fallback-chains]` — 5 alerts + 2 fallback chains.
- `[wave:s8/k2-w6-bulkhead-defaults]` — Bulkhead defaults в `ResilienceSettings`.
- `[wave:s8/k2-w7-tenant-rate-limit-namespace]` — per-tenant namespace.

### К1 (Security) — Round 2 перенесён в Sprint 8A K1 W1-W3
- `[wave:s8/k1-w1-waf-phase2]` — BLOCKER #3 closure (38 callsites + flip).
- `[wave:s8/k1-w2-dlq-replay-rbac]` — admin-only RBAC + audit-event на replay.
- `[wave:s8/k1-w3-inbox-audit-pii]` — Inbox dedup audit с PII-mask.

### К3 (DSL/Workflow) — W13-W14 перенесены в Sprint 8A K3 W10-W11
- `[wave:s8/k3-w10-workflow-taskgroup]` — `asyncio.TaskGroup` migration.
- `[wave:s8/k3-w11-invoke-workflow-reply]` — sync через Temporal signal.

### К4 (AI/RAG) — 9 wave перенесены в Sprint 8A K4 W1-W8
- `[wave:s8/k4-w1-multimodal-rag]` — docling + PaddleOCR/EasyOCR + `.rag_ingest(modal=...)`.
- `[wave:s8/k4-w2-rlm-hierarchical-memory]` — MemGPT-style hierarchical memory toolkit.
- `[wave:s8/k4-w3-rag-cache-invalidation]` — 3-уровневый cache invalidation через Redis pub/sub.
- `[wave:s8/k4-w4-bge-m3-reranker]` — BGE-M3 + bge-reranker-v2.5 EmbeddingProvider.
- `[wave:s8/k4-w5-rag-streamlit-pages-7]` — 7 RAG Streamlit pages (см. Sprint 8B K4 W5).
- `[wave:s8/k4-w6-mem0-rag-memory-dsl]` — `mem0ai>=0.1.0` + `.rag_*/.memory_*` DSL.
- `[wave:s8/k4-w7-saga-blueprint]` — `saga_with_compensation` Blueprint R2.
- `[wave:s8/k4-w8-litellm-final]` — LiteLLM gateway financial (cost-budget + retry + fallback).
- `[wave:s8/k1-w4-pii-dsl-step]` — `.mask_pii/.unmask_pii` DSL (формально К1 owner, но scope К4).

### Sprint 7 К1 carryover (stash-accident potery) → Sprint 8A K1 W5-W6
- `[wave:s8/k1-w5-supply-chain-cosign-all]` — multi-artifact cosign (plugin TOML).
- `[wave:s8/k1-w6-openfeature-flagsmith]` — OpenFeature → Flagsmith default-ON staging.

### Sprint 7 К5 carryover → Sprint 8A K5 W2-W4
- `[wave:s8/k5-w2-streamlit-tenants]` — `70_Tenants.py`.
- `[wave:s8/k5-w3-streamlit-capabilities]` — `71_Capabilities.py`.
- `[wave:s8/k5-w4-streamlit-files-s3]` — `30_Files_S3.py`.

### Sprint 7 К2 carryover → Sprint 8B K2 W8-W9
- `[wave:s8/k2-w8-httpx-unify]` — `httpx + httpx-retries + httpx-cache (hishel)`
  (адаптер `httpx_cache_adapter.py` уже в working tree).
- `[wave:s8/k2-w9-grafana-and-slo-alerts]` — 7 Grafana dashboards финал + 3 SLO-burn alerts.

### Sprint 7 К3 carryover → Sprint 8A K3 W8-W9 + W13
- `[wave:s8/k3-w8-dsl-blueprints-subdir]` — `dsl/macros.py`/`dsl/blueprints.py` → `dsl/blueprints/` package.
- `[wave:s8/k3-w9-workflow-versioning]` — Temporal `patched` API + per-workflow semver.
- `[wave:s8/k3-w13-plugin-hotswap-impl]` — расширение `core/plugin_runtime/hot_swap.py`
  (если по итогам S8 K3 ревизии потребуется доделать state migration / version-conflict).

### Sprint 5 К4 carryover (MCP)
- `[wave:s8/k3-w12-mcp-via-fastmcp]` — FastMCP auto-export Tier 1+2 actions
  (code-зона DSL/MCP — К3 owner, AI-payload — К4).

---

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

### ✅ BLOCKER #3 — WAF Phase-2 migration — CLOSED 2026-05-18

- **Owner**: K1 Security
- **Closed**: Sprint 8 K1 W1 `[wave:s8/k1-w1-waf-phase2-finale]` (`058705ed`)
- **Final coverage**: `tools/check_waf_coverage.py` → 0 violations
- **Feature-flag**: `feature_flags.waf_outbound_via_facade` (default-OFF)

**Реализовано (S8 closure)**:
- ✅ 3 callsites вне allowlist мигрированы на `make_http_client()`:
  - `core/feature_flags/flagsmith_client.py:_get_client`
  - `core/feature_flags/flagsmith_provider.py:_get_or_create_client`
  - `services/rpa/desktop_rpa_client.py:invoke`
- ✅ `tools/check_waf_coverage.py` exit 0
- ✅ Default-OFF поведение сохранено (нулевой риск регрессии)

**Carryover → Sprint 9 K1**:
- ⏳ Tightening allowlist: миграция ~13 baseline-callsites
  (express_bot, telegram_bot, opa, clickhouse, vault_cipher, ml_inference,
   proxy/forward, imports endpoint, webhook handler/transformer,
   search_providers).
- ⏳ Flip `feature_flags.waf_outbound_via_facade` → default-ON после
  staging-smoke (`vault/2026-XX-waf-phase2-rollout.md`).
- ⏳ ADR-0053 Proposed → Accepted.

---

### ✅ BLOCKER #4 — Supply-chain (SBOM + cosign + ZAP) — CLOSED 2026-05-14

- **Owner**: K1 Security
- **Wave**: `[wave:s3/k1-w3-supply-chain-ci]` `c8c8a5a` + `[wave:s3/k1-w5-plugin-semver]` `a3df2a6`
- **Закрыто**: Sprint 3 K1 W3 + W5
- **Feature-flag**: `feature_flag.supply_chain_ci_gate` (CI-only) + `feature_flag.plugin_semver_strict`

**Реализовано**:
- ✅ `tools/checks/generate_sbom.py` — CycloneDX JSON + XML generator
- ✅ `tools/checks/run_pip_audit.py` — pip-audit JSON-output обёртка
- ✅ `tools/checks/cosign_sign.py` — cosign artifact signing
- ✅ `tools/checks/check_plugin_semver.py` — plugin manifest semver validator
- ✅ Makefile.security: `sbom` / `audit-deps` / `cosign-sign` / `check-plugin-semver`
- ✅ `pyproject.toml::[security]` extras: cyclonedx-bom + pip-audit
- ✅ 5+4 unit-тестов

**Открытая часть**: подключение к `.github/workflows/release.yml` + OWASP ZAP `.github/workflows/security.yml` —
запланировано как Sprint 4 К1 W1 (отдельный wave-tag).

---

### 🟢 PLAN #5 — Search-DSL extension (SearXNG + Exa + cleanup current)

- **Owner**: K6 AI/RAG (lead) + K7 EventBus (provider integration)
- **ETA**: Sprint 3 / Sprint 4 (M-size, 3-5 дней)
- **Wave-tag**: `[wave:s3/k6-w4-search-providers]` (lead) + `[wave:s3/k6-w4-search-cleanup]`
- **Risk**: low (new feature behind feature-flag, parallel к existing)

**Контекст**: Internal audit (2026-05-13) выявил пробелы в текущей search-архитектуре:
- Tavily без `Settings`-класса — `tavily_api_key` через `getattr` без валидации
- `PerplexityProvider` дублируется: `infrastructure/clients/external/search_providers.py` + `services/ai/ai_agent.py`
- DSL actions дублируются: `ai.search_web` (Perplexity-only) vs `web_search.query` (с fallback)
- DuckDuckGo не реализован (только MCP в Claude Code, не в коде проекта)
- Нет тестов на `search_providers.py`

External research (2026-05-13) подтвердил:
- ❌ Brave Search free tier удалён фев-2026 (платный $5/mo)
- ❌ Bing Web Search API retired авг-2025
- ❌ Glean / Kagi / Mojeek — enterprise/paid only
- ✅ **SearXNG** (self-hosted, unlimited, privacy-first) — production-ready для банковской среды
- ✅ **Exa AI** (1000 req/mo free, neural semantic) — production-ready для RAG grounding
- 🟡 **OpenAlex** (academic, free key) — spike-worthy для compliance RAG
- 🟡 **Firecrawl** (1000 pages/mo, Markdown) — spike-worthy для data ingestion

Полный отчёт: `vault/research-2026-05-13-search-engines.md`.

**Scope (DoD checklist)**:

*Cleanup waves (Sprint 3 Wave 1)*:
- [ ] `TavilySettings` класс в `core/config/ai.py` + Pydantic-валидация api_key
- [ ] Дедупликация `PerplexityProvider` — единый класс в `search_providers.py`, `ai_agent.py` использует его
- [ ] DSL action consolidation: `web_search.query` единый, `ai.search_web` deprecated alias
- [ ] Unit-тесты для `search_providers.py` (4-6 тестов: mock httpx)

*New providers (Sprint 3 Wave 2)*:
- [ ] `SearXNGProvider` (BaseSearchProvider subclass) — async via httpx + `?format=json`
- [ ] `SearXNGSettings` (base_url, engines list, default-OFF feature-flag)
- [ ] `ExaProvider` через `exa-py` — neural mode + content extraction
- [ ] `ExaSettings` (api_key, mode, default-OFF feature-flag)
- [ ] WAF capability для Exa: `net.outbound.exa.ai:external`
- [ ] DSL step extension в `dsl/engine/processors/ai.py`: `search:` с `provider: searxng|exa|perplexity|tavily`
- [ ] 2 reference routes с новыми providers
- [ ] 6-8 unit-тестов (mock httpx, mock exa-py)

*Optional spike (Sprint 4)*:
- [ ] `OpenAlexProvider` (academic RAG)
- [ ] `FirecrawlProvider` (Markdown extraction)

**Feature-flags** для регистрации:
- `search_provider_searxng` (default-OFF)
- `search_provider_exa` (default-OFF)
- `search_provider_openalex` (default-OFF, Sprint 4)
- `search_provider_firecrawl` (default-OFF, Sprint 4)

**Coordination**: K6 — provider implementations + DSL step, K7 — capability registration для WAF, K2 — `OutboundHttpClient` для `:external` (Exa, OpenAlex), K10 — feature-flag реестр.

**Сильные стороны**: SearXNG closes air-gap/privacy concern для банка; Exa Neural идеален для RAG; cleanup убирает дублирование Perplexity + закрывает test gap.

---

### Sprint 2 (V15.3 MVP) — РЕЗУЛЬТАТЫ kickoff (2026-05-13)

**Закрыто** (14 wave-коммитов, 46 unit-тестов green, 22 feature-flag default-OFF):

| Owner | Wave-tag | Commit | Описание |
|---|---|---|---|
| К10 | `s2/k10-backbone` | `371eace` | 10-team ownership + 22 feature-flag + 3 blockers |
| К10 | `s2/k10-w2-py2-syntax` | `461a6ce` | 20 Python-2 except callsites hotfix |
| К10 | `s2/k10-w1-testkit` | `8af96c1` | testkit/pytest_plugin.py entry-point |
| К10 | `s2/k10-features-extend` | `07512b4` | +3 feature-flag (task_watchdog/pool_health/file_watcher) |
| К1 | `s2/k1-w1-joserfc` | `af0c4f5` | joserfc parallel shim + 14 тестов |
| К2 (K3) | `s2/k3-w1-otel-tenacity` | `42ed620` | OTel asyncpg + tenacity unification |
| К2 (K3) | `s2/k3-w2-watchdog-deadline` | `d9beed9` + `5549127` | TaskWatchdog + AIWorkspaceCleaner + fix |
| К2 (K3) | `s2/k3-w4-perf-gate-ci` | `26aa05a` | perf-gate Makefile + CI workflow + baseline |
| К2 (K8) | `s2/k8-w5-pool-health` | `2aa4544` | ConnectionPoolHealthMonitor scaffold |
| К3 (K5) | `s2/k5-w3-processor-registry` | `f2f5b14` | @processor + JSON-Schema export (17 тестов) |
| К3 (K5) | `s2/k5-w5-routes-v11-refs` | `dc33a03` | 2 reference routes по ADR-0056 (4 тестов) |
| К3 (K7) | `s2/k7-w4-file-watcher` | `dacd89c` | FileWatcherSource через watchfiles.awatch |
| К4 (K6) | `s2/k6-w1-langfuse-v3` | `ca5429d` | LangFuse 3.x parallel shim (4 тестов) |

**НЕ закрыто (перенесено в Sprint 3)**:
- SBOM/cosign/ZAP supply-chain → BLOCKER #4 (выше)
- WAF Phase-2 38 callsites → BLOCKER #3 (выше)
- TaskIQ removal → BLOCKER #1 (выше)
- Workflow legacy purge → BLOCKER #2 (выше)

**Memory**: `~/.claude/projects/.../memory/feedback_s2_multi_agent_kickoff.md`.

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

---

## Deferred реестр Sprint 1–9 (2026-05-14, координатор-2)

> Wave: `[wave:s2-s9/known-issues-deferred-2026-05-14]`. Параллельная
> команда S4 закрывает Workflow DSL + BPMN + Temporal + WAF Phase-2.
> Координатор-2 закрыл ТОП-7 техдолга (см. ниже), остальное оформлено
> здесь как обоснованный deferred с привязкой к будущим Sprint'ам.

### A-фаза 2026-05-14: ЗАКРЫТО

| Wave | Файл / отчёт | Статус |
|---|---|---|
| `[wave:s1/k2-1-cache-decorator]` | `core/resilience/cache_decorators.py` (ADR-0051, in-house вместо aiocache) | ✅ pre-existing, проверено 11 тестов |
| `[wave:s1/k2-2-policy-decorator]` | `core/resilience/decorators.py` (ADR-0052, канонический порядок) | ✅ pre-existing, проверено 7 тестов |
| `[wave:s5/doc-generation-dsl]` | `dsl/engine/processors/documents.py` + `.render_docx`/`.render_xlsx` через python-docx + openpyxl (уже в deps) | ✅ 4 теста |
| `[wave:s6/msgspec-benchmark]` | `tests/perf/test_msgspec_benchmark.py` + `vault/benchmark-2026-05-14-msgspec.md` (msgspec в среднем ×5.5 быстрее) | ✅ |
| `[wave:s6/layer-violations-facade]` | `services/dsl_portal/` фасад; 2 frontend-pages переписаны; 6 baseline-violations закрыты | ✅ |
| `[wave:s8/rule-engine-scaffold]` | `dsl/engine/processors/rule_engine.py` + `.evaluate_rules()` через SimpleEval | ✅ 3 теста |
| `[wave:s2-s9/known-issues-deferred-2026-05-14]` | этот реестр | ✅ |

### S1 — deferred

* **`[wave:s1/asyncio-taskgroup]` migration DSL-процессоров** → **Sprint 5**.
  Зависит от parallel/streaming-split рефакторинга в
  `dsl/engine/processors/{parallel,streaming}.py` — эта зона активно
  меняется параллельной командой S4 (LLM-activity, Workflow DSL).
  Reason: избежать двойного рефакторинга.

* **`[wave:s1/result-monad]` `result>=0.17.0` + `ResultUnwrapProcessor`**
  → **Sprint 5**. Новый процессор, не критичный для S2-S4 deliverable.
  How to apply: после стабилизации control_flow processors S4 K3.

### S2 — deferred

* **Plugin codegen `make new-plugin NAME=x`** → **Sprint 7 sidekick (Team T5)**.
  Why: T5 уже владеет `core/plugin_runtime/`, hot-swap; codegen логично
  пристёгнуть к этой же миграции.
  How to apply: `tools/codegen/codegen_plugin.py` (уже scaffold существует)
  + Make-цель `new-plugin`.

* **Hot-reload DSL <3 сек graceful drain** → **Sprint 7 sidekick (Team T5)**.
  Why: hot_swap plugin API (Team T5 owns) — естественная база для
  graceful drain DSL-routes. Связано с feature-flag rollouts.

### S3 — deferred

* **Search-DSL final cleanup (Tavily Settings dedup + Perplexity dedup)**
  → **Sprint 7 sidekick (Team T4)**. См. PLAN #5 выше.

### S5 — deferred

* **R2 Blueprints (api_normalize, cdc_enrich, ai_pipeline, saga_with_compensation)**
  → **Sprint 7 (Team T4 захватит api_normalize в reference) + Sprint 8**
  (остальные). Зависит от R2 Sprint 5 blueprints API.
  Why: первый blueprint — pilot, остальные — после feedback.

* **CDC PostgreSQL logical replication** → **Sprint 8**. Большой scope,
  blocking — нет, отложить до RPA-волны.

* **DSL web-search expansion** → **Sprint 7 sidekick (Team T4)**.
  Cleanup из S3 deferred покрывает первый шаг.

* **Async Queue migration / DLQ unified / Dry-run** → **зависят от S4 Temporal**.
  Why: TaskIQ removal (BLOCKER #1 Sprint 2) и Temporal facade —
  предпосылка. Ожидать завершения S4 K1-K5.

### S6 — deferred

* **k6+locust perf-suite + p95<200ms gate** → **Sprint 8**.
  Why: нужен стабильный staging с auto-scaler K2 (Sprint 4 ✅) и
  k8s HPA exporter (S3 K2 W4 ✅). Запуск на готовой инфре.

* **COM-sidecar Windows RPA** → **Sprint 8**. Вместе с RPA-волной;
  Windows-only компонент.

* **Schemathesis CI gate** → **Sprint 8**. После стабилизации OpenAPI
  схем (S4 закрывает workflow endpoints — ждать).

* **Codeclone gate strict** → **Sprint 8**. Pre-prod check, не блокирует
  S2-S7 deliverable.

### S8 — deferred

* **patchright RPA (browser + Windows)** → **Sprint 8**. Тяжёлые
  зависимости (playwright + Windows-specific), отдельная волна.

* **HTTP/3 opt-in** → **Sprint 9**. Сетевая оптимизация —
  после стабилизации S4-S8 deliverable.

* **mypy ≤ 50 + deptry/vulture green** → **Sprint 9 financial cleanup**.

### S9 — deferred

* **≥9 tutorials + ≥10 runbooks** → **Sprint 9 docs wave**.
  Why: больше смысла писать после стабилизации features Sprint 7-8.

* **Visual Editor BPMN export** → **Sprint 9**.
  Why: S4 BPMN import — это первый шаг (`bpmn_importer.py` в WIP).
  Export — после.

* **Pre-prod-check gate (20 critia)** → **Sprint 9 final wave**.

---

## Sprint 7 запуск (2026-05-14)

5 worktree-команд параллельно по PLAN.md §4 Sprint 7. Каждая команда
работает в изолированном worktree через Agent с `isolation: "worktree"`.

| Team | Branch | Скоуп |
|---|---|---|
| T1 | `team/01-s7-core-entities-uo` | Migrate users + orders → `extensions/core_entities/` |
| T2 | `team/02-s7-core-entities-of-credit-scaffold` | Migrate orderkinds + files + scaffold `extensions/credit_pipeline/` |
| T3 | `team/03-s7-credit-1st-client` | 1st credit client + workflow YAML + feature_flag.credit_pipeline_v2 (blockedBy: T2) |
| T4 | `team/04-s7-admin-frontend` | sqladmin + 3 Streamlit pages + R2 Blueprint api_normalize |
| T5 | `team/05-s7-plugin-runtime-flags` | plugin hot-swap + blue/green + OpenFeature + make new-plugin |

**S4-охраняемые файлы** (не трогать):
`dsl/workflow/**`, `infrastructure/workflow/**`, `infrastructure/temporal/**`,
`services/workflows/**`, `core/workflow/**`, `services/ai/**`, `core/auth/**`,
`core/net/**`, `dsl/engine/processors/ai*.py`,
`plugins/composition/lifecycle.py`, `tools/checks/check_waf_coverage.py`.

---

## Sprint 6 запуск (2026-05-14, координатор-3)

5 worktree-команд параллельно по PLAN.md §6 (`Sprint 6 — Performance + Chaos +
Coverage + Security + OLE/COM + Observability`). Запуск **параллельно** с
текущим Sprint 5 (доделывается параллельной командой) и Sprint 7 (T1-T5
worktree миграция). Каждая команда работает в изолированном worktree через
Agent с `isolation: "worktree"`, делает intermediate commits после каждой
завершённой задачи. Pipeline-mode: координатор делает ff-merge / cherry-pick
в master без блокирующего подтверждения.

**Полный план**: `~/.claude/plans/effervescent-herding-fairy.md`.

| Team | Branch | Скоуп |
|---|---|---|
| K1 | `team/s6-k1-security` | SAML+AD финал, supply-chain полный CI gate, OWASP ZAP, custom-code-audit, codeclone strict, per-host metering финал (6 wave) |
| K2 | `team/s6-k2-resilience-perf` | k6+locust perf-suite, Granian RSGI ADR, DB pool tuning, structlog batching, processor-specific health, backpressure, schemathesis, service-doc gate (8 wave) |
| K3 | `team/s6-k3-dsl-workflow` | e2e один action × 6 протоколов, coverage gate ≥70%, banking-processors тесты (12), DSL Linter CLI + LSP, COM Windows sidecar (5 wave) |
| K4 | `team/s6-k4-ai-quality` | Inspect AI nightly eval, DSPy для critical pipelines, AI cost dashboard финал (3 wave) |
| K5 | `team/s6-k5-frontend-chaos` | 33 chaos-теста (11 chains × 3 сценария), DLQ-replay UI, Resilience Dashboard, Pool Monitor, 5 Grafana dashboards (5 wave) |

**Backbone-commit** перед запуском агентов (выполнен координатором):
- `src/backend/core/config/features.py` — 21 новый default-OFF feature-flag (S6 K1-K5)
- `.claude/team-ownership.toml` — раздел `[team_s6.k1]`..`[team_s6.k5]` с `owned_paths` + `forbidden_paths`
- `.claude/KNOWN_ISSUES.md` — этот раздел
- Wave-тег: `[wave:s6/backbone]`

**Уже досрочно закрытые задачи Sprint 6** (A-фаза 2026-05-14):
- ✅ `[wave:s6/msgspec-benchmark]` (`3743c574`)
- ✅ `[wave:s6/layer-violations-facade]` (`6b818829`)

**S5→S6 stub-контракты** (Protocol+Fake в `core/`, реальная impl в `infrastructure/` от S5 K2):
- `OutboxBackend` (`core/messaging/outbox.py`) — для K5 DLQ-replay UI и K2 perf-gate
- `AsyncQueueBackend` (`core/orchestration/async_queue.py`) — для K2 perf-gate
- `RetryEngine` (`core/resilience/retry.py`) — для K2 если Tenacity ещё не unified

Каждый stub имеет соответствующий `FakeXxx` для тестов; DI переключает на
реальную имплементацию через feature-flag когда S5 K2 закоммитит её в master.

**S4-охраняемые файлы + S7-захваченные пути** — см. `forbidden_paths` в
`.claude/team-ownership.toml::[team_s6.kN]`. Ключевые ограничения:
- `dsl/workflow/**`, `infrastructure/workflow/**`, `infrastructure/temporal/**` — S4 closed но активная пост-завершительная подчистка K3/K4
- `services/ai/agents*/`, `services/ai/gateway/` — S5 K4 owns
- `infrastructure/messaging/outbox_dispatcher.py` — S5 K2 owns
- `extensions/**`, `plugins/composition/**` — S7 T1-T5 owns
- `pages/{30_Files_S3,50_Workflow_Logs,80_Admin_Models}.py` — S7 T4 owns

**DoD Sprint 6** (по PLAN.md:623):
- [ ] p95<200ms / RPS>1000 — baseline зафиксирован, gate warn-only
- [ ] 33 chaos-теста зелёные (локально blocking, CI warn-only)
- [ ] coverage ≥70% (BLOCKING)
- [ ] SAML+AD логин
- [ ] SBOM в каждом релизе
- [ ] OWASP ZAP gate зелёный (warn-only)
- [ ] codeclone gate `--fail-on-new-clones`
- [ ] COM-sidecar тест на Windows (или mock)
- [ ] CI docs-gate зелёный
- [ ] schemathesis в CI (warn-only)
- [x] msgspec hotpath benchmark задокументирован (`vault/benchmark-2026-05-14-msgspec.md`)
- [x] layer-violations через `services/dsl_portal/` фасад → 0
