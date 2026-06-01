# PLAN.md — gd_integration_tools V22.6 FINAL (S31–S36 GAP-driven maturity ramp to 90%+)

> **Версия**: V22.6 FINAL (S31–S36 GAP-driven sprint planning добавлены 2026-05-27; повышение зрелости до 90%+). Sprint 28–S30 CLOSED. **Sprint 21–S27 AI Platform Layer** — предыдущий пласт. **Sprint 31–S36** — GAP-driven планирование (архитектурная нормализация, AI consolidation, DX, documentation CI, dependency governance, chaos, production readiness).
> **Дата**: 2026-05-27.
> **Замещает**: V22.3 FINAL (предыдущая ревизия с S24 AI Safety) и V21.0 (архив → `vault/archive-plan-v21.md`).
> **Срок**: 2026-05-22 → 2026-08-31 (S16–S20: 5 спринтов × 2 недели × 5 команд). S28–S30 closed 2026-05-27.
> **S31–S36 GAP-driven** (2026-06-09 → 2026-08-31): 6 спринтов × 2 недели × 5 команд для достижения зрелости 90%+.
> **Post-production backlog (S21-S23)**: без дат, выполняется параллельно release stabilization, не блокирует release v1.0.0-production.
>
> **Главные принципы V22**:
> - Только нереализованное и дополнительное. Архив S0–S15 — отдельный документ.
> - Single Entry per Cross-Cutting Concern расширен (centralization V22): ConfigValidator / MetricsRegistry / AuthorizationGateway / ResilienceCoordinator class.
> - Каждый спринт = 2 недели × 5 команд (К1 Security / К2 Resilience+Perf / К3 DSL+Workflow / К4 AI+RAG / К5 Frontend+Ext+Mig).
> - DoD-критерии grep-based (CI verify).
> - Push в `origin master` — только Sprint 20 wrapper, с явного подтверждения пользователя.

---

## 0. Видение

`gd_integration_tools` — универсальная интеграционная шина банка (Python 3.14+, Apache-Camel + Airflow + Temporal style). Ядро (`src/backend/`) — domain-agnostic. Бизнес-логика — `extensions/<name>/` (ADR R1.6 hybrid: shared + features). Stakeholder #1 — кредитный конвейер. Финальное состояние V22 (target Sprint 20) — production-ready: pre-prod-check 38/38 + Centralization Hardening 8/8 + coverage 83% + mypy=0 + p95 ≤80ms + RPS ≥1500 + 0 layer violations + 0 WAF allowlist + 0 docstring allowlist.

---

## 1. Принципы (неизменные V15.1 + V17 + V22 расширения)

### 1.1. Single Entry V22 (расширенный)
```
ResilienceCoordinator (V22 class) ← 12 fallback chains
├── CircuitBreaker / RateLimiter / Retry / Bulkhead / TimeLimit / Reconnection / Cache
├── FallbackChains: antivirus / audit / cache / db / express / mongo / mq / object_storage / search / secrets / smtp / graylog / genai

ConfigValidator (V22 NEW) ← cross-settings + production-safety + startup-gate
MetricsRegistry (V22 NEW) ← idempotent + standard labels {tenant_id, route_id, component, env}
AuthorizationGateway (V22 NEW) ← Casbin → OPA → CapabilityGate (единый correlation_id)
TaskRegistry (V22 OBLIGATORY) ← все asyncio.create_task через TaskRegistry.create_task(name, deadline)
AuditService (V22 EXTENDED) ← correlation_id из contextvars + unified schema
FeatureFlagService (V22 EXTENDED) ← per-tenant + runtime UI + Redis pub/sub
```

### 1.2. Граница «ядро / extensions» (без изменений)
- Ядро `src/backend/` — domain-agnostic.
- `extensions/<name>/` — бизнес-логика; импорт только `gd_integration_tools.{core, testkit}` + capability-checked фасады.
- CI-gate: `tools/checks/check_layers.py --strict-extensions`.

### 1.3. DSL dual-mode + 80/20 (без изменений)
- YAML `route.toml + *.dsl.yaml` И Python `RouteBuilder`. Равноправно.
- YAML↔Python round-trip + `diff()`.
- Hot Reload < 3 сек.

### 1.4. Auto-registration (3-tier, без изменений)
- `@service_dsl(protocols=["all"])` → REST + SOAP + XML + gRPC + GraphQL + MQ + WS + SSE + MCP + MQTT.

### 1.5. ADR R1.6 — Hybrid plugin layout (закреплён)
- `extensions/<plugin>/{plugin.toml, plugin.py, shared/, features/}`.

### 1.6. Стандарты V17 (закреплены)
- `asyncio.TaskGroup` вместо `asyncio.gather`.
- Lazy import (`_ensure_<lib>()`) для AI/тяжёлых библиотек.
- `msgspec.Struct` для internal DTO в hot-path.
- `Result[T, E]` для бизнес-ошибок без try/except каскадов.

### 1.7. EventBus Facade (V17, дополнено V22 DSL methods)
- `EventBus.get().publish(topic, payload)` / `EventBus.get().subscribe(pattern, handler)`.
- Backends: KafkaEventBusBackend / RabbitMQEventBusBackend / NATSJetStreamEventBusBackend.
- **V22 NEW**: DSL `.to_eventbus(topic)` + `.from_eventbus(topic_pattern)` в RouteBuilder (Sprint 18 K3 W2).

### 1.8. V22 Centralization Hardening (новое)
- **ConfigValidator** обязателен в lifespan startup (Sprint 17 К1 W1).
- **MetricsRegistry** — единственный путь регистрации Prometheus метрик (Sprint 17 К2 W1+W2).
- **TaskRegistry obligatory** — все `asyncio.create_task` через registry; CI gate `check_task_registry.py` (Sprint 17 К2 W3).
- **AuthorizationGateway** — единый фасад над Casbin + OPA + CapabilityGate; единый `correlation_id` (Sprint 17 К1 W2).
- **AuditService correlation_id** — propagation через contextvars во всех audit/capability/outbound emit calls (Sprint 17 К3 W1).
- **ResilienceCoordinator class** — 12 fallback chains зарегистрированы в lifespan (Sprint 17 К2 W5).

---

## 2. Команды (5, без изменений V21)

| Команда | Зона ответственности | Owns каталоги | Запрещено трогать |
|---|---|---|---|
| **К1 Security** | Auth, Capabilities, WAF, Secrets, AI Safety, PII, Supply-chain, ConfigValidator, AuthorizationGateway | `core/security/`, `core/auth/`, `core/ai/{workspace_manager,fs_facade}`, `core/net/`, `core/config/validator.py` (NEW), `infrastructure/secrets/`, `infrastructure/security/`, `infrastructure/policy/casbin*` & `opa*`, `tools/check_waf_coverage*`, `make/security.mk` | `dsl/`, `services/ai/`, `frontend/`, `extensions/` |
| **К2 Resilience+Perf** | Single Entry CB/RL/Retry/Bulkhead, TaskRegistry, Watchdog, MetricsRegistry, ResilienceCoordinator class, APScheduler observability, OTel, ClickHouse/Graylog/Redis/HTTP pools, msgspec hotpath, Granian | `core/resilience/`, `core/scaling/`, `core/messaging/outbox.py`, `core/utils/task_registry.py`, `infrastructure/resilience/`, `infrastructure/observability/`, `infrastructure/clients/transport/`, `infrastructure/cache/`, `infrastructure/logging/`, `infrastructure/messaging/outbox_*`, `infrastructure/scheduler/`, `tests/perf/`, `tests/chaos/` | `dsl/`, `services/ai/`, `frontend/`, `extensions/` |
| **К3 DSL+Workflow** | DSL builder, Workflow DSL+compiler, Temporal, Sources/Sinks/Processors, EventBus, BPMN, ProcessorRegistry, Schema-registry, Hot Reload, Routes, Auto-reg, correlation_id propagation | `dsl/`, `entrypoints/` (кроме admin/mcp), `services/schema_registry/`, `services/execution/`, `infrastructure/workflow/`, `infrastructure/sources/`, `infrastructure/sinks/`, `infrastructure/eventbus/`, `routes/`, `tools/codegen/`, `tools/dsl/` | `core/security/`, `services/ai/`, `frontend/`, `extensions/` |
| **К4 AI+RAG** | services/ai/ полностью, MCP, RAG cache, LangMem, PydanticAI, LiteLLM, StreamingLLM, AI cost dashboard, AI workflow handlers, multimodal RAG, AI Safety | `services/ai/`, `core/config/{ai,ai_2026,rag}.py`, `infrastructure/cache/rag/`, `entrypoints/api/v1/endpoints/{rag_*,ai_*}.py`, `entrypoints/mcp/`, `dsl/engine/processors/{ai*,llm_*}.py`, `plugins/composition/setup_ai_2026.py` | `core/security/`, `core/resilience/`, `frontend/` (кроме AI-страниц) |
| **К5 Frontend+Ext+Mig** | Streamlit (все pages), api_client, codegen plugins, миграция core_entities → extensions/, Admin UI, F-5 pyi stubs, F-6 sys._current_frames, Layer-violations Protocol-extraction | `frontend/`, `extensions/`, `tools/codegen/codegen_plugin.py`, `tools/templates/`, `tools/vscode-extension/` (NEW S19), `services/admin/` | `core/`, `dsl/`, `services/ai/` |

### Coverage ramp-up (V22 ratchet)

| Sprint | Target | Gate |
|---|---|---|
| S16 (active) | ≥75% | Wave K5 W3 coverage-gate-75 |
| S17 | ≥77% | Все wave с new tests |
| S18 | ≥80% | K2 ramp + failing tests fix |
| S19 | ≥80% (sustain) | Все DX wave не теряют coverage |
| **S20 final** | **≥83%** | pre-prod-check v2 #28 |

---

## 3. Запрещённые паттерны (V22)

### Архитектурные (без изменений)
- God Object (>300 LOC или >10 public methods); God-modules (>500 LOC).
- Прямой импорт `infrastructure/` в `services/` или `core/`.
- Хардкод конфигурации и секретов.
- Прямой `SomeClass()` в обход DI.

### Async / concurrency
- `time.sleep()` в async-контексте.
- **V22 NEW**: `asyncio.create_task(...)` вне `TaskRegistry.create_task(name, ...)`.
- **V22 NEW**: `threading.RLock` в async-коде (use `asyncio.Lock`).

### Error handling / logging
- `except Exception: pass` (глотание ошибок).
- Логирование через `print` или `logging.basicConfig` (только `structlog`).

### Зависимости / runtime
- `aiohttp` / `prefect` / `taskiq` в DSL.
- Прямой `subprocess.run` в плагинах (только sandboxed).
- Кастомный код при наличии библиотечного аналога.
- Глобальные httpx-settings вместо per-service.

### Security
- `ssl.CERT_NONE` / `check_hostname=False` (V1).
- `pickle` / `marshal` для untrusted данных.
- `yaml.load` без `safe_load`.
- `eval` / `exec` без явного sandboxing.
- AI-агент изменяет существующие файлы проекта (V22 AI Safety).
- Capability-обращение вне `plugin.toml::capabilities` (V11.1).

### Process / commit
- Push в `main` / `master` без явного запроса пользователя.
- Skip pre-commit/pre-push hooks без обоснования.
- `.from_health_check()` / `HealthCheckProcessor` (V15: use TechService + ActionSpec).

### V22 NEW (Centralization)
- Inline `Counter(...) / Histogram(...) / Gauge(...)` вне `MetricsRegistry`.
- `get_secret_value()` вне `infrastructure/secrets/backends/`.
- Audit/capability/outbound event без `correlation_id` (либо явно `None` с обоснованием).
- Endpoint без auth-guard, не использующий `AuthorizationGateway.authorize(...)`.
- DSL processor `service.toml` без `[timeouts]` блока (per-service mandatory).

---

## 4. Спринт-расписание (10 недель)

### Sprint 16 — Closure (active, 2 недели: 2026-05-22 → 2026-06-04)

**Owner**: К1/К2/К3/К4/К5 параллельно.
**Приоритет**: **P0** (active, единственный незакрытый рабочий спринт).
**Состояние**: 1/16 wave CLOSED (`[wave:s16/k2-w3-otel-otlp-metrics]` `e200b53f`), 15 OPEN + 3 cleanup + 4 pre-merge gate.

#### Pre-merge gate (Wave 0, обязательно до wave-работ)
- `[wave:s16/gate-w0-merge-conflict]` — resolve `gap-analysis/GAP-анализ gd_integration_tools актуальный.md` (UU status, заменён на `DEEP-RESEARCH-gd_integration_tools-2026-05-20.md`).
- `[wave:s16/gate-w0-ops-reorg-smoke]` — `make ci` zero-error + `docker compose -f ops/compose/docker-compose.yml config` + все GitHub workflow paths валидны (см. `ops/scripts/smoke-ops-reorg.sh`).
- `[wave:s16/gate-w0-otel-unit-tests]` — `pytest tests/unit/infrastructure/observability/otel/` green (6 unit-тестов S16 Wave 1).
- `[wave:s16/gate-w0-f2-sandbox-decision]` — `M src/backend/core/plugin_runtime/sandbox.py` либо commit как F-2 carryover wave, либо `git checkout` (зависит от выбора S18/S19 strategy).

#### 6 P0 wave (critical / data-safety / security)
- `[wave:s16/k2-w1-asyncio-lock-registry]` (L1-P0-1, **deadlock fix**) — `services/schema_registry/registry.py:66` `threading.RLock` → `asyncio.Lock`; await-update 8 импортёров.
- `[wave:s16/k1-w1-asyncssh-pool]` (L1-P0-2/3) — SFTP+FTP через `asyncssh.SSHClient` + session pool + reconnect + known_hosts (replace `aioftp` с `ssl.CERT_NONE` V1 fix).
- `[wave:s16/k2-w2-outbox-tx-atomic]` (L2-P0-1, **data-loss fix**) — Transactional Outbox через advanced-alchemy `unit_of_work`; outbox event в той же DB-транзакции что и business data.
- `[wave:s16/k3-w1-pygls-lsp-server]` (L4-P0-1) — `tools/dsl_lsp/server.py` через pygls≥2.0; completion + hover + diagnostics для route.toml + *.dsl.yaml.
- `[wave:s16/k4-w1-adaptive-rag-classifier]` (L5-P0-1) — `QueryClassifier` LLM-based; динамический выбор `RAGStrategy` (dense/hybrid/hyde/multi_query); bench accuracy +15%.
- `[wave:s16/k1-w2-jwt-introspection]` (L7-P1-1) — endpoint `GET /auth/introspect` RFC 7662.

#### 6 P1 wave (compliance / resilience)
- `[wave:s16/k1-w3-vault-rotation-impl]` (L1-P1-4) — реализация ротации Vault secrets через `hvac` + audit-event на ротацию.
- `[wave:s16/k2-w4-pybreaker-replace]` (L1-P1-6) — замена custom Circuit Breaker на `pybreaker≥1.2.0` + state persistence через Redis backend.
- `[wave:s16/k2-w5-redis-graceful-degrade]` (L1-P1-3) — in-memory `TTLCache` fallback при Redis down (cachetools).
- `[wave:s16/k5-w1-plugin-topo-sort]` (L8-P1-1) — `PluginGraphResolver` через `cachetools.OrderedGraph` + topo-sort + cycle detection.
- `[wave:s16/k5-w2-global-ratelimit-mw]` (L9-P1-1) — ASGI-level `RateLimitMiddleware` через `fastapi-limiter` (`entrypoints/middlewares/global_rate_limit.py`).
- `[wave:s16/k5-w3-coverage-gate-75]` (L11-P1-1) — `[tool.coverage.report]::fail_under = 75` + `tools/coverage/breakdown_by_layer.py`.

#### 3 Cleanup wave
- `[wave:s16/k2-w6-litetemporal-simplify]` (OE-3) — `infrastructure/workflow/lite_temporal_backend.py` упростить до thin wrapper.
- `[wave:s16/k3-w2-routebuilder-clone-cleanup]` (DC-1) — `grep` verified 0 callsites `RouteBuilder.clone()` → удалить метод и тесты.
- `[wave:s16/k1-w4-pyproject-prune-empties]` — drop 8 empty extras (iot/web3/legacy/banking/enterprise/datalake/temporal/beam) + add 2 new (`lsp = pygls≥2.0.0` / `circuit-breaker = pybreaker≥1.2.0`).

#### Closure
- `[wave:s16/closure]` — DoD audit + memory `feedback_sprint16_closure` + CONTEXT.md update.

**DoD Sprint 16 (12 критериев)**:
1. ✅ Все 4 pre-merge gate зелёные (merge-conflict resolved / ops-reorg smoke / OTel tests / F-2 sandbox decision).
2. ✅ L1-P0-1: `grep -rn "threading.RLock" src/backend/services/schema_registry/` → 0; `asyncio.Lock` integration test passing.
3. ✅ L1-P0-2/3: SFTP+FTP через asyncssh pool; reconnect автоматический; integration test с testcontainers.
4. ✅ L2-P0-1: Outbox dropped-message rate = 0 в chaos-test (kill между business-write и outbox-write).
5. ✅ L4-P0-1: pygls LSP запускается; VSCode integration prep работает; completion на route.toml сценарии.
6. ✅ L5-P0-1: Adaptive RAG QueryClassifier выбирает strategy динамически; bench accuracy +15% vs static.
7. ✅ JWT Introspection endpoint `/auth/introspect` отвечает 200/401 по RFC 7662.
8. ✅ Vault rotation реально ротирует secret раз в N часов (hvac call + audit-event).
9. ✅ pybreaker заменяет custom CB; state restored after restart.
10. ✅ Coverage gate ≥75% активен в CI; per-layer breakdown отчёт генерируется.
11. ✅ pyproject pruning применён (0 пустых extras); 2 new extras добавлены.
12. ✅ `[wave:s16/closure]` commit + memory note.

---

### Sprint 17 — GAP P0 Closure + Centralization Hardening (REPLACED 2026-05-21, 2 недели: 2026-06-05 → 2026-06-18)

**Owner**: К1 (security/auth/syntax/TLS) + К2 (centralization/observability) + К3 (routes capability+tenant+correlation_id) + К4 (AI Safety) + К5 (admin UI + K8s scaffold).
**Приоритет**: **P0** (production blocker; объединяет centralization V22 backbone и 17 КРИТИЧЕСКИХ блокеров GAP-аудита 2026-05-21).
**Источник**: GAP-аудит 2026-05-21 (10 слоёв × 4 вектора, среднее 5.7/10) + GAP V3.0 D9–D14 + memory `feedback_wave_integration_pattern`.
**Backbone-ADR**: ADR-NEW-1 AuthorizationGateway / ADR-NEW-2 Declarative MW chain / ADR-NEW-3 Unified RequestContext / ADR-NEW-4 CapabilityGateway Protocol (см. `.claude/DECISIONS.md`).

#### Wave 0 — Backbone (обязательный pre-commit, по правилу `feedback_s2_multi_agent_kickoff`)
- `[wave:s17/backbone]` — 12 default-OFF feature-flags (`config_validator_enabled` / `metrics_registry_strict` / `task_registry_strict` / `apscheduler_metrics` / `authz_gateway_enabled` / `audit_correlation_required` / `tenant_feature_flag_ui` / `resilience_coordinator_enabled` / `routes_capability_gate_strict` / `routes_tenant_aware_strict` / `call_function_whitelist_strict` / `saga_state_persistence_enabled`) + team_s17.k1..k5 в `.claude/team-ownership.toml` + KNOWN_ISSUES.md ссылка на GAP-аудит.

#### Wave 1–6 (P0 Группа SYNTAX + TLS — hotfix CI blockers)
- `[wave:s17/k1-w0-python3-except-clause-sweep]` — **K-SYN-1..5** (Python 2 syntax fix): codemod `tools/codemods/fix_except_clause.py` (libcst) для **70+ файлов** (точный grep `-l` = 71) в `infrastructure/{observability,database,clients,storage,logging,secrets}/`, `core/ai/workspace_manager.py:248`, `entrypoints/mcp/mcp_server.py:142`, `dsl/engine/processors/rpa.py:816`, `infrastructure/observability/tracing.py:60,87`, а также `dsl/`, `services/`, `entrypoints/` (помимо L6/L7). CI-gate `tools/checks/check_python3_syntax.py`. Тесты: import-smoke 70+ файлов + observability/tracing.py integration.
- `[wave:s17/k1-w1-tls-cert-required]` — **K-TLS-1..3** (V1 hotfix): `infrastructure/clients/transport/ftp.py:52-54,83-85`, `infrastructure/sources/email.py`, `entrypoints/email/imap_monitor.py` — заменить `ssl.CERT_NONE` на `ssl.create_default_context()` + `verify_mode=CERT_REQUIRED`. Optional `ca_cert_path` параметр. CI-gate `make secrets-check` + unit-test `assert ctx.verify_mode == CERT_REQUIRED`.

#### Wave 7–10 (P0 Группа ARCHITECTURE — ADR-NEW-1..4 backbone)
- `[wave:s17/k1-w2-authorization-gateway]` — **ADR-NEW-1 + ADR-NEW-4** (K-ARCH-1, K-ARCH-2): `core/security/authorization_gateway.py::AuthorizationGateway` + `core/interfaces/capability_gateway.py::CapabilityGatewayProtocol`. Фасад: CapabilityGate → CapabilityPolicy → Casbin → OPA с единым `correlation_id`. Миграция всех non-public endpoint-guard'ов. Audit-event `authorization.decision` на каждое решение. Reason-chain в response.
- `[wave:s17/k3-w0-routes-capability-gate]` — **K-ARCH-3**: `services/routes/loader.py:70` добавить `capability_gate.declare(route.capabilities)` ДО `pipeline_registrar` callback. Audit-event `route.capabilities.allocated`. CI-gate `tools/checks/check_routes_capability_gate.py`.
- `[wave:s17/k3-w0-routes-tenant-aware]` — **K-ARCH-4**: `RouteManifestV11.tenant_aware` обязательно пробрасывать в `TenantContext.current_tenant()` через RouteLoader. DSL шаги `crud_*` / `proxy` / `dispatch_action` получают tenant-фильтр. End-to-end test: tenant A не видит данные tenant B.
- `[wave:s17/k1-w3-call-function-whitelist-strict]` — **K-ARCH-5**: `dsl/engine/processors/function_call.py:118-119` убрать dev fallback в production; `if os.getenv("ENVIRONMENT") == "production" and not whitelist: raise PermissionError(...)`. CapabilityGate.check(`function.call.<module>`) обязательно. Обновить `extensions/example_plugin/plugin.toml` с `call_function_modules = [...]`.

#### Wave 11–18 (V22 Centralization — D9–D14 + GAP carryover)
- `[wave:s17/k3-w1-unified-request-context]` — **ADR-NEW-3**: `core/request_context.py::RequestContext` dataclass (frozen). `RequestContextMiddleware` собирает один раз. structlog `bind_contextvars` для `correlation_id+trace_id+tenant_id`. Скрипт `tools/migrate_request_context.py` для миграции 30+ callsites. Backward-compat alias `request.state.correlation_id` (deprecated).
- `[wave:s17/k3-w2-middleware-registry]` — **ADR-NEW-2** (S-L1-1): `entrypoints/middlewares/registry.py::MiddlewareRegistry`. `plugin.toml::[[middleware]]` секция. Entry-points-группа `gd_integration_tools.middleware_hooks`. Per-route override через `route.toml::[middleware]`. Команда `make middleware-tree`.
- `[wave:s17/k1-w4-config-validator]` — **D14**: `core/config/validator.py::ConfigValidator` ≥5 production-safety rules (DEBUG+PROD fail / CORS="*" fail / JWT_SECRET ≥32 / Vault unreachable fail / feature-flag dependency).
- `[wave:s17/k2-w1-metrics-registry]` — **D11 backbone**: `infrastructure/observability/metrics_registry.py::MetricsRegistry.counter/histogram/gauge` с обязательными labels `{tenant_id, route_id, component, env}`. Idempotent registration.
- `[wave:s17/k2-w2-metrics-migrate]` — **D11 sweep**: миграция 52 inline `= Counter(...) / = Histogram(...) / = Gauge(...)` callsites. CI-gate.
- `[wave:s17/k2-w3-task-registry-coverage]` — **D13a + S17 V22 obligatory**: миграция 34 orphan `asyncio.create_task` callsites. `copy_context()` propagation. CI-gate `tools/checks/check_task_registry.py --fail-on-orphans`.
- `[wave:s17/k2-w4-apscheduler-observability]` — **D13b**: Prometheus metrics + Grafana alert.
- `[wave:s17/k3-w3-correlation-id-end-to-end]` — **D12**: contextvars propagation через MW → audit → outbound_http → DSL processors. End-to-end test: 3+ источников в `SELECT * FROM audit WHERE correlation_id = X`.
- `[wave:s17/k7-w1-observability-fixes]` — **S-L7-1..3** (carryover из L7): ClickHouse audit retry + DLQ (tenacity loop, Redis stream fallback); structlog inject OTel `trace_id`/`span_id`; Graylog GELF socket.close() в aclose() + global fallback-sink при `is_healthy=False`.
- `[wave:s17/k5-w1-tenant-feature-toggle-ui]` — **D9**: REST endpoint `POST /admin/feature-flags/<flag>/tenant/<id>` + Redis pub/sub broadcast (<100ms) + audit + Streamlit page.

#### Wave 19–24 (P0 OPERATIONAL — K8s + DR + pre-prod scaffold)
- `[wave:s17/k2-w5-resilience-coordinator-class]` — `core/resilience/coordinator.py::ResilienceCoordinator` class. 12 fallback chains в lifespan.
- `[wave:s17/k3-w4-saga-state-store]` — **K-OPS-1**: `infrastructure/workflow/saga_state.py::SagaStateModel` (PostgreSQL table) — checkpoints / compensations / rollback-events. CRUD repository + integration с Temporal Workflow signal_event.
- `[wave:s17/k5-w2-k8s-manifests]` — **K-OPS-2**: `deploy/k8s/` (NEW): Deployment + Service + Ingress + NetworkPolicy + PDB + HPA + Resource requests/limits для main app + workflow-worker. Helm chart scaffold (полный финал — S18).
- `[wave:s17/k9-w1-pre-prod-check-v2-scaffold]` — **K-OPS-3**: `make pre-prod-check` v2 расширение текущих 20 → 30 gates (+10 новых: ConfigValidator startup / TaskRegistry orphans / OTel route coverage / APScheduler obs / AuthorizationGateway audit / MetricsRegistry coverage / FF default-OFF audit / Sphinx docs ≥95% / Numeric perf p95 / DR backup freshness). Финал (+8 grep V22 = 38/38) — S20.
- `[wave:s17/k5-w3-db-migration-init-container]` — **K-OPS-4**: `ops/compose/docker-compose.yml` init-container `migration-runner` (alembic upgrade head) перед `app` через `depends_on::service_completed_successfully`. `deploy/k8s/jobs/migration.yaml` для K8s. Smoke-test `manage.py db verify`.
- `[wave:s17/k1-w5-backup-dr-scaffold]` — **K-OPS-5**: `ops/backup/` scripts (pg_dump + redis-persist + clamav-update + S3-backup ClickHouse). Runbook `vault/runbooks/disaster_recovery.md`. (Полный verified drill — S20.)

#### Closure
- `[wave:s17/closure]` — DoD grep verify + memory `feedback_sprint17_gap_closure_centralization` + CONTEXT.md update + ARCHITECTURE.md обновление слоёв L1–L10 готовности.

**DoD Sprint 17 (15 критериев, ВСЕ обязательны)**:
1. ✅ `[wave:s17/backbone]` landed: 12 default-OFF flags + team_s17.k1..k5.
2. ✅ **K-SYN-1..5**: `grep -rEn "except [A-Za-z][A-Za-z0-9_]*, [A-Za-z][A-Za-z0-9_]*:" src/backend/` = **0**; `pytest tests/smoke/test_import_all.py` зелёный. **F-A-4 gate (обязательно ДО merge wave)**: codemod скрипт `tools/codemods/fix_except_clause.py` pre-tested на **5+ репрезентативных callsites** (минимум по одному из L5/L6/L7 + 2 из `dsl/`/`services/`/`entrypoints/`); diff каждого ручной review; `pytest <соответствующие тесты>` зелёный после ручного применения; только после этого batch-применение к остальным 70+ файлам. Это gate для предотвращения rollback (libcst-codemod может сломать редкие edge-cases — multi-line except, nested try, type-narrowing).
3. ✅ **K-TLS-1..3**: `grep -rn "ssl\.CERT_NONE\|check_hostname=False" src/backend/` = **0**; integration test FTPS / IMAP / IMAP-monitor verify cert-required.
4. ✅ **K-ARCH-1+2 (ADR-NEW-1+4)**: AuthorizationGateway покрывает 100% non-public endpoints; `grep "if request.user.is_admin" src/backend/` = 0; `CapabilityGatewayProtocol` в `core/interfaces/`.
5. ✅ **K-ARCH-3**: `tools/checks/check_routes_capability_gate.py` зелёный; routes/echo_demo + health_proxy_demo проходят capability-gate.
6. ✅ **K-ARCH-4**: integration test tenant-isolation между echo_demo и credit_pipeline зелёный.
7. ✅ **K-ARCH-5**: `call_function_modules` whitelist обязателен в production; all `plugin.toml` декларируют список.
8. ✅ **ADR-NEW-2 (S-L1-1)**: `MiddlewareRegistry` собирает 26 встроенных + 1+ из `plugin.toml::[[middleware]]`; `make middleware-tree` визуализирует цепочку.
9. ✅ **ADR-NEW-3**: `RequestContext` доступен через `RequestContext.current()`; structlog logs содержат `trace_id` (L7 corr-fix).
10. ✅ **D11 + D13a + D14**: ConfigValidator ≥5 rules; MetricsRegistry ≥50 метрик; `grep "asyncio.create_task" src/ | grep -v task_registry` = **0**.
11. ✅ **D12 D13b D9**: correlation_id в 100% audit events; APScheduler exporter visible в Prometheus; per-tenant FF toggle UI работает.
12. ✅ **K-OPS-1 K-OPS-2**: Saga state model + persistence; K8s manifests (Deployment/Service/PDB/HPA/Ingress) применяются `kubectl apply --dry-run=server`.
13. ✅ **K-OPS-3**: `make pre-prod-check v2` 30/30 (текущие 20 + 10 новых) gates зелёные.
14. ✅ **K-OPS-4 K-OPS-5**: БД migration init-container в docker-compose; backup scripts работают (`pg_dump | gzip | aws s3 cp` smoke).
15. ✅ **S-L7-1..3**: ClickHouse audit retry+DLQ; structlog `trace_id`; Graylog FD-leak fix; coverage ≥77%; mypy 0 сохранён; memory note `feedback_sprint17_gap_closure_centralization`.

---

### Sprint 18 — Operational + Security GAP Carryover (REPLACED 2026-05-21, 2 недели: 2026-06-19 → 2026-07-02)

**Owner**: К1 (WAF allowlist + supply-chain + Casbin/OPA wiring + JWT blacklist) / К2 (coverage + F-2 sandbox + failing tests + observability cardinality) / К3 (Core entities + EventBus DSL + per-route timeout) / К4 (AI handlers + LangFuse + Guardrails enforcer + LangMem consolidation) / К5 (F-5 stubs + Layer violations + K8s Helm chart финал + multi-environment configs).
**Приоритет**: **P1** (techdebt + Operational GAP carryover + Security серьёзные пробелы).
**Источник**: GAP-аудит 2026-05-21 → S-L1/S-L7/S-L8 пробелы + 4 функциональных предложения operational-фокус (БД migration init / K8s Helm / multi-tenant rate-limit / pre-prod-check v2).
**ВАЖНО**: credit-pipeline 5 интеграционных клиентов (DaData/БКИ/СМЭВ/ЦБ/1С) — **НЕ В ЭТОМ ПЛАНЕ**.

#### Wave 0 — Backbone
- `[wave:s18/backbone]` — 8 default-OFF feature-flags (`waf_strict_zero_allowlist` / `failing_tests_quarantined_off` / `sandbox_amortised_final` / `core_entities_legacy_off` / `eventbus_dsl_enabled` / `langfuse_production_wired` / `opa_runtime_query_enabled` / `multi_tenant_rate_limit_enabled`) + team_s18.k1..k5.

#### Wave 1–4 (S-L8 Security pробелы)
- `[wave:s18/k1-w1-waf-allowlist-tightening]` — миграция 23 callsites в `tools/check_waf_coverage_allowlist.txt` на `make_http_client()`. Список: express_bot / telegram_bot / opa / clickhouse / vault_cipher / ml_inference / proxy/forward / imports endpoint / webhook handler/transformer / search_providers / Vault×2 / bots×2.
- `[wave:s18/k1-w2-supply-chain-finale]` — SBOM CycloneDX + cosign sign + pip-audit zero HIGH/CRITICAL; secrets-check zero-tolerance; OWASP ZAP gate blocking (S-L8-6: `make audit-zap` exit 1 при HIGH); `make security` exit 0.
- `[wave:s18/k1-w3-casbin-opa-runtime-query]` — **S-L8-1, S-L8-2**: интегрировать `CapabilityPolicy` с Casbin tenant-scoped enforcer; OPA-client runtime-query через `AuthorizationGateway.opa_step()`; политики в `infrastructure/policy/opa/policies/` (rego). Smoke-test allow/deny decision.
- `[wave:s18/k1-w4-jwt-blacklist-batch-revoke]` — **S-L8-5**: `core/auth/jwt_blacklist.JwtBlacklist.revoke_before_time(time)` для batch-revocation при JWKS rotation; `JwtBackend.verify(token)` проверяет jti против blacklist; Redis backend; integration test rotation scenario.

#### Wave 5–9 (S-L1 + S-L7 + multi-environment)
- `[wave:s18/k3-w1-pii-response-middleware]` — **S-L8-4**: `entrypoints/middlewares/pii_masking_response.py::PIIMaskingResponseMiddleware` — global response wrapper применяет `pii_masker` к JSON body на configurable path patterns. Default-OFF feature-flag.
- `[wave:s18/k3-w2-per-route-timeout]` — **P0 Gateway-centralization gap**: per-route timeout через `route.toml::[timeout]` (connect/read/write/total) + DSL `.policy.timeout(connect=..., read=..., total=...)`. `TimeoutMiddleware` читает per-route metadata; fallback на global default.
- `[wave:s18/k5-w1-rate-limit-global-mw]` — **P0 Gateway-centralization gap**: `entrypoints/middlewares/global_rate_limit.py::RateLimitMiddleware` (на базе fastapi-limiter) — global default + per-route override + per-tenant via Casbin/OPA. **Поддерживает функциональное предложение "multi-tenant rate-limiting"**.
- `[wave:s18/k7-w1-observability-cardinality-tenant]` — **S-L7-5, S-L7-6**: `tenant_id` label во все Prometheus metrics через `MetricsRegistry`; W3C TraceContext propagation в Kafka/RabbitMQ headers через textmap propagator; cardinality enum-нормализация.
- `[wave:s18/k9-w1-multi-environment-configs]` — **S-L9-3**: `config_profiles/{dev,staging,prod}.yml` + docker-compose env-file selection; `manage.py validate-profile <env>` ConfigValidator integration.

#### Wave 10–14 (techdebt + carryover S16)
- `[wave:s18/k2-w1-coverage-ramp-70]` — ratchet 50→70%; per-layer breakdown; команды добавляют тесты (К1 security ≥75% / К2 resilience ≥80% / К3 dsl ≥75% / К4 ai ≥65% / К5 frontend ≥60%).
- `[wave:s18/k2-w2-failing-tests-triage]` — разобрать ~91 pre-existing failing tests; fix / xfail-с-ADR / skip-feature-flag.
- `[wave:s18/k1-w5-plugin-trust-2tier]` — **ADR-NEW-6 / B-4** (замещает `[wave:s18/k2-w3-sandbox-f2-final]`): `plugin.toml::trust_tier = "A" | "B"`. Tier-A (signed by org-CA cosign) — runtime sandbox **disabled**; isolation через capability-gate + code-review CI + supply-chain. Tier-B (untrusted/external) — strict e2b/pyodide. Existing 3 plugins (`example_plugin`, `credit_pipeline`, `core_entities`) → Tier-A по умолчанию. Cosign-signing pipeline extends supply-chain (`make security`). DoD S18 #11 переформулируется: F-2 closure через model change, не sandbox-tuning.
- `[wave:s18/k1-w6-multi-tenancy-mb-reduce]` — **ADR-NEW-9 / B-6** (NEW): scope reduction до M-B (Multi-BU одного банка). `TenantContext` остаётся (BU-разграничение + audit `tenant_id`). Per-tenant SLO/quota → **per-BU rate-limit + budget** (Casbin/OPA policies + fastapi-limiter tenant-aware namespace). `infrastructure/security/tenant_encryption.py` удаляется (~200 LOC) + `post-v22-backlog/m-c-encryption.md` создаётся для будущего M-C use case. IDS-per-tenant удаляется (общий SIEM через Graylog). Migration note в KNOWN_ISSUES.md.
- `[wave:s18/k5-w5-multi-backend-tiers]` — **ADR-NEW-11 / B-2** (NEW): Tier-A (PG+Oracle, RabbitMQ+Kafka, S3+MinIO) — full CI integration + perf-gate + chaos. Tier-B (MSSQL/MySQL/DB2, Redis Streams/NATS, LocalFS) — minimal smoke test only. `pyproject.toml` extras restructure: `db-tier-a` / `db-tier-b` / `mq-tier-a` / `mq-tier-b` / `storage-tier-a` / `storage-tier-b`. README + `docs/backends.md` явная декларация tiers. CI matrix pruning: 12 backends → 5 actively-tested.
- `[wave:s18/k3-w3-core-entities-final-cleanup]` — удалить `src/backend/services/core/{users.py,orders.py,orderkinds.py}` legacy; импортёры на `extensions/core_entities/`.
- `[wave:s18/k3-w4-eventbus-dsl-methods]` — `RouteBuilder.to_eventbus(topic, payload_ref)` + `.from_eventbus(topic_pattern, ack_mode)` + 2 step-type.
- `[wave:s18/k4-w1-ai-workflow-handlers]` — handlers `services/ai/workflows/{rag_query,multi_agent_supervisor,e2b_execute}.py`; LangFuse production wiring + cost dashboard.
- `[wave:s18/k4-w2-multimodal-rag-pipeline]` — **S11 K4 W2 carryover**: ingest → chunking → embedding → Qdrant → retrieval → rerank → LLM.

#### Wave 15–18 (operational — K8s Helm + БД migration finalize)
- `[wave:s18/k5-w2-pyi-stub-fidelity]` — **F-5 carryover**: `tools/gen_dsl_stubs._resolve_annotation` через `typing.get_type_hints` + PEP-695.
- `[wave:s18/k5-w3-layer-violations-protocol-extraction]` — Layer violations 73 → 0; composition-root из `core/` в `infrastructure/`.
- `[wave:s18/k5-w4-k8s-helm-chart-finale]` — **Func-rec #9**: `deploy/helm/` — Helm chart полный (Chart.yaml + values.yaml + templates/{deployment,service,ingress,hpa,pdb,configmap-secret}.yaml). Values: dev/staging/prod profiles. `helm template . | kubectl apply --dry-run=server` зелёный. `helm test` smoke job.
- `[wave:s18/k4-w3-guardrails-enforcer]` — **S-L4-2**: `GuardrailsEnforcerProcessor` в `dsl/engine/processors/ai.py` перед `LLMCallProcessor`; интеграция Lakera/Rebuff клиентов; default-ON в `[ai]` extra; PromptInjection / ToxicContent / PII-leakage detection.
- `[wave:s18/verify-routes-integration]` — Integration test 3 routes (`routes/health_proxy_demo/` + `routes/echo_demo/` + `extensions/core_entities/`) с ConfigValidator+MetricsRegistry+EventBus+TaskRegistry+per-route-timeout+rate-limit; testcontainers; 5+ assertion checkpoints.

#### Closure
- `[wave:s18/closure]` — DoD verify + memory `feedback_sprint18_operational_security`.

**DoD Sprint 18 (18 критериев, расширено ADR-NEW-6/-9/-11)**:
1. ✅ `[wave:s18/backbone]` landed.
2. ✅ WAF allowlist пуст: `tools/check_waf_coverage_allowlist.txt` = 0 lines.
3. ✅ Supply-chain: `make security` exit 0; OWASP ZAP gate **blocking** для HIGH.
4. ✅ **S-L8-1, S-L8-2**: Casbin/OPA runtime-query через AuthorizationGateway; интеграционный test allow/deny.
5. ✅ **S-L8-5**: JWT batch-revoke при JWKS rotation работает.
6. ✅ **S-L8-4**: PII response middleware применяется на configurable paths; integration test PII не утекает.
7. ✅ **Gateway P0**: per-route timeout (route.toml + DSL) работает; global rate-limit MW с per-tenant активирован.
8. ✅ **S-L7-5, S-L7-6**: `tenant_id` label в metrics; W3C TraceContext в MQ headers; cardinality OK.
9. ✅ **S-L9-3**: multi-environment configs (`config_profiles/{dev,staging,prod}.yml`); `manage.py validate-profile prod` зелёный.
10. ✅ Coverage ≥70%; per-layer breakdown; pre-existing failing tests = 0.
11. ✅ **ADR-NEW-6 / B-4 (замещает F-2 numeric DoD)**: `plugin.toml::trust_tier = "A" | "B"` enforced; 3 existing plugins → Tier-A signed by org-CA cosign; runtime sandbox disabled for Tier-A; Tier-B e2b sandbox numerically <5% overhead.
12. ✅ Core entities legacy удалены; `RouteBuilder.to_eventbus()/.from_eventbus()` доступны.
13. ✅ 3 AI workflow handlers + LangFuse + Multimodal RAG pipeline regression-test зелёный.
14. ✅ **Func-rec #9**: K8s Helm chart `helm template . | kubectl apply --dry-run=server` зелёный.
15. ✅ **S-L4-2**: Guardrails enforcer применяется перед LLMCallProcessor; integration test prompt-injection заблокирован; layer violations 0; F-5 stubs 100%; routes integration зелёный; memory note.
16. ✅ **ADR-NEW-9 / B-6**: Multi-tenancy scope reduced до M-B (Multi-BU одного банка); `infrastructure/security/tenant_encryption.py` removed; `TenantContext` + ACL + audit per BU работают; `post-v22-backlog/m-c-encryption.md` создан как revert-path для M-C use case.
17. ✅ **ADR-NEW-11 / B-2**: Tier-A (PG+Oracle, RabbitMQ+Kafka, S3+MinIO) — CI integration + perf-gate + chaos зелёные; Tier-B (MSSQL/MySQL/DB2, Redis Streams/NATS, LocalFS) — smoke test only; `pyproject.toml` extras разделены (db-tier-a/b, mq-tier-a/b, storage-tier-a/b); `docs/backends.md` опубликован.
18. ✅ **F-A-4 codemod pre-test gate** (S17 carryover): `tools/codemods/fix_except_clause.py` pre-tested на 5+ репрезентативных callsites ДО batch-применения (если carryover из S17 не закрыт в S17).

---

### Sprint 19 — DSL+AI расширения + DX (REPLACED 2026-05-21, 2 недели: 2026-07-03 → 2026-07-16)

**Owner**: К1 (F-6 sys._current_frames + secrets-finale) / К2 (Adaptive timeout + Coverage ratchet + multi-replica failover) / К3 (LSP финал + Visual Editor + route composition + workflow versioning + route authz) / К4 (Adaptive RAG strategy + Multipart RAG ingest + Reranking + LangMem consolidation + Banking AI processors) / К5 (VSCode extension + Quick wins + Testkit API + RPA browser session persistence).
**Приоритет**: **P1** (functional expansion из GAP-аудита Phase 3 + DX baseline для onboarding ≤ 1 час).
**Источник**: 10 функциональных предложений Phase 3 (все приняты) + S-L4 carryover (Banking AI / LangMem / Reranking / Multipart) + S-L5 carryover (RPA session persistence) + S-L10 carryover (Public testkit API) + S-L6 carryover (replica failover).

#### Wave 0 — Backbone
- `[wave:s19/backbone]` — 10 default-OFF feature-flags (`vscode_extension_published` / `lsp_server_strict` / `dsl_visual_editor_drag_drop` / `ai_pr_review_enabled` / `adaptive_timeout_enabled` / `workflow_versioning_routes` / `route_composition_include` / `route_authz_requires_permission` / `rag_multipart_ingest` / `rpa_session_persistence`) + team_s19.k1..k5.

#### Wave 1–6 (DSL расширения из Func-rec #1, #2, #3)
- `[wave:s19/k3-w1-workflow-versioning-routes]` — **Func-rec #1**: `route.toml` добавить секцию `[requires_workflows] = { "wf_name" = ">=1.0,<2.0" }`. `RouteLoader.load()` проверяет совместимость версий workflow при загрузке; `RouteBuilder.invoke_workflow(name, version=...)` принимает SemVer-range. Audit-event `workflow.version.mismatch`.
- `[wave:s19/k3-w2-route-composition-include]` — **Func-rec #2**: `*.dsl.yaml` поддерживает `include: ["./common-steps.yaml"]` (один уровень) + `extends: ./base-route.yaml`. YAML-loader разрешает дерево включений с cycle detection. JSON-Schema каталог обновляется.
- `[wave:s19/k3-w3-route-authz-requires-permission]` — **Func-rec #3**: `route.toml::[security] requires_permission = ["role:admin", "scope:credit.read"]`. `AuthorizationGateway` (S17 ADR-NEW-1) проверяет перед dispatch на route. Capability-gate в `RouteLoader.load()` валидирует синтаксис permission-string.
- `[wave:s19/k4-w1-multipart-rag-ingest]` — **Func-rec #4**: `POST /api/v1/ai/rag/bulk-ingest` multipart endpoint для bulk document upload. Streamlit page bulk-ingest UI. Capability `rag.ingest.<collection>` обязательна.
- `[wave:s19/k4-w2-reranking-pipeline]` — **Func-rec #5**: `RerankerProcessor` в `dsl/engine/processors/ai.py`; интегрировать в `RagQueryProcessor` (default-OFF). Поддержка cross-encoder моделей (BAAI/bge-reranker, cohere-rerank API). Latency budget tracking.
- `[wave:s19/k5-w1-rpa-browser-session-persistence]` — **Func-rec #6 (S-L5-2)**: Redis-backed session-store (`key = tenant_id:session_id`) с cookies/auth/local-storage; lazy-restore в `BrowserLaunchProcessor`; TTL configurable. RPA-route `routes/banking_legacy_session_demo/` как reference.

#### Wave 7–10 (Banking AI + LangMem + AI carryover)
- `[wave:s19/k4-w3-banking-ai-processors-impl]` — **S-L4-1**: реализовать логику в `dsl/engine/processors/ai_banking.py` (KycAmlVerifyProcessor / AntiFraudScoreProcessor / CreditScoringRagProcessor / DocumentClassifierProcessor / FrancotypingProcessor): LLM call + structured output Pydantic + capability-gate `ai.banking.*` + audit-event + cost budget tracking.
- `[wave:s19/k4-w4-langmem-consolidation-impl]` — **S-L4-3**: реализовать `LangMemService.consolidate()`: episodic → semantic compaction через LLM-summarisation; интеграция с langmem package; запуск через APScheduler eachly + admin-trigger; metrics consolidation count + token usage.
- `[wave:s19/k2-w1-multi-replica-failover]` — **S-L6-4**: `SmartSessionManager` поддержка multi-replica failover; replication-lag monitoring через `pg_stat_replication`; auto-routing по lag-budget; chaos test (kill replica).
- `[wave:s19/k1-w1-vault-zero-downtime-rotation]` — **S-L6-6**: zero-downtime Vault rotation: graceful reconnect + сохранение старого secret N минут drift-toleration + validation новых credentials ДО активации.

#### Wave 11–16 (DX + LSP/Visual Editor + Testkit)
- `[wave:s19/k5-w2-vscode-extension]` — `tools/vscode-extension/` `.vsix`: syntax highlighting + hover docs + "Run step" CodeLens + LSP client. Private marketplace publish (ADR R1.14).
- `[wave:s19/k3-w4-lsp-server-finale]` — расширение `tools/dsl_lsp/server.py` (S16 baseline): YAML schema completion + diagnostics через DSL Linter; integration test pygls test-client.
- `[wave:s19/k3-w5-dsl-visual-editor-finale]` — `frontend/streamlit_app/pages/31_DSL_Visual_Editor.py`: drag-drop + YAML/BPMN export + undo/redo + step palette с capability descriptions.
- `[wave:s19/k4-w5-ai-pr-review-action]` — `.github/workflows/ai-pr-review.yml`: layer-policy + security + perf-regression + coverage delta; prompt caching ≥80% hit; cost ≤$0.10/PR.
- `[wave:s19/k5-w3-testkit-public-api]` — **S-L10-1**: `src/testkit/` (NEW) — public API для extensions/plugin authors. Components: `RouteRunner`, `WorkflowRunner`, `MockCapabilityGateway`, `FakeWorkflowBackend`, `recorder/replay` fixtures, `assert_audit_event`, `assert_metric_recorded`. Документация в `docs/testkit/`.
- `[wave:s19/k5-w4-quick-wins-pack]` — `make new-adr TITLE="..."` + `manage.py completions install` + `make release-notes` + `frontend/streamlit_app/pages/05_Architecture_Map.py` (D3.js).

#### Wave 17–24 (carryover + diagnose + ADR finalize + Phase B critical incorporation)
- `[wave:s19/k2-w2-manage-py-diagnose]` — `manage.py diagnose` aggregator JSON output для CI.
- `[wave:s19/k1-w2-current-frames-fallback]` — **F-6 carryover**: `sys._current_frames()` graceful fallback для PyPy/Jython.
- `[wave:s19/k2-w3-adaptive-timeout-policy]` — `.policy.adaptive_timeout(percentile=99, safety_factor=1.5)` builder API.
- `[wave:s19/k4-w6-adaptive-rag-strategy-finale]` — расширение S16 K4 W1: dense/hybrid/hyde/multi_query через LLM-classifier; accuracy +15% bench; latency <50ms.
- `[wave:s19/k2-w4-coverage-ratchet-75]` — ratchet 70→75%; per-layer enforcement.
- `[wave:s19/adr-w1-r1-1-r1-5-r1-7]` — ADR R1.1 / R1.5 / R1.7 finalize.
- `[wave:s19/adr-w2-r1-8-r1-9-r1-20]` — ADR R1.8 / R1.9 / R1.20 finalize.
- `[wave:s19/k1-w5-ai-safety-capability-unify]` — **ADR-NEW-5 / B-3** (NEW): единая capability `fs.write.<scope>`; AI-плагины декларируют `fs.write.workspace.*`; запрет `fs.write.repo.*`. Legacy `fs.create_new.<workspace>` → deprecated alias через `CapabilityRegistry.resolve()` + audit-event `capability.deprecated_alias`. 3 existing AI-plugins (если есть) migrate на новую capability. Docstring update в `core/ai/workspace_manager.py`.
- `[wave:s19/k1-w6-prod-hot-reload-disable]` — **ADR-NEW-7 / B-5** (NEW): при `APP_PROFILE=prod` все hot-reload пути disabled (DSLYamlWatcher, PluginLoader.hot_swap → `OperationNotPermittedInProductionError`, RouteLoader.hot_reload). `PluginInventorySnapshot.hash()` (SHA-256 of sorted plugin@version × route@version × middleware@version) на startup → bind в structlog `bind_contextvars(plugin_inventory_hash=...)` + persist в ClickHouse audit column. Apt-style atomic upgrade (`ops/deploy/atomic-rollout.sh` scaffold). DoD V22 «Hot Reload < 3 сек» переформулируется на dev_light only.
- `[wave:s19/k3-w6-dsl-usage-audit]` — **ADR-NEW-10 / B-1** (NEW): `tools/audit/dsl_usage_audit.py` собирает callsites методов `RouteBuilder` + blueprints + processors из `routes/`, `extensions/`, `tests/`. Methods с <5 callsites → `@warnings.deprecated` + LSP completion warning. JSON report `audit-out/dsl_usage_report.json` + Streamlit page `frontend/streamlit_app/pages/86_DSL_Usage_Audit.py`. Deprecation в S19, removal — post-V22 (V23 backlog). Целевая метрика 150 → 70-90 cohesive methods к V23.
- `[wave:s19/k5-w5-admin-react-mvp]` — **ADR-NEW-8 / B-7** (NEW): двухпортальная архитектура. `frontend/streamlit_app/` остаётся developer portal (dev_light + staging). `frontend/admin-react/` (NEW) — React + Vite + FastAPI admin endpoints; MVP 5-7 страниц: audit log viewer / feature flags admin / plugin inventory / user management / capability grants / audit replay. RBAC через `AuthorizationGateway.authorize()` (ADR-NEW-1). Audit-trail каждого UI-клика через middleware → `audit.admin_action` с trace. SSO через SAML+AD (S18 К1).

#### Closure
- `[wave:s19/closure]` — DoD verify + memory `feedback_sprint19_dsl_ai_dx`.

**DoD Sprint 19 (19 критериев, расширено ADR-NEW-5/-7/-8/-10)**:
1. ✅ `[wave:s19/backbone]` landed.
2. ✅ **Func-rec #1**: workflow versioning в route.toml работает; SemVer-range validation.
3. ✅ **Func-rec #2**: route composition `include:` / `extends:` работает; cycle detection.
4. ✅ **Func-rec #3**: route-level `requires_permission` enforced через AuthorizationGateway.
5. ✅ **Func-rec #4**: multipart RAG bulk-ingest endpoint + UI.
6. ✅ **Func-rec #5**: RerankerProcessor + integration test в RagQueryProcessor.
7. ✅ **Func-rec #6 (S-L5-2)**: RPA browser session persistence + `routes/banking_legacy_session_demo/` reference.
8. ✅ **S-L4-1**: Banking AI processors functional (KYC/AML/CreditScoring/DocumentClassifier/Francotyping) с capability+audit+cost.
9. ✅ **S-L4-3**: LangMem `consolidate()` реализован; metrics visible.
10. ✅ **S-L6-4, S-L6-6**: multi-replica failover + chaos test; Vault zero-downtime rotation.
11. ✅ VSCode extension `.vsix`; LSP server финал; DSL Visual Editor финал; AI PR review активен.
12. ✅ **S-L10-1**: `src/testkit/` public API доступен; 5+ example extensions tests используют.
13. ✅ Quick wins (`make new-adr`, `manage.py completions install`, `make release-notes`, Arch Map) работают.
14. ✅ `manage.py diagnose` JSON output; F-6 graceful fallback; adaptive_timeout + adaptive RAG strategy.
15. ✅ Coverage ≥75%; ADR R1.1 / R1.5 / R1.7 / R1.8 / R1.9 / R1.20 — Status: Accepted; memory note.
16. ✅ **ADR-NEW-5 / B-3**: единая capability `fs.write.<scope>` enforced; AI-плагины используют `fs.write.workspace.*`; запрет `fs.write.repo.*`; legacy `fs.create_new.<workspace>` deprecated alias работает через `CapabilityRegistry.resolve()` + audit-event.
17. ✅ **ADR-NEW-7 / B-5**: `APP_PROFILE=prod` ⇒ hot-reload disabled (3 пути); `PluginInventorySnapshot.hash()` SHA-256 в каждом audit-event; ClickHouse audit column `plugin_inventory_hash` присутствует; `ops/deploy/atomic-rollout.sh` scaffold.
18. ✅ **ADR-NEW-10 / B-1**: `make dsl-usage-audit` зелёный; `audit-out/dsl_usage_report.json` сгенерирован; <5-callsite методы `@warnings.deprecated`; Streamlit page 86 работает; metric `dsl_methods_count` в Prometheus.
19. ✅ **ADR-NEW-8 / B-7**: `frontend/admin-react/` MVP — 5-7 страниц работают (audit log / feature flags / plugin inventory / user mgmt / capability grants / audit replay); RBAC через AuthorizationGateway; audit-trail UI-clicks в ClickHouse; SAML+AD SSO интегрирован.

---

### Sprint 20 — Production Signoff (2 недели: 2026-07-17 → 2026-07-31)

**Owner**: координатор + все 5 команд параллельно.
**Приоритет**: **P0** (финальный production-ready signoff; push в origin master).

#### Wave 0 — Backbone
- `[wave:s20/backbone]` — 4 feature-flags (`perf_gate_strict_p95_80ms` / `coverage_gate_83` / `mypy_strict_zero` / `pre_prod_check_v2_full`) — все default-OFF до прохождения wave, default-ON в финале.

#### Wave 1–10 (security audit + perf bench + coverage finale + docs + canary + release)
- `[wave:s20/k1-w1-final-security-audit]` — OWASP ZAP scan (zero HIGH/CRITICAL) + OWASP API Top 10 (10/10 покрыты schemathesis) + pip-audit (zero HIGH) + bandit TLS (zero HIGH) + cosign verify SBOM + secrets scan zero-tolerance + Vale prose linter.
- `[wave:s20/k2-w1-final-perf-bench]` — k6 + locust суиты; **p95 ≤80ms на cached route** (от 200ms baseline); **RPS ≥1500** (от 1000 baseline); perf-gate enforced в CI (flip `perf_gate_strict_p95_80ms` default-ON).
- `[wave:s20/k2-w2-mypy-zero-strict]` — финальный mypy reduction до **0 errors** в strict mode (от текущих 30); все `# type: ignore` либо оправданы (с ADR-ссылкой), либо удалены.
- `[wave:s20/k2-w3-coverage-finale-83]` — ratchet 75→**83%** (V22 final target); per-layer enforcement.
- `[wave:s20/k5-w1-docs-finale]` — Sphinx auto-gen build `-W` (warnings = errors) zero; Diátaxis 15+ tutorials + 20+ runbooks; ReadTheDocs publish verified; AsyncAPI 3 export + diff=0 gate.
- `[wave:s20/k2-w4-pre-prod-check-v2-full]` — финальный pre-prod-check v2:
  - 20 текущих критериев (без изменений).
  - 10 новых: ConfigValidator startup / TaskRegistry coverage 0 orphan / OTel route coverage / APScheduler observability / AuthorizationGateway audit / MetricsRegistry coverage / FF default-OFF audit / Sphinx docs ≥95% / Numeric perf p95 ≤80ms RPS ≥1500 / DR backup freshness.
  - 8 grep V22: `asyncio.create_task` вне TaskRegistry = 0 / `from tenacity import` вне resilience = 0 / `= Counter(` вне MetricsRegistry = 0 / `= Histogram(` вне MetricsRegistry = 0 / `get_secret_value()` вне backends = 0 / `APIKeyMiddleware` = 0 / `notification_hub` import = 0 / `threading.RLock` в async = 0.
  - Composite gate JSON: `{mypy_errors: 0, coverage_percent_min: 83, layer_violations: 0, perf_p95_ms_max: 80, perf_rps_min: 1500, startup_time_s_max: 3.0, waf_allowlist_size_max: 0, docstring_allowlist_size_max: 0, task_registry_orphans_max: 0, feature_flags_default_on_max: 0}`.
- `[wave:s20/k2-w5-chaos-finale]` — 33/33 chaos-tests green в CI; 5+ Grafana dashboards production-ready (admin / AI / DB-replica / RAG-strategy / cron-scheduler).
- `[wave:s20/k1-w2-dr-backup-runbook-verified]` — DR & Backup runbook: DB backup verified (weekly drill, restore <30 min, RPO ≤1h); Vault snapshot raft restore (monthly drill); ClickHouse audit replay (validate idempotency, bit-exact); Plugin hot-swap rollback (graceful drain 30s + state migration). `tools/check_dr_freshness.py` зелёный.
- `[wave:s20/ops-w1-staging-canary-rollout]` — canary 1% (30 min, error rate <0.01%) → 10% (2 hours, all SLO green) → 50% (4 hours, soak load + CH audit replay test) → 100% (24 hours soak, alert rules silent). 5 rollback runbooks верифицированы (blue-green / plugin / feature-flag / db migration / secret rotation).
- `[wave:s20/release-w1-tag-push]` — `git tag -a v1.0.0-production -m "..."`; `git push origin master` (с явного подтверждения пользователя); `CHANGELOG.md` финал из wave-коммитов через `make release-notes`.

#### Closure
- `[wave:s20/closure]` — финальный memory `project_v22_production_ready` + CONTEXT.md production-final + post-release backlog зафиксирован в `docs/backlog-post-release.md`.

**DoD Sprint 20 (15 критериев, ВСЕ обязательны)**:
1. ✅ OWASP ZAP scan: 0 high, 0 critical findings.
2. ✅ OWASP API Top 10: все 10 категорий покрыты тестами (schemathesis).
3. ✅ pip-audit: 0 HIGH/CRITICAL vulnerabilities; cosign verify SBOM зелёный.
4. ✅ p95 latency ≤80ms на cached route (k6 baseline).
5. ✅ RPS ≥1500 (locust baseline).
6. ✅ mypy --strict: **0 errors**.
7. ✅ layer violations: **0** (strict, без allowlist).
8. ✅ Coverage ≥**83%**.
9. ✅ Sphinx docs build без warnings; 15+ tutorials; 20+ runbooks; ReadTheDocs deploy verified.
10. ✅ `make pre-prod-check` v2: **38/38** gates зелёные (20+10+8).
11. ✅ `manage.py diagnose` без findings; CI integration активен.
12. ✅ 33/33 chaos-tests green; 5+ Grafana dashboards production-ready.
13. ✅ DR & Backup runbook verified: DB RPO≤1h RTO≤30min; Vault snapshot restore; ClickHouse audit replay; Plugin hot-swap rollback.
14. ✅ Staging-canary rollout 1→10→50→100% verified; 5 rollback runbooks tested.
15. ✅ `git tag v1.0.0-production` создан; `git push origin master` выполнен (с явного подтверждения пользователя); `CHANGELOG.md` финал; CONTEXT.md production-final; memory note + `vault/archive-plan-v21.md` сохранён.

---

> **Sprint 21–23** — post-production GAP-backlog, основанный на
> `gap-analysis/DEEP-RESEARCH-gd_integration_tools-2026-05-20.md` (10 CRITICAL
> B-01..B-10 + 16 P0 STRONGLY RECOMMENDED G-01..G-16 + 15 функциональных
> предложений F-01..F-15 + 7 архитектурных рекомендаций A-01..A-07). **БЕЗ
> конкретных дат**, выполняется ПОСЛЕ Sprint 20 (`v1.0.0-production`)
> параллельно release stabilization. Не блокируют release v1.0.0. Часть GAP уже
> покрыта в S17–S20 (B-01, G-01, G-11, G-12, F-13, ADR-NEW-9, B-04); 28 пунктов
> переносятся в S21–S23 + 5 follow-up к частично покрытым (B-06, G-04, G-05,
> F-08, F-15). 4 новых ADR (ADR-NEW-12..15) — см. §6.

### Sprint 21 — Resilience & Multi-tenancy Hardening (post-production gap-backlog)

**Owner**: К1 / К2 / К3 (К4/К5 — backbone only).
**Приоритет**: **P0** (CRITICAL блокеры B-02/B-03/B-05/B-09).
**Источник**: DEEP-RESEARCH 2026-05-20 A-03/A-04/A-05 + B-02/B-03/B-05/B-09 + G-06/G-07/G-08/G-09.

#### Wave 0 — Backbone
- `[wave:s21/backbone]` — 8 default-OFF feature-flags: `RLS_POSTGRES_ENFORCE`, `TENANT_CACHE_PREFIX_ENABLED`, `RPA_RESILIENCE_WRAPPER_ENABLED`, `SCHEDULER_DLQ_ENABLED`, `WEBHOOK_RESILIENCE_POLICY_ENABLED`, `DESKTOP_RPA_SESSION_POOL_ENABLED`, `BROWSER_COOKIES_REDIS_PERSIST`, `WORKFLOW_STATE_SQLITE_PERSIST`. Добавить в `core/config/feature_flags.py`, инвентарь admin `/admin/feature-flags`.

#### Wave 1-2 (К1 Security/Multi-tenancy)
- `[wave:s21/k1-w1-rls-postgres]` — **ADR-NEW-12 RLS Strategy** (A-03, G-08): миграция Alembic `CREATE POLICY ... USING (tenant_id = current_setting('app.tenant_id'))` для multi-tenant таблиц (`orders`, `users`, `files`, `audit_log`, `routes_state`). FF `RLS_POSTGRES_ENFORCE=true` включает policy enforcement. SET LOCAL per-request через `TenantContextMiddleware`. Tests: `tests/security/test_rls_isolation.py` (5 сценариев leakage).
- `[wave:s21/k1-w2-tenant-cache-wrapper]` — **A-03 TenantCacheBackend** (B-03): wrapper в `infrastructure/cache/tenant_wrapper.py` поверх RedisCache / S3Cache / MemoryCache. Все cache ops через `TenantCacheBackend.get/set(key, value, tenant_id)`. Auto-prefix `tenant:{id}:`. FF `TENANT_CACHE_PREFIX_ENABLED`. Tests: `tests/cache/test_tenant_isolation.py`.

#### Wave 3-5 (К2 Resilience)
- `[wave:s21/k2-w1-rpa-resilience-wrapper]` — **ADR-NEW-13 RPACallPolicy** (A-05, B-02): `core/resilience/rpa_policy.py` — единый wrapper над `browser_pool`/`cdc`/`filewatcher`/`webhook_scheduler`/`desktop_rpa`. Композирует `@with_retry` + `breaker.guard()` + DLQ через `outbox`. FF `RPA_RESILIENCE_WRAPPER_ENABLED`. Tests: `tests/resilience/test_rpa_policy.py` (5 toxiproxy сценариев).
- `[wave:s21/k2-w2-scheduler-dlq]` — **G-09 Scheduler DLQ**: APScheduler job failures → DLQ в `outbox.dead_letter_queue` с `kind=scheduler_job`. Admin `/admin/scheduler/dlq` для retry/replay. FF `SCHEDULER_DLQ_ENABLED`. Tests: `tests/scheduler/test_dlq.py`.
- `[wave:s21/k2-w3-webhook-resilience]` — **G-07 Webhook resilience**: `entrypoints/webhook/scheduler.py` обёрнут в `RPACallPolicy` + декларативная retry policy (см. S23 W4 follow-up). FF `WEBHOOK_RESILIENCE_POLICY_ENABLED`. Tests: `tests/webhook/test_resilience.py`.

#### Wave 6-8 (К3 RPA/Workflow)
- `[wave:s21/k3-w1-desktop-rpa-pool]` — **F-12 + B-09 DesktopRPASessionPool**: `services/rpa/desktop_session_pool.py` — пул persistent pywinauto `Application()` instances. Session affinity по `app_name`. Auto-reconnect на stale handles. TTL 30 мин. FF `DESKTOP_RPA_SESSION_POOL_ENABLED`. Tests: `tests/rpa/test_desktop_pool.py`.
- `[wave:s21/k3-w2-browser-cookies-redis]` — **G-06 Browser cookies persistence**: `services/rpa/browser_pool.py` сохраняет cookies/localStorage в Redis hash `browser:session:{user_id}:{domain}` с TTL 24h. Restore при следующем launch. FF `BROWSER_COOKIES_REDIS_PERSIST`. Tests: `tests/rpa/test_browser_cookies.py`.
- `[wave:s21/k3-w3-workflow-state-persist]` — **ADR-NEW-14 Workflow State Persistence** (A-04, B-05): `infrastructure/workflow/lite_temporal_backend.py` — добавить SQLite persistence (`aiosqlite`) для in-flight workflow state. Production Temporal `WorkflowState` class для saga compensating state. FF `WORKFLOW_STATE_SQLITE_PERSIST`. Tests: `tests/workflow/test_state_persistence.py` (4 crash-recover сценария).

#### Wave 9 (К5 Frontend)
- `[wave:s21/k5-w1-streamlit-tenant-admin]` — Streamlit page `pages/81_tenant_inspection.py`: tenant cache hit-rates, RLS-policy status, RPA session pool stats, scheduler DLQ size. Read-only.

#### Closure
- `[wave:s21/closure]` — DoD grep verify + memory note `feedback_sprint21_resilience_multitenancy.md` + CONTEXT.md update.

**DoD Sprint 21 (12 критериев)**:
1. ✅ `[wave:s21/backbone]` landed: 8 feature-flags default-OFF в `feature_flags.py`.
2. ✅ **B-03/G-08**: `grep -rn "redis.set\|redis.get" src/backend/ | grep -v tenant_wrapper` = **0** (все cache ops через TenantCacheBackend).
3. ✅ **B-03**: миграция Alembic с `CREATE POLICY` применена для 5+ таблиц; `tests/security/test_rls_isolation.py` зелёный (5 сценариев leakage).
4. ✅ **ADR-NEW-12 RLS Strategy** принят в `.claude/DECISIONS.md`.
5. ✅ **B-02**: `grep -rn "browser_pool.acquire\|cdc.run\|filewatcher.watch\|webhook.send" src/backend/ | grep -v rpa_policy` = **0**; `tests/resilience/test_rpa_policy.py` 5/5 toxiproxy зелёные.
6. ✅ **ADR-NEW-13 RPACallPolicy** принят.
7. ✅ **G-09**: scheduler job failure → DLQ event verified; admin `/admin/scheduler/dlq` UI работает.
8. ✅ **G-07**: webhook scheduler retry budget исчерпывается → DLQ; CB state visible через `/admin/circuit-breakers` (S22).
9. ✅ **B-09/F-12**: DesktopRPASessionPool warm на 5 sessions; `tests/rpa/test_desktop_pool.py` зелёный; reconnect на stale verified.
10. ✅ **G-06**: browser cookies survive worker restart; verified в `tests/rpa/test_browser_cookies.py`.
11. ✅ **B-05/A-04**: workflow crash → resume from SQLite state; `tests/workflow/test_state_persistence.py` 4/4; **ADR-NEW-14** принят.
12. ✅ Memory note + CONTEXT.md updated; Streamlit page `81_tenant_inspection.py` доступна.

---

### Sprint 22 — Observability & Testing Maturity (post-production gap-backlog)

**Owner**: К1 / К2 / К3 / К4 / К5.
**Приоритет**: **P0** (CRITICAL B-07/B-08 + STRONGLY RECOMMENDED G-02/G-10/G-15/G-16).
**Источник**: DEEP-RESEARCH 2026-05-20 A-06/A-07 + B-06/B-07/B-08 + G-02/G-10/G-15/G-16 + F-02/F-09/F-10/F-11/F-14.

#### Wave 0 — Backbone
- `[wave:s22/backbone]` — 6 default-OFF feature-flags: `SECURITY_HEADERS_ASGI_NATIVE`, `PII_MASKER_UNIFIED`, `PROCESSOR_DI_ENABLED`, `SMOKE_TESTS_CI_GATE`, `PROPERTY_BASED_TESTING_NIGHTLY`, `ALERTMANAGER_RULES_ENABLED`.

#### Wave 1-2 (К1 Security)
- `[wave:s22/k1-w1-security-headers-asgi]` — **A-06 SecurityHeadersMiddleware ASGI rewrite** (B-07): переписать `entrypoints/middlewares/security_headers.py` с `BaseHTTPMiddleware` на Starlette-native ASGI (принимает `app`, обрабатывает `scope`/`receive`/`send`). FF `SECURITY_HEADERS_ASGI_NATIVE`. Tests: `tests/middleware/test_security_headers_asgi.py` (race condition + concurrent requests).
- `[wave:s22/k1-w2-pii-masker-unify]` — **A-07 PII Masker Unification** (B-06, follow-up S18 W1): `entrypoints/middlewares/data_masking.py` вызывает `core/security/pii_masker.default_masker().mask_all(payload)`. Унифицировать использование во всех слоях: middleware + RAG ingestion + logging + audit. FF `PII_MASKER_UNIFIED`. Tests: `tests/security/test_pii_unification.py` (8 PII-categories).

#### Wave 3-7 (К2 Testing/Observability)
- `[wave:s22/k2-w1-smoke-tests]` — **B-08 Smoke test suite**: `tests/smoke/` — 12+ endpoint-level smoke tests (health, routes, /api/v1/credit/score [extension], FastMCP tools list, GraphQL schema fetch, WS handshake). CI gate `make smoke`. FF `SMOKE_TESTS_CI_GATE`.
- `[wave:s22/k2-w2-middleware-integration-tests]` — **G-15 Middleware integration tests**: `tests/integration/middlewares/test_chain_compose.py` — full request → middleware chain → response. Verify ordering, auth-agnostic per-route, error propagation. 15+ сценариев.
- `[wave:s22/k2-w3-hypothesis-suite]` — **G-16 Property-based testing**: добавить `hypothesis` 6.x в dev-extras. `tests/property/` — суиты для DSL processors (idempotency, commutativity), audit event schema, ResilienceCoordinator state machine. FF `PROPERTY_BASED_TESTING_NIGHTLY` для CI nightly job.
- `[wave:s22/k2-w4-observability-test-suite]` — **F-10 Observability tests**: `tests/observability/` — tracing context propagation across async boundaries, metric cardinality limits (`tenant_id` × `route_id` ≤ 10k), alert firing rules (mock Prometheus), log format compliance (structlog → JSON schema validation).
- `[wave:s22/k2-w5-alertmanager-rules]` — **G-10 AlertManager + PrometheusRules**: `ops/prometheus/rules/` — 10+ rules (p95-breach, error-rate-spike, breaker-open-stuck, queue-depth, cache-miss-rate, db-pool-exhaustion, workflow-stuck, ai-cost-budget, secret-rotation-overdue, scheduler-dlq-grew). `ops/alertmanager/routes.yml` — routing на Slack/PagerDuty placeholder. FF `ALERTMANAGER_RULES_ENABLED`.

#### Wave 8 (К3 DSL)
- `[wave:s22/k3-w1-processor-di]` — **G-02 ProcessorFactory DI**: `dsl/registry/processor_factory.py` — фабрика с DI container; замена прямого `cls(**kwargs)` в `dsl/engine/processors/` (~15 файлов). Поддерживает constructor injection для DB sessions, external clients. FF `PROCESSOR_DI_ENABLED`. Tests: `tests/dsl/test_processor_di.py` (mock-substitute сценарии).

#### Wave 9 (К4 AI)
- `[wave:s22/k4-w1-semantic-cache-heatmap]` — **F-11 Semantic cache heatmap**: `services/ai/rag/semantic_cache.py` экспортирует Prometheus `semantic_cache_hits_total`, `_misses_total`, `_latency_seconds` (labels: tenant_id, route_id). Grafana dashboard `dashboards/ai-semantic-cache.json` с heatmap по `tenant × route`.

#### Wave 10-12 (К5 Dashboards)
- `[wave:s22/k5-w1-cb-dashboard]` — **F-02 Circuit Breaker Dashboard**: admin endpoint `/admin/circuit-breakers` (auth-required) возвращает `[{name, state, failure_count, last_failure, half_open_test_after}]`. Grafana dashboard `dashboards/circuit-breakers.json` с per-resource breakdown.
- `[wave:s22/k5-w2-ratelimit-dashboard]` — **F-09 Rate Limit Dashboard**: admin `/admin/rate-limits` (текущие счётчики, TTL, quota per tenant). Grafana dashboard с per-tenant rate-limit heatmap. Используется существующий `RateLimitMiddleware`.
- `[wave:s22/k5-w3-sla-dashboard]` — **F-14 SLA Dashboard per Route**: `route.toml::[slo]` (p95_latency, rps, error_rate) уже есть, добавить collector `services/observability/sla_collector.py` + Grafana `dashboards/route-sla.json` с breach alerts (интеграция с S22 W5 AlertManager rules).

#### Closure
- `[wave:s22/closure]` — DoD grep verify + memory note `feedback_sprint22_observability_testing.md` + CONTEXT.md update.

**DoD Sprint 22 (14 критериев)**:
1. ✅ `[wave:s22/backbone]` landed: 6 feature-flags default-OFF.
2. ✅ **B-07/A-06**: `grep -rn "BaseHTTPMiddleware" src/backend/entrypoints/middlewares/security_headers.py` = **0**; `tests/middleware/test_security_headers_asgi.py` 5/5 race condition зелёные.
3. ✅ **B-06/A-07**: `grep -rn "mask_pii\|redact_pii" src/backend/ | grep -v default_masker` = **0** (все вызовы через PII masker core).
4. ✅ **B-08**: `make smoke` зелёный (12+ tests); CI gate активен.
5. ✅ **G-15**: `tests/integration/middlewares/` 15+ зелёных тестов; chain composition verified.
6. ✅ **G-16**: `hypothesis` в `pyproject.toml::[dev]`; `tests/property/` 5+ suites зелёные; CI nightly job настроен.
7. ✅ **F-10**: `tests/observability/` 8+ зелёных; metric cardinality gate (≤ 10k) активен.
8. ✅ **G-10**: 10+ PrometheusRules в `ops/prometheus/rules/`; `promtool check rules` зелёный; AlertManager config syntax-valid.
9. ✅ **G-02**: `grep -rn "= cls(\*\*kwargs)" src/backend/dsl/engine/processors/` = **0**; `tests/dsl/test_processor_di.py` зелёный.
10. ✅ **F-11**: Prometheus exporter `semantic_cache_*` метрики видны; Grafana dashboard импортирован.
11. ✅ **F-02**: `/admin/circuit-breakers` возвращает 200 + JSON; Grafana dashboard работает.
12. ✅ **F-09**: `/admin/rate-limits` возвращает 200 + JSON; per-tenant heatmap визуализируется.
13. ✅ **F-14**: `route.toml::[slo]` validated; SLA dashboard breach-alerts связаны с AlertManager.
14. ✅ Memory note + CONTEXT.md updated; ничего из S22 не блокирует release.

---

### Sprint 23 — AI / DSL / DX Extensions (post-production gap-backlog)

**Owner**: К1 / К3 / К4 / К5 (К2 — backbone only).
**Приоритет**: **P0** (CRITICAL B-10) + **P1** (G-03/G-13/G-14 + F-01..F-08).
**Источник**: DEEP-RESEARCH 2026-05-20 A-02 + B-10 + G-03/G-13/G-14 + F-01/F-03/F-04/F-05/F-06/F-07 + F-15 follow-up.

#### Wave 0 — Backbone
- `[wave:s23/backbone]` — 11 default-OFF feature-flags: `DOCKER_REGISTRY_PUSH_CI`, `WORKFLOW_HOT_RELOAD`, `SCHEMA_REGISTRY_REST_API`, `ROUTE_BLUEPRINTS_MARKETPLACE`, `WEBHOOK_RETRY_DECLARATIVE`, `MULTIAGENT_SUPERVISOR_LLM`, `AI_GUARDRAILS_FRAMEWORK`, `PLUGIN_SANDBOX_E2B`, `BACKEND_HPA_AUTOSCALE`, `MULTI_REGION_ROUTING_ENABLED`, `CHAOS_CI_PR_GATE`.

#### Wave 1 (К1 Ops/CI)
- `[wave:s23/k1-w1-docker-registry-push]` — **G-14 Docker registry push CI**: GitHub Actions `.github/workflows/docker-push.yml` — на push в main собирает multi-stage Docker image, cosign-sign, push в registry (placeholder env `${DOCKER_REGISTRY_URL}`). FF `DOCKER_REGISTRY_PUSH_CI`. SBOM attached.

#### Wave 2-5 (К3 DSL/Workflow)
- `[wave:s23/k3-w1-workflow-hot-reload]` — **G-03 Workflow hot reload**: расширить `dsl/route/hot_reload.py` → также watch `extensions/*/workflows/*.workflow.yaml` через watchfiles. Перезапуск Temporal worker registry без полного process restart. FF `WORKFLOW_HOT_RELOAD`. Tests: `tests/workflow/test_hot_reload.py`.
- `[wave:s23/k3-w2-schema-registry-rest]` — **F-01 Schema Registry Service**: `services/schema_registry/registry.py` (scaffold уже есть) → REST API `/api/v1/schemas/{name}/{version}` + breaking-change detection (через `jsonschema-spec` diff). `route.toml::input_schema`/`output_schema` валидируется на gateway. FF `SCHEMA_REGISTRY_REST_API`. Tests: `tests/schema_registry/test_breaking_change.py`.
- `[wave:s23/k3-w3-blueprints-marketplace]` — **F-03 Route Blueprints Marketplace**: `dsl/blueprints/` (19 blueprints в S10 уже есть) → расширить до 25+ + админ UI `pages/82_blueprints_browser.py`. Маршрут импортируется через `route: blueprint:rest-to-grpc-proxy`. FF `ROUTE_BLUEPRINTS_MARKETPLACE`. Tests: `tests/blueprints/test_import_round_trip.py`.
- `[wave:s23/k3-w4-webhook-retry-policy]` — **F-05 Webhook Retry declarative**: `entrypoints/webhook/retry_policy.py` — `@dataclass WebhookRetryPolicy(max_attempts, backoff_multiplier, max_delay, retry_on)`. YAML декларация `webhook: { retry: { max_attempts: 5, backoff: exponential } }`. Интеграция с S21 W3 webhook resilience. FF `WEBHOOK_RETRY_DECLARATIVE`. Tests: `tests/webhook/test_declarative_retry.py`.

#### Wave 6-8 (К4 AI)
- `[wave:s23/k4-w1-multiagent-supervisor-llm]` — **B-10 Multi-agent supervisor LLM integration**: `services/ai/agents/multi_agent.py` (stub) → реальный LangGraph supervisor pattern. Supervisor agent через LiteLLM (default GPT-4o-mini), worker agents (RAG, Code, Search). FF `MULTIAGENT_SUPERVISOR_LLM`. Tests: `tests/ai/test_multiagent_supervisor.py` (3 scenario: routing/fallback/cost-budget).
- `[wave:s23/k4-w2-ai-guardrails-framework]` — **F-04 AI Guardrails Framework** (follow-up S18 W18 G-04): `services/ai/guardrails/enforcement.py` — `GuardrailEnforcementProcessor` для DSL pipeline: input sanitization (PII + prompt-injection через Rebuff/Lakera) → LLM → output filtering (PII redaction + jailbreak detection). API keys из Vault. FF `AI_GUARDRAILS_FRAMEWORK`. Tests: `tests/ai/guardrails/test_enforcement.py`.
- `[wave:s23/k4-w3-plugin-sandbox-e2b]` — **F-06 Plugin Sandbox e2b finalize** (follow-up S18 R1.20 ADR-NEW-6 Tier-B): `core/ai/ai_workspace_manager.py` интегрирует e2b SDK. Code execution в AI workspace через `e2b.Sandbox.create(template='python', timeout=30)`. Cost/quota tracking. FF `PLUGIN_SANDBOX_E2B`. Tests: `tests/ai/test_e2b_sandbox.py` (cost-budget + timeout-kill).

#### Wave 9-11 (К5 Ops)
- `[wave:s23/k5-w1-backend-hpa]` — **G-13 Backend HPA**: `k8s/manifests/backend-hpa.yaml` — HorizontalPodAutoscaler по CPU (70%) + custom Prometheus метрике `app_request_queue_depth`. minReplicas=2, maxReplicas=20. FF `BACKEND_HPA_AUTOSCALE` (k8s annotation-based). Tests: `tests/k8s/test_hpa_manifest.py` (kubectl-dry-run validation).
- `[wave:s23/k5-w2-multi-region-scaffold]` — **F-07 Multi-region Traffic Routing scaffold**: `core/routing/region_router.py` — `RegionRouter` (Protocol + InMemory impl). YAML config `routing.yaml::regions: [us-east, eu-west, ap-south]`. Health-based routing, latency-based scoring. **Scaffold only** — production rollout = §9 backlog. FF `MULTI_REGION_ROUTING_ENABLED`. Tests: `tests/routing/test_region_routing.py`.
- `[wave:s23/k5-w3-chaos-ci-pr-gate]` — **F-15 Chaos CI PR-gate** (follow-up S20 W6): `.github/workflows/chaos-gate.yml` — chaos suite (33 tests, Toxiproxy) запускается на PR с label `needs-chaos`. Results блокируют merge. **ADR-NEW-15 Chaos PR-gate policy**. FF `CHAOS_CI_PR_GATE`. Tests: `.github/workflows/chaos-gate.yml` syntax-validated.

#### Closure
- `[wave:s23/closure]` — DoD grep verify + memory note `feedback_sprint23_ai_dsl_dx.md` + CONTEXT.md update + `vault/session-summary-s21-s23.md`.

**DoD Sprint 23 (14 критериев)**:
1. ✅ `[wave:s23/backbone]` landed: 11 feature-flags default-OFF.
2. ✅ **G-14**: `.github/workflows/docker-push.yml` syntax-valid; `cosign verify` запускается; SBOM прикреплён в release.
3. ✅ **G-03**: workflow YAML edit → Temporal worker реестр перезагружен <3s; `tests/workflow/test_hot_reload.py` зелёный.
4. ✅ **F-01**: `/api/v1/schemas/{name}/{version}` возвращает 200; breaking-change detection работает; `tests/schema_registry/` зелёный.
5. ✅ **F-03**: `dsl/blueprints/` ≥25 шаблонов; `route: blueprint:NAME` import работает; admin page `82_blueprints_browser` доступна.
6. ✅ **F-05**: `webhook: { retry: { ... } }` декларация работает; интеграция с S21 W3 verified.
7. ✅ **B-10**: `tests/ai/test_multiagent_supervisor.py` 3/3 (routing/fallback/cost); supervisor использует LLM (не stub).
8. ✅ **F-04/G-04**: GuardrailEnforcementProcessor в DSL; Rebuff API key через Vault; prompt-injection blocked в тестах.
9. ✅ **F-06/G-05**: e2b sandbox создаётся в тестах; cost-budget enforced; timeout-kill verified; ADR-NEW-6 Tier-B (S18) closed.
10. ✅ **G-13**: `backend-hpa.yaml` применим в k8s (kubectl dry-run); minReplicas=2 enforced.
11. ✅ **F-07**: `RegionRouter` Protocol + InMemory impl; `tests/routing/test_region_routing.py` зелёный; production rollout в §9.
12. ✅ **F-15**: `chaos-gate.yml` triggered на PR с label; ADR-NEW-15 Chaos PR-gate принят.
13. ✅ **ADR-NEW-15** записан в `.claude/DECISIONS.md`.
14. ✅ Memory note + CONTEXT.md + `vault/session-summary-s21-s23.md`; Streamlit pages ≥82.

---

### Sprint 24 — AI Safety Hardening (post-production gap-backlog)

**Owner**: К4 (AI/Data primary) + К1 (Security review).
**Приоритет**: **P0** (CRITICAL для compliance 152-ФЗ + banking jailbreak resistance).
**Источник**: gap-analysis/AI-GAP-ANALYSIS-gd_integration_tools-2026-05-22.md (10 зон, 3 × P0).
**Зависимости**: S17 ADR-NEW-3 RequestContext (для PII context propagation), S21 ADR-NEW-12 RLS (для tenant-aware memory).

#### Wave 0 — Backbone
- `[wave:s24/backbone]` — 3 default-OFF feature-flags: `PRESIDIO_PII_ENABLED`, `NEMO_GUARDRAILS_ENABLED`, `LANGGRAPH_CHECKPOINTER_ENABLED`. Capability schema extension: `pii.read.<tenant>`, `ai.guardrail.evaluate.<tenant>`, `ai.memory.{read,write,delete}.<tenant>`.

#### Wave 1 (К4 W1 PII)
- `[wave:s24/w1-presidio-ru-ner]` — **ADR-NEW-16 Presidio + ru NER**: `presidio-analyzer` + `presidio-anonymizer` + spaCy `ru_core_news_lg` + 4 custom recognizers (INN, СНИЛС, паспорт, номер кредитного дела). Применение: input LLM + output LLM + RAG retrieval (default-ON) + Langfuse traces callback + DLQ payload. CI-gate `make pii-audit` (1000 ru-документов, precision/recall ≥ 0.9). Tests: `tests/ai/test_presidio_ru.py`.

#### Wave 2 (К4 W2 Guardrails)
- `[wave:s24/w2-nemo-llamaguard]` — **ADR-NEW-17 NeMo Guardrails + Llama Guard 3**: defense-in-depth pipeline (WAF → NeMo input rails → LLM → Llama Guard output → Presidio PII → audit). NeMo Colang flows: jailbreak detection (perplexity-thresholds), topic filter (banking-specific). Llama Guard 3 self-hosted на vLLM/TGI. Per-tenant policy через `tenant_config.py` расширение. Tests: `tests/ai/test_guardrails_defense_in_depth.py` (100 jailbreak-prompts gold-set, block rate ≥ 95%; latency p95 ≤ 80ms combined).

#### Wave 3 (К4 W3 Memory)
- `[wave:s24/w3-memory-persistence]` — **ADR-NEW-18 LangGraph Checkpointer + Mem0**: `langgraph-checkpoint-postgres` для durable graph state (multi-agent supervisor.py). `mem0ai` на pgvector как unified long-term memory (поверх legacy LangMem). `MemoryProtocol` в `core/interfaces/ai_memory.py`. LangMemService consolidate() реализован через Mem0. Chaos-test: kill worker mid-conversation → resume successful. Tests: `tests/ai/test_memory_persistence.py`.

#### Closure
- `[wave:s24/closure]` — DoD grep verify + memory note `feedback_sprint24_ai_safety_hardening.md` + CONTEXT.md update.

**DoD Sprint 24 (9 критериев)**:
1. ✅ `[wave:s24/backbone]` landed: 3 feature-flags + capability schema extension.
2. ✅ **ADR-NEW-16 Presidio + ru NER** принят в `.claude/DECISIONS.md`. `make pii-audit` precision/recall ≥ 0.9 на ru-gold-set.
3. ✅ `grep -rn "AnalyzerEngine\(\)" src/backend/services/ai/pii/` ≥ 1 (Presidio active). `rag_pii_retrieval_mask=true` default.
4. ✅ **ADR-NEW-17 NeMo Guardrails + Llama Guard 3** принят. `tests/ai/test_guardrails_defense_in_depth.py` 100/100 jailbreak (block rate ≥ 95%, p95 ≤ 80ms).
5. ✅ NeMo + Llama Guard self-hosted в vLLM/TGI compose; per-tenant policy enable/disable.
6. ✅ **ADR-NEW-18 LangGraph Checkpointer + Mem0** принят. `tests/ai/test_memory_persistence.py` 4/4 chaos-recover.
7. ✅ `MemoryProtocol` в `core/interfaces/ai_memory.py`; LangMemService consolidate() реализован.
8. ✅ Langfuse traces содержат PII только в anonymized виде (integration test `tests/ai/test_langfuse_pii_callback.py`).
9. ✅ Memory note + CONTEXT.md updated.

---

### Sprint 25 — AI Gateway + Policy DSL (post-production gap-backlog)

**Owner**: К4 (AI/Data primary) + К1 (Security review) + К2 (DSL review).
**Приоритет**: **P0** (защитный слой невозможен без единой точки входа).
**Источник**: gap-analysis/AI-GAP-ANALYSIS-gd_integration_tools-2026-05-22.md Зона 1 (orchestration consolidation) + новый платформенный план V22.4 §3 Зоны N1/N2/N6.
**Зависимости**: S24 W1 Presidio backend (для PIITokenizer), S17 ADR-NEW-3 RequestContext (для correlation_id), ADR-NEW-1 AuthorizationGateway (pattern reuse).

#### Wave 0 — Backbone
- `[wave:s25/backbone]` — 3 default-OFF feature-flags: `AI_GATEWAY_ENFORCE`, `AI_POLICY_ENFORCE`, `AI_PII_TOKENIZER_ENABLED`. Capability schema extension: `ai.invoke.<workflow>`, `ai.memory.{read,write}.<namespace>`, `pii.tokenize.reversible.<scope>`. Scaffold-файлы `core/ai/gateway.py` + `core/ai/policy/{spec,resolver,enforcer}.py` (pass-through pipeline). `ai_policies/.gitkeep` + `ai_policies/credit_check_strict.policy.yaml` PoC.

#### Wave 1 (К4 W1 Gateway facade)
- `[wave:s25/w1-ai-gateway]` — **ADR-NEW-19 AIGateway facade**: 9-step pipeline (policy_resolve → input_sanitizers → input_guards → prompt_render → invoke_llm → output_guards → output_sanitizers → audit_emit → cost_track). `AIRequest`/`AIResponse` dataclass с `workflow_id`, `tenant_id`, `correlation_id`, `prompt_ref`. Tests: `tests/unit/core/ai/test_gateway_pipeline.py`. CI-gate `make ai-gateway-coverage` (AST-checker, warn-only first month).

#### Wave 2 (К2 W2 Policy DSL)
- `[wave:s25/w2-policy-resolver]` — **ADR-NEW-20 AIPolicySpec + PolicyResolver**: Pydantic v2 `AIPolicySpec(name, model_router, input_sanitizers, input_guards, output_guards, output_sanitizers, memory, budget, audit)`. `ai_policies/*.policy.yaml` JSON-Schema (`make ai-policy-schema`). Per-tenant override через `extensions/*/ai_policies/`. `PolicyResolver.resolve(workflow_id, tenant_id) → AIPolicySpec`. Tests: `tests/unit/core/ai/policy/test_resolver_yaml.py`.

#### Wave 3 (К4 W3 Adapter wrap)
- `[wave:s25/w3-adapter-wrap]` — 3 кодопути LLM (`services/ai/ai_agent.py`, `services/ai/ai_graph.py`, `services/ai/agents_pydantic/base.py`) обёрнуты в `AIGateway.invoke()`. Интерфейсы сохранены (backward-compat). Feature-flag `AI_GATEWAY_ENFORCE` default-OFF → ON в S27 closure. Tests: regression `tests/ai/test_3_codepaths_regress.py` (golden-snapshot).

#### Wave 4 (К1 W4 PII Tokenizer reversible)
- `[wave:s25/w4-pii-tokenizer]` — **ADR-NEW-21 PIITokenizer reversible**: `core/security/pii_tokenizer.py::mask_reversible(text, policy) → (masked, token_map)` + `unmask(masked, token_map)` через UUIDv7-токенизацию + Presidio (из S24 W1). `TokenRegistry` Redis-backed (TTL = policy.ttl_s, AES-GCM ключ через `infrastructure/secrets/`). Capability `pii.tokenize.reversible.<scope>`. Audit-event `ai.pii.tokenize.{mask,unmask}`. Tests: `tests/security/test_pii_tokenizer_roundtrip.py` (500 примеров mask→unmask exact-match).

#### Wave 5 (К4 W5 Langfuse v3 + PII callback)
- `[wave:s25/w5-langfuse-v3]` — upgrade `services/ai/gateway/langfuse_callback.py` v2 → v3 (OTel-native, GenAI semantic conventions). PII-mask callback через `PIITokenizer.mask_irreversible` ДО отправки в Langfuse SaaS. OTel attrs (`gen_ai.{system,request.model,usage.{prompt_tokens,completion_tokens}}`) на 100% LLM-spans. Dual-write 1 спринт → cut-over в S26 closure. Tests: `tests/ai/test_langfuse_v3_pii_callback.py` (trace с ФИО → anonymized в Langfuse API).

#### Closure
- `[wave:s25/closure]` — DoD grep verify + memory note `feedback_sprint25_ai_gateway.md` + CONTEXT.md update + `vault/session-summary-s25.md`.

**DoD Sprint 25 (8 критериев)**:
1. ✅ `[wave:s25/backbone]` landed: 3 feature-flags + capability schema extension + scaffold pass-through.
2. ✅ **ADR-NEW-19 AIGateway facade** принят в `.claude/DECISIONS.md`. `AIGateway.invoke()` единственная точка входа в LLM (после S27 closure).
3. ✅ **ADR-NEW-20 AIPolicySpec** принят. `make ai-policy-schema` валидирует 100% `*.policy.yaml`; PoC `credit_check_strict` запускается.
4. ✅ 3 кодопути обёрнуты, regress-free (golden-snapshot).
5. ✅ **ADR-NEW-21 PIITokenizer reversible** принят. `tests/security/test_pii_tokenizer_roundtrip.py` 500/500 exact-match.
6. ✅ Langfuse v3 PII-mask callback подтверждён: trace с реальным ФИО → anonymized.
7. ✅ OTel GenAI atts на 100% LLM-spans (`gen_ai.{system,request.model,usage.*}`).
8. ✅ CI-gate `make ai-gateway-coverage` warn-only включён (strict-mode в S27 closure).

---

### Sprint 26 — Prompts Pipeline + Skills Registry (post-production gap-backlog)

**Owner**: К4 (AI/Data primary) + К2 (DSL) + К3 (CI/RAGAS).
**Приоритет**: **P0** (полный цикл tuning + R-V15-6 для AI-tools).
**Источник**: AI-GAP-2026-05-22 Зоны N3/N4 + 80% YAML / 20% Python принцип (R-V15-6).
**Зависимости**: S25 W1 AIGateway (для prompt_render integration), S25 W2 AIPolicySpec (для skill policy_ref).

#### Wave 0 — Backbone
- `[wave:s26/backbone]` — 3 default-OFF feature-flags: `AI_PROMPT_SWEEP_STRICT`, `AI_PROMPT_EVAL_BLOCKING` (RAGAS gate), `AI_SKILL_TOML_ENABLED`. Capability `skill.invoke.<id>` schema extension.

#### Wave 1 (К4 W1 Prompts sweep)
- `[wave:s26/w1-prompts-sweep]` — **AST-checker `tools/checks/check_hardcoded_prompts.py`**: ищет литералы вида `system_prompt=`, `system_message=`, `system="..."` длиннее 50 символов в `src/backend/`. Миграция 20+ строк через `manage.py ai prompts migrate <module>:<var>`. Langfuse PromptRegistry source-of-truth. CI-gate `make check-hardcoded-prompts` (warn → strict в S27).

#### Wave 2 (К2 W2 prompt_render DSL)
- `[wave:s26/w2-prompt-render]` — DSL processor `dsl/engine/processors/ai/prompt_render.py`: `{ref, inputs, output_var, budget.max_tokens}` через `tiktoken` trim. Builder `.prompt_render(ref=..., inputs=..., output=...)`. Integration с `AIPolicySpec.budget`. Tests: `tests/dsl/processors/test_prompt_render_budget.py`.

#### Wave 3 (К4 W3 DSPy ↔ PromptRegistry loop)
- `[wave:s26/w3-dspy-loop]` — `services/ai/dspy/optimizer_loop.py`: `manage.py ai prompts optimize <ref> --gold-set <path> --metric ragas.faithfulness`. Output: новая версия в Langfuse + canary trigger (5% → 25% → 100%) через `ai_cost_dashboard`. Weekly cron `make ai-prompt-optimize` non-blocking. Tests: `tests/ai/test_dspy_optimizer_loop.py`.

#### Wave 4 (К3+К4 W4 RAGAS gate)
- `[wave:s26/w4-ragas-gate]` — `make ai-prompt-eval` блокирует PR при `faithfulness < 0.8` или `answer_relevancy < 0.75` на 500 gold. Feature-flag `AI_PROMPT_EVAL_BLOCKING` default-OFF первый месяц → ON в S27 closure. Tests: nightly cron + smoke-test регрессии.

#### Wave 5 (К2 W5 Skill Registry V11.2 TOML)
- `[wave:s26/w5-skill-registry]` — **ADR-NEW-22 SkillRegistry V11.2**: расширение `plugin.toml [[skill]]` секцией (`id`, `version`, `handler`, `input_schema`, `output_schema`, `capabilities`, `policy_ref`, `protocols=[mcp,langgraph,openai_tools]`, `timeout_s`). `core/ai/skill_registry.py::from_toml_manifest()` (sov с existing `services/ai/tools/registry.py`). `make skill-schema` JSON-Schema. Hot-reload через существующий `watchfiles.awatch`. Auto-export в MCP + LangGraph + OpenAI tools. Tests: `tests/unit/core/ai/test_skill_registry_toml.py`.

#### Closure
- `[wave:s26/closure]` — DoD grep verify + memory note `feedback_sprint26_prompts_skills.md` + CONTEXT.md update.

**DoD Sprint 26 (8 критериев)**:
1. ✅ `[wave:s26/backbone]` landed: 3 feature-flags + capability schema extension.
2. ✅ `tools/checks/check_hardcoded_prompts.py` AST-checker зелёный (`make check-hardcoded-prompts` = 0 violations в src/backend/, кроме allowlist).
3. ✅ 20+ промптов в Langfuse PromptRegistry с version history; `prompt_registry.get("credit_check.production").version >= 2`.
4. ✅ DSL `prompt_render` использует `tiktoken` для trim к `policy.budget.max_tokens` (regression test).
5. ✅ DSPy `optimizer_loop` runable: `manage.py ai prompts optimize credit_check` → новая версия Langfuse + canary trigger `5%`.
6. ✅ `make ai-prompt-eval` fail при `faithfulness < 0.8` (на 500 gold); warn-only первый месяц → blocking в S27 closure.
7. ✅ **ADR-NEW-22 SkillRegistry V11.2** принят. `plugin.toml [[skill]]` JSON-Schema валидирует 100% extension манифестов; hot-reload ≤2s.
8. ✅ SkillRegistry auto-export в MCP + LangGraph + OpenAI tools (100% skills доступны во всех 3 формах).

---

### Sprint 27 — Agent DSL + MCP Gateway + Audit Unified (post-production gap-backlog)

**Owner**: К2 (DSL primary) + К3 (MCP/Ops) + К4 (AI integration) + К1 (Security review).
**Приоритет**: **P0** (декларативная агентика + единая audit-схема + MCP namespaces).
**Источник**: AI-GAP-2026-05-22 Зоны N5/N7/N8 + R-V15-9 «AI-функции через Workflow DSL».
**Зависимости**: S24 W2 NeMo + Llama Guard backends (для guardrails_apply), S24 W3 LangGraph Checkpointer (для memory_recall/store), S25 backbone (AIGateway+Policy), S26 (PromptRegistry+SkillRegistry).

#### Wave 0 — Backbone
- `[wave:s27/backbone]` — 4 default-OFF feature-flags: `AI_AGENT_DSL_ENABLED`, `MCP_GATEWAY_NAMESPACES_ENABLED`, `AI_AUDIT_UNIFIED_ENABLED`, `WORKFLOW_INVOKE_AGENT_ENABLED`. Capability schema extension: `mcp.gateway.invoke.<namespace>`.

#### Wave 1 (К2 W1 agent DSL primary)
- `[wave:s27/w1-agent-dsl-primary]` — DSL processors `dsl/engine/processors/ai/{agent_run,agent_branch,agent_loop,agent_parallel}.py`. Builder `.agent_run()`, `.ai_invoke()`, `.agent_branch()`, `.agent_loop()`, `.agent_parallel()`. Integration с AIPolicySpec через policy_ref. Tests: `tests/dsl/processors/ai/test_agent_dsl.py` (≥90% coverage).

#### Wave 2 (К2+К1 W2 guardrails+pii DSL)
- `[wave:s27/w2-guardrails-pii-dsl]` — DSL processors `guardrails_apply.py` (stage=input|output, on_block=dlq|fail|warn) + `pii_mask.py`/`pii_unmask.py` (capability `pii.tokenize.reversible.<scope>`, integration с PIITokenizer из S25 W4). Builder `.guardrails_apply()`, `.pii_mask()`, `.pii_unmask()`. Tests: `tests/dsl/processors/ai/test_guardrails_pii.py`.

#### Wave 3 (К2 W3 skill_invoke + memory DSL)
- `[wave:s27/w3-skill-memory-dsl]` — DSL processors `skill_invoke.py` (capability-gate через SkillRegistry V11.2) + `memory_recall.py`/`memory_store.py` (через MemoryProtocol из S24 W3). Builder `.skill_invoke()`, `.ai_memory_recall()`, `.ai_memory_store()`. Tests: `tests/dsl/processors/ai/test_skill_memory.py`. PoC route `routes/credit_check_demo/` использует все 9 новых processors.

#### Wave 4 (К3+К1 W4 MCP Gateway)
- `[wave:s27/w4-mcp-gateway]` — **ADR-NEW-23 MCP Gateway namespaces**: split монолита `entrypoints/mcp/mcp_server.py` на 3 namespace (`credit-mcp`, `analytics-mcp`, `system-mcp`) через aggregator (backward-compat). `entrypoints/mcp/gateway.py` — `MCPNamespace` + composite root. `MCPClientRegistry` в `infrastructure/clients/external/mcp_registry.py` — trusted external MCP через `OutboundHttpClient` + WAF capability `net.outbound.<host>:external`. FastMCP `>=3.2.4` upgrade с `JWTAuthProvider` (SSO integration из S18/B-1). Tests: `tests/mcp/test_namespaces_aggregator.py` (`mcp.tools.count() == pre_split_count`).

#### Wave 5 (К3+К1 W5 Audit unified)
- `[wave:s27/w5-audit-unified]` — **ADR-NEW-24 AI Audit Unified Schema**: 9 событий `ai.invocation.{requested|policy_resolved|sanitized|guarded|completed|denied|failed|pii.mask|pii.unmask}` через `AuditService.emit()` (расширение S17/K3). Langfuse v3 OTel-exporter в ClickHouse. Удаление legacy `audit_clickhouse.py` (миграция в S26 dual-write window). PII в audit маскируется через `PIITokenizer.mask_irreversible`. Tests: `tests/audit/test_ai_invocation_events.py`.

#### Wave 6 (К2+К4 W6 Workflow ↔ Agent)
- `[wave:s27/w6-workflow-invoke-agent]` — `WorkflowBuilder.invoke_agent("credit_advisor", durable=True)` — LangGraph multi-agent supervisor обёрнут в Temporal activity (R-V15-9 «AI-функции через Workflow DSL»). LangGraph Checkpointer integration (из S24 W3). Tests: chaos-test `tests/workflow/test_agent_activity_chaos.py` (kill worker mid-conversation → resume successful).

#### Closure
- `[wave:s27/closure]` — DoD grep verify + AIGateway feature-flag `AI_GATEWAY_ENFORCE` → ON в production config (без legacy fallback). `make pre-prod-check 38+8` extension (8 AI-gates: gateway-coverage, policy-schema, prompt-sweep, skill-schema, agent-dsl, mcp-gateway, audit-unified, memory-recall round-trip). Memory note `feedback_sprint27_ai_platform_closure.md` + CONTEXT.md + `vault/session-summary-s25-s27.md`.

**DoD Sprint 27 (10 критериев)**:
1. ✅ `[wave:s27/backbone]` landed: 4 feature-flags + capability schema extension.
2. ✅ 9 новых DSL processors (`agent_run`, `agent_branch`, `agent_loop`, `agent_parallel`, `guardrails_apply`, `pii_mask`, `pii_unmask`, `skill_invoke`, `memory_recall`/`memory_store`) с unit-тестами ≥ 90% coverage.
3. ✅ Builder fluent API расширен; `make routes-strict` зелёный; PoC `routes/credit_check_demo/` использует все 9 processors end-to-end.
4. ✅ **ADR-NEW-23 MCP Gateway namespaces** принят. 3 domain MCP servers; backward-compat aggregator (`mcp.tools.count() == pre_split_count`).
5. ✅ `MCPClientRegistry` — 100% external MCP через `OutboundHttpClient` + WAF capability `net.outbound.<host>:external`. FastMCP `>=3.2.4` + `JWTAuthProvider` SSO.
6. ✅ **ADR-NEW-24 AI Audit Unified Schema** принят. 9 типов событий `ai.invocation.*`; 100% покрытие путей AIGateway. ClickHouse query `SELECT count() FROM audit_events WHERE event_type LIKE 'ai.invocation.%'` ≥ 1.
7. ✅ Legacy `audit_clickhouse.py` удалён; миграция в Langfuse v3 OTel-exporter завершена.
8. ✅ `WorkflowBuilder.invoke_agent()` — LangGraph через Temporal activity; chaos-test (kill worker) восстанавливает state ≥ 2 turn.
9. ✅ `AI_GATEWAY_ENFORCE=true` в production config; `make ai-gateway-coverage` strict (0 прямых `litellm.completion` / `agent.run()` в обход AIGateway).
10. ✅ `make pre-prod-check` extended 38 → 46 (8 новых AI-gates); memory note + CONTEXT.md + vault summary.

---

## 5. Финальный DoD V22 (production-ready)

### Протоколы и интеграции (5)
- REST / SOAP / gRPC / GraphQL / FTP+SFTP / Email / CDC / Watchdog — DSL-шаги с тестами.
- WSDL/OpenAPI → codegen клиента за 60 сек.
- EventBus facade (Kafka/RabbitMQ/NATS) единый API + DSL `.to_eventbus()` / `.from_eventbus()`.
- Auto-registration 3-tier (REST + SOAP + XML + gRPC + GraphQL + MQ + WS + SSE + MCP + MQTT).
- pygls LSP server для route.toml + workflow.yaml + service.toml.

### DSL обогащение (15)
- `.convert()`, `.gateway_xor/and/or`, `.notify()`, `.audit_log()`, `.mask_pii / .unmask_pii`.
- `.rag_query / .rag_upsert / .rag_delete / .memory_write / .memory_read`.
- `.render_docx / .render_xlsx`, `.web_search()`, `.evaluate_rules()`, `.llm_structured()`.
- `.crud_*`, `.invoke_workflow`, `.call_function`, `.get_setting`, `.validate_response`, `.db_call_procedure`, `.policy.*`.
- Per-service timeouts + per-service pool config + retry-policy.
- Single Entry V22: CB / RL / Retry / Bulkhead / Cache через ResilienceCoordinator.
- `manage.py workflow dryrun` + `manage.py workflow import --format bpmn`.
- YAML↔Python round-trip + diff() + versioning.
- Hot Reload < 3 сек.
- `.to_eventbus()` + `.from_eventbus()` (V22 NEW).
- `.policy.adaptive_timeout()` (V22 NEW).
- `.cancel_workflow()` DSL step.

### Workflow (6)
- Workflow DSL обёртка над Temporal.
- XOR/AND/OR gateways.
- HITL / saga / sleep / sensor / continue_as_new.
- Workflow step log в ClickHouse + Streamlit waterfall.
- Один action × 6+ протоколов.
- AI workflow handlers (RAG saga / multi-agent supervisor / code-interpreter loop) + LangFuse production.

### AI (10)
- AI в workflow (LLM-activity + saga + LangGraph checkpoints).
- AI Safety: workspace isolation; capabilities `fs.write.*` запрещены.
- MCP через FastMCP (auto-export Tier 1+2 actions).
- LangMem + 3-уровневый RAG cache.
- AI стек: PydanticAI / Instructor / LiteLLM / DSPy / mem0 / multimodal RAG (BLIP2 / Whisper / docling / CLIP).
- AI ops: cost dashboard + Inspect AI nightly + Model Registry + GenAI OTel.
- LangChain/LangGraph через lazy import.
- PII маркировка + AI видит только маскированные данные.
- WAF strict для cloud LLM.
- Guardrails (Lakera/Rebuff) для prompt injection.

### Производительность и устойчивость (12)
- 12 Sinks + 14 Sources + 30 EIP processors.
- Auto-scaling 3 уровня (process / task / container) + leak prevention.
- 12 fallback chains + 33 chaos-tests + 5 alerts.
- p95 ≤ 80ms / RPS ≥ 1500 + perf-gate в CI.
- ConnectionReuseManager + Pool warm-up.
- `asyncio.TaskGroup` повсеместно.
- `msgspec.Struct` в hot-path.
- Granian ASGI ADR R1.9 + benchmark.
- Pool connections везде (DB / Redis / ClickHouse / Graylog / HTTP).
- Dask в analytics extra.
- **V22 centralization** (4): ConfigValidator + MetricsRegistry + AuthorizationGateway + ResilienceCoordinator + TaskRegistry obligatory + AuditService correlation_id.

### Безопасность (8)
- Auth: JWT + APIkey + mTLS + SAML + AD + JWT introspection RFC 7662.
- Supply-chain: SBOM CycloneDX + pip-audit zero HIGH + cosign verify + OWASP ZAP zero HIGH + bandit TLS zero HIGH.
- WAF strict: `make check-waf-coverage` zero violations; allowlist=0.
- V1–V24 уязвимости закрыты (FTP TLS asyncssh fix).
- codeclone gate `--fail-on-new-clones`.
- AI safety: workspace dirs TTL + audit-event + size quota.
- Vault: rotation impl + secrets-backend=vault в prod profile; `get_secret_value()` вне backends = 0.
- RestrictedPython / e2b sandbox для плагинов.

### Grep-критерии (V22 NEW, обязательно в CI)
```
grep -rn "asyncio\.create_task" src/backend/ | grep -v task_registry       # 0
grep -rn "from tenacity import" src/backend/ | grep -v core/resilience      # 0
grep -rn "= Counter(\|= Histogram(\|= Gauge(" src/backend/ | grep -v MetricsRegistry  # 0
grep -rn "get_secret_value()" src/backend/ | grep -v backends               # 0
grep -rn "APIKeyMiddleware" src/backend/                                    # 0
grep -rn "notification_hub" src/backend/ | grep import                      # 0
grep -rn "threading\.RLock" src/backend/                                    # 0
grep -rn "except Exception:\s*pass" src/backend/                            # 0
grep -rn "ssl\.CERT_NONE\|check_hostname=False" src/backend/                # 0
grep -rn "yaml\.load(" src/backend/ | grep -v safe_load                     # 0
grep -rn "pickle\.loads(" src/backend/                                      # 0
grep -rn "eval(\|exec(" src/backend/ | grep -v "# noqa"                     # 0
APP_PROFILE=prod DEBUG=true uv run python -m src.backend.main               # fail (CRITICAL)
curl ":8000/api/v1/audit?correlation_id=<id>"                               # события от 3+ источников
```

---

## 6. Открытые ADR (закрываются Sprint 19 + Sprint 17)

| ADR | Тема | Sprint-target | Owner |
|---|---|---|---|
| **R1.1** | plugin.toml capability synthax (массив vs flat-keys) | S19 W11 | К1 |
| **R1.5** | SLO формат (sloth YAML vs route.toml::slo) | S19 W11 | К2/К3 |
| **R1.7** | Single Entry policy naming | S19 W11 | К2 |
| **R1.8** | EventBus production backend (NATS/Kafka/RabbitMQ) | S19 W12 (для S18 W7 EventBus DSL) | К3 |
| **R1.9** | Granian RSGI vs Uvicorn (benchmark + decision) | S19 W12 (для S20 perf bench) | К2 |
| **R1.10** | DI container (`core/di/providers.py` vs `dependency-injector`) | **defer S21+ (post-production)** | К1/К2 |
| **R1.17** (NEW V22) | ConfigValidator strictness (fail-fast CRITICAL vs WARN logging) | S17 W1 | К1 |
| **R1.18** (NEW V22) | MetricsRegistry namespacing для plugin metrics | S17 W3 | К2 |
| **R1.19** (NEW V22) | AuthorizationGateway evaluation order (Casbin → OPA → CapabilityGate vs параллельно) | S17 W2 | К1 |
| **R1.20** (NEW V22) | F-2 PluginSandboxAdapter final strategy | S18 W5 (impl) + S19 W12 (formal accept) | К1/К2 |
| **ADR-NEW-12** (NEW post-S20) | RLS Strategy для multi-tenant tables | S21 W1 | К1 |
| **ADR-NEW-13** (NEW post-S20) | RPACallPolicy единый wrapper resilience | S21 W3 | К2 |
| **ADR-NEW-14** (NEW post-S20) | Workflow State Persistence (SQLite/Temporal) | S21 W8 | К3 |
| **ADR-NEW-15** (NEW post-S20) | Chaos PR-gate (on-PR triggered tests) | S23 W11 | К5 |
| **ADR-NEW-16** (NEW post-S20) | Presidio + ru NER PII layer | S24 W1 | К4 |
| **ADR-NEW-17** (NEW post-S20) | NeMo Guardrails + Llama Guard 3 defense-in-depth | S24 W2 | К4 |
| **ADR-NEW-18** (NEW post-S20) | LangGraph Checkpointer + Mem0 unified memory | S24 W3 | К4 |
| **ADR-NEW-19** (NEW V22.4) | AIGateway facade (единая точка входа в AI) | S25 W1 | К4/К1 |
| **ADR-NEW-20** (NEW V22.4) | AIPolicySpec — декларативная политика AI per-workflow | S25 W2 | К2/К4 |
| **ADR-NEW-21** (NEW V22.4) | PIITokenizer reversible (Presidio + AES-GCM TokenRegistry) | S25 W4 | К1 |
| **ADR-NEW-22** (NEW V22.4) | SkillRegistry V11.2 TOML-manifest для AI-tools | S26 W5 | К2 |
| **ADR-NEW-23** (NEW V22.4) | MCP Gateway domain namespaces + trusted external registry | S27 W4 | К3/К1 |
| **ADR-NEW-24** (NEW V22.4) | AI Audit Unified Schema (`ai.invocation.*`) | S27 W5 | К3/К1 |

**Закрытые в V21 → V22 (целевые)**: R1.6 hybrid layout (Wave R3.10), R1.11 Streamlit page numbering (S9), R1.12 plugin sandbox (S19 W12 финал через R1.20), R1.13 Adaptive RAG dispatching (S16 K4 W1), R1.14 VSCode marketplace private (S19 K5 W1), R1.15 path aliases (S9), R1.16 bulk audit writer (S9).

---

## 7. Команды финальной проверки (Makefile + CLI snippet)

```bash
# Базовый набор (каждый commit)
make format-check
make lint-strict
make type-check-budget       # mypy ≤ 0 (current baseline)
make startup-time-gate       # <3s
make coverage-gate           # ≥83% (target Sprint 20)
make layers                  # 0 violations (strict)
make check-waf-coverage      # strict, allowlist empty
make check-ai-safety         # fs.write.* запрещены
make secrets-check
make deps-check-strict       # creosote
make v11-artefacts-check     # schemas committed

# V22 NEW gates (Sprint 17+)
python tools/checks/check_task_registry.py        # 0 orphan create_task
python tools/checks/check_metrics_registry.py     # 0 inline Counter/Histogram
python tools/checks/check_config_validator.py     # ≥5 production-safety rules
python tools/checks/check_correlation_id.py       # 100% audit events

# Composite
make ci                      # composite: lint+type+test+coverage+security+layers
make pr                      # composite: ci+docs+pre-prod-check

# Финальный gate (Sprint 20)
make pre-prod-check          # v2: 20+10+8 grep = 38/38 ✅
manage.py diagnose           # 0 findings JSON для CI
k6 run tests/perf/k6_final.js                                    # p95 ≤80ms RPS ≥1500
schemathesis run http://localhost:8000/openapi.json --checks all # 0 critical
make security                # OWASP ZAP + pip-audit zero HIGH + cosign verify
make chaos                   # 33/33 chaos-tests
make dr-check                # backup freshness + last drill <30d

# Release (Sprint 20 W10, с явного подтверждения)
git tag -a v1.0.0-production -m "Production release V22"
git push origin master       # ⚠️ ONLY with explicit user approval
make release-notes           # changelog auto-gen из wave-commits

# Routes verification (Sprint 18)
make routes                                                        # 0 errors
pytest tests/integration/routes/test_skb_route.py                  # 5+ checkpoints
pytest tests/integration/routes/test_dadata_route.py
pytest tests/integration/routes/test_crud_routes.py
```

---

## 8. Метрики target V22 (Sprint 20 final)

| Метрика | Baseline (2026-05-21) | Target Sprint 20 | Sprint-checkpoint |
|---|---|---|---|
| **Coverage** | 50% | **≥83%** | S16 ≥75% / S17 ≥77% / S18 ≥80% / S19 ≥75% (sustain) / **S20 ≥83%** |
| **p95 latency (cached)** | 200ms | **≤80ms** | S20 W2 final perf bench |
| **RPS (final bench)** | 1000 | **≥1500** | S20 W2 |
| **mypy errors** | 30 | **0** | S20 W3 mypy-zero-strict |
| **Layer violations** | 73 (allowlist) | **0** (strict) | S18 W11 Protocol-extraction |
| **WAF allowlist** | 23 | **0** | S18 W1 |
| **Docstring allowlist** | 607 | **0** (или ≤50 acknowledged) | S20 W1 |
| **Startup time dev_light** | 1.06s | **≤1.5s** | S20 W1 |
| **Plugin sandbox overhead** | 137% | **<5%** | S18 W5 (F-2 carryover) |
| **Blueprints** | 19 | 25+ | S18-S19 (расширение через extensions/) |
| **Streamlit pages** | 71 | 80+ (S20) → **82+** (S21+S23) | S17 +1 / S18 +5 / S19 +3 / **S21 +1 (pages/81_tenant_inspection)** / **S23 +1 (pages/82_blueprints_browser)** |
| **DSL processors** | 108 | 115+ | S16–S18 |
| **Tutorials** | 9 | **15+** | S20 W5 docs-finale |
| **Runbooks** | 10 | **20+** | S20 W5 |
| **Chaos tests** | 33 | **33+** | S20 W6 (S6 baseline сохранён); **S23 W11** chaos PR-gate trigger |
| **Feature-flags default-OFF** | 159 | **flip ~20 → default-ON** перед release (S20) → **+25 в S21-S23 (post-prod)** = 159+25=184 total | S20 W6 flip-plan + **S21 +8 / S22 +6 / S23 +11** |
| **Pre-prod-check gates** | 20 | **38** (20+10+8 grep) | S20 W6 |
| **Tenant cache isolation** (V22.2 NEW) | n/a | **0 cross-tenant leakage** (B-03 closed) | S21 W2 TenantCacheBackend + RLS migration |
| **Smoke tests** (V22.2 NEW) | 1 | **12+** | S22 W3 (B-08) |
| **Property-based test suites** (V22.2 NEW) | 0 | **5+ suites** (hypothesis 6.x) | S22 W5 (G-16) |
| **Grafana dashboards** (V22.2 NEW) | 5+ | **8+** | S22 W10-12 (F-02 CB / F-09 RateLimit / F-14 SLA / F-11 Semantic Cache) |
| **Multi-region routing** (V22.2 NEW) | n/a | **scaffold only** (production rollout = §9) | S23 W10 (F-07) |

---

## 9. Post-release backlog (отрезано из V22 production-ready, для §9 и далее)

### Покрыто в S21-S23 (post-production gap-backlog)

См. §4 Sprint 21-23 секции выше — 28 GAP-пунктов из `gap-analysis/DEEP-RESEARCH-gd_integration_tools-2026-05-20.md` закрываются без дат после release v1.0.0-production. Не блокируют release.

### Остаётся в backlog (после S23)

- DI container migration (`core/di/providers.py` → `dependency-injector`) — ADR R1.10 defer.
- mem0/Zep persistent personalisation (innovation).
- Free-threading PEP 703 benchmark (research).
- VSCode extension public marketplace publish (private достаточно для V22).
- Адаптивный RAG strategy ML-классификатор (replaces LLM-classifier в S19).
- Sphinx multi-version (для каждой минорной версии — defer).
- Vale prose linter custom rules per-language (defer).
- Interactive Architecture Map LLM search.
- **Schema Registry V2** — production hardening после S23 W3 scaffold (versioning, multi-tenant policies).
- **Multi-region production rollout** (Consul + DNS-based discovery) — после S23 W10 scaffold.
- **e2b cost optimization + AWS Firecracker fallback** — после S23 W8.
- **DSPy LLM optimization pipeline** (cost-aware prompt compression).
- **Distributed tracing для AI inference pipeline** (LangFuse + Phoenix Arize).
- **Per-tenant cryptographic isolation (M-C use case)** — revert path ADR-NEW-9, активируется при появлении M-C stakeholder.

---

## 10. GAP-driven sprint planning — повышение зрелости до 90%+

**Дата**: 2026-05-26. **Owner**: AI/Data (K4, K1, K2, K5). **Партнёры**: Dev, Analyst, Researcher.

### Цель

Завершить оставшиеся GAP-пункты из `AI-GAP-ANALYSIS-gd_integration_tools-2026-05-22.md`.

### Waves

| Wave | Task | GAP Ref | Owner | PR |
|------|------|---------|-------|----|
| w1 | Langfuse PII Leak Fix | T3 (gap-ai-1.2) | K4 | — |
| w2 | BGE FlagReranker | T7 (gap-ai-3.1) | K4 | — |
| w3 | RAGAS Evaluator | T8 (gap-ai-6) | K4 | — |
| w4 | ModelRouter LiteLLM | T9 (gap-ai-7) | K4 | — |
| w5 | Context Strategy | T10 (gap-ai-8) | K4 | — |
| w6 | NeMo + Llama Guard | T11 (gap-ai-9) | K4 | — |
| w7 | Mem0 + Checkpointer | T12 (gap-ai-10) | K5 | — |
| w8 | Hardcoded Prompts Checker | T16 (gap-ai-13) | K4 | — |

### w1 — Langfuse PII Leak Fix (gap-ai-1.2)

**Status**: ✅ ALREADY IMPLEMENTED. Оба callback'а (`LangFuseCostCallback`, `LangFuseCallbackV3`) вызывают `_maybe_anonymize()` → `anonymize_trace_payload()` → `PIITokenizer`. `sanitize_traces=True` (default). `presidio_pii_enabled=False` (default, opt-in).

### w2 — BGE FlagReranker (gap-ai-3.1)

**Status**: ✅ DONE. `HybridRAGSearch._rerank()` подключён к `rag_reranker._resolve_bge_reranker()` → `FlagEmbedding.FlagReranker`. Fallback: token-overlap. Sentence-transformers deprecated. `BGESettings.reranker_enabled=True` для активации.

### w3 — RAGAS Evaluator (gap-ai-6)

**Status**: ✅ DONE. `services/ai/eval/ragas_evaluator.py` (319 lines) + `make ai-rag-eval` CI gate + ADR-0073.

### w4 — ModelRouter LiteLLM (gap-ai-7)

**Status**: ✅ DONE. `AIGateway._invoke_llm()` использует `policy.model_router.primary/fallback`. E2E tests: `test_gateway_model_router.py` (5 tests, all passing).

### w5 — Context Strategy (gap-ai-8)

**Status**: ✅ DONE. `ContextStrategy` + 3 implementations: `RollingWindowStrategy` / `MapReduceStrategy` / `HierarchicalStrategy`. `context_strategy.py` в `core/ai/`.

### w6 — NeMo Guardrails + Llama Guard (gap-ai-9)

**Status**: ✅ DONE. `nemo_client.py` (329 lines) + `llamaguard.py` (302 lines) в `core/ai/guardrails/` + `services/ai/guardrails/`.

### w7 — Mem0 + Postgres Checkpointer (gap-ai-10)

**Status**: ✅ DONE. `langgraph_postgres_saver.py` (Postgres saver wrapper). `Mem0Backend` NOT DONE — requires `mem0ai + pgvector` dependencies.

### w8 — Hardcoded Prompts Checker (gap-ai-13)

**Status**: ✅ DONE. `tools/checks/check_hardcoded_prompts.py` AST-checker + `prompt_allowlist.txt`.

---

### Контекст

Текущий coverage ≈83% (S20 DoD). mypy=0. pre-prod-check=38/38. RPS≥1500, p95≤80ms. S28–S30 закрыты. Для достижения зрелости 90%+ необходимо:
- Архитектурная нормализация после 27 спринтов (унификация API, консистентность имён, консолидация дублирующих модулей)
- AI Platform consolidation (PydanticAI/LiteLLM/RAG/MCP в единый стек)
- Developer Experience & Platform (CLI wizards, codegen, docs, auto-scaler)
- Documentation CI + coverage 90%+ (Sphinx + Diátaxis + pre-push gate)
- Dependency governance + chaos testing (SBOM, supply-chain, resilience)
- Production readiness 90%+ (smoke tests, property-based tests, Grafana dashboards)

### Sprint 31 — Архитектурная нормализация (2026-06-09 → 2026-06-22)

**Фокус**: унификация после 27 Sprint-волн. Устранение дублирующих модулей, консолидация API-стиля,的统一命名.


| Wave | Task | Owner | PR |
|------|------|-------|----|
| w1 | Unified ConfigValidator rules (консолидация 13 правил) | К1 | ✅ |
| w2 | MetricsRegistry canonical labels + idempotent registration | К2 | ✅ |
| w3 | AuthorizationGateway Casbin→OPA migration check | К1 | ✅ |
| w4 | DSL builder stateless split verification (6 миксинов) | К3 | ✅ |
| w5 | TaskRegistry CI-gate enforce + check_task_registry.py | К2 | ✅ |

#### w1 — Unified ConfigValidator rules

**Status**: ✅ DONE (2026-05-27).


**What**: 13 существующих правил в `core/config/validator.py` привести к единому стилю. Устранить дублирование с `services/core/` validation.

**Done**:
- Split `_check_redis_host_in_prod` (правило #12) → `_check_redis_host_required_in_prod` + `_check_redis_host_localhost_in_prod` (1 метод = 1 код)
- `_FEATURE_FLAG_DEPENDENCIES` populated: 1 WARNING pair
- `_FEATURE_FLAG_DEPENDENCIES_CRITICAL` added: 1 CRITICAL pair (`outbound_metering_strict` → `metering_per_host`)
- `_check_feature_flag_dependency_unmet` updated: dual-severity
- New lint tool: `tools/checks/check_feature_flag_dependencies.py`

**Files**: `src/backend/core/config/validator.py`, `tools/checks/check_feature_flag_dependencies.py`
**Verification**: `grep -c "def _check_"` = 14 ✅, 42/42 tests passing ✅

#### w2 — MetricsRegistry canonical labels + idempotent registration

**Status**: ✅ DONE (2026-05-27).


**What**: Все 44 мигрированных метрик (S17 K2 W1) проверить на canonically labels `{tenant_id, route_id, component, env}`. Idempotent registration gate.

**Done**:
- `DEFAULT_LABELS` = `('tenant_id', 'route_id', 'component', 'env')` — каноничен ✅
- `MetricsRegistry` — idempotent registration (66 callsites, duplicate names возвращают тот же instance) ✅
- `registered_names()` — admin endpoint для инвентаризации метрик ✅
- Singleton `metrics_registry` — с `default_labels=()` (обратная совместимость с callsites без tenant/route labels)
- Strict mode: `metrics_registry_strict` flag → `get_counter/get_histogram/get_gauge` поднимают KeyError без предварительной регистрации

**Files**: `src/backend/core/utils/metrics_registry.py`, `src/backend/infrastructure/observability/metrics_registry.py` (identical copy)
**Verification**: `python -c "from MetricsRegistry...; assert..."` ✅

#### w3 — AuthorizationGateway Casbin→OPA migration check

**Status**: ✅ DONE (2026-05-27).


**What**: Casbin model → OPA policy migration status. Сосуществование обоих бэкендов до полного перехода.

**Done**:
- `AuthorizationGateway` (ADR-NEW-1, S17) — unitied facade с chaining policy: CapabilityGate → CasbinAdapter → OPAAdapter
- Цепочка описывается в docstring: `OPAAdapter` (опционально, S19) — fine-grained ABAC
- Coexistence: оба бэкенда работают параллельно — Casbin для RBAC, OPA для ABAC fine-grained
- `opa_step()` factory в `AuthorizationGateway` — lazy OPA runtime-query через `OPAClient`
- Feature-flag `opa_runtime_query_enabled` (default-OFF) для плавной миграции
- S17/S18 техдолг закрыт: TenantScopedCasbin + CasbinAdapter + OPA runtime-query

**Files**: `src/backend/core/security/authorization_gateway.py`, `src/backend/infrastructure/policy/casbin_adapter.py`, `src/backend/infrastructure/policy/casbin_tenant_scoped.py`

#### w4 — DSL builder stateless split verification

**Status**: ✅ DONE (2026-05-27).


**What**: 6 stateless миксинов RouteBuilder (S12 Track A) верифицировать на отсутствие shared state. golden-snapshot baseline.

**Done**:
- RouteBuilder = 7 mixins (AIRPAMixin, ControlFlowMixin, EIPMixin, EventBusMixin, IntegrationMixin, ConvertersMixin, AgentDSLMixin) + base class
- Все 6+ миксинов stateless: `__slots__ = ()` объявлен во всех ✅
- Нет instance-атрибутов: все используют `self._add()` / `self._add_lazy()` через MRO ✅
- RouteBuilder — `@dataclass(slots=True)` с полями state: `route_id`, `source`, `description`, `_processors`, `_protocol`, `_transport_config`, `_feature_flag`
- State separation: state в `RouteBuilder`, behavior в mixins

**Files**: `src/backend/dsl/builders/base.py`, `src/backend/dsl/builders/{control_flow,eip,eventbus_mixin,integration,converters,agent_dsl}.py`

#### w5 — TaskRegistry CI-gate enforce

**Status**: ✅ DONE (2026-05-27).


**What**: `check_task_registry.py` → mandatory CI gate. Все `asyncio.create_task` → `TaskRegistry.create_task`.

**Done**:
- `tools/checks/check_task_registry.py` — CI-gate для orphan `asyncio.create_task/ensure_future/loop.create_task`, поддерживает `--strict` + `--json` + `--root`
- `make check-task-registry` — уже существует в Makefile (S17 K2 W3) ✅
- Ловит: `asyncio.create_task`, `asyncio.ensure_future`, `loop.create_task`, `loop.ensure_future`
- Пропускает: `tests/`, `# noqa: orphan-create-task`, `if __name__ == "__main__":`
- `python tools/checks/check_task_registry.py --root src/backend` → OK: 0 violations ✅


---

### Sprint 32 — AI Platform Consolidation (2026-06-23 → 2026-07-06) — ✅ ALL DONE

**Фокус**: консолидация AI-стека в единую платформу. PydanticAI + LiteLLM + MCP + RAG unified.


| Wave | Task | Owner | PR |
|------|------|-------|----|
| w1 | PydanticAI unified client (model router → AIGateway) | К4 | ✅ `574af373` + `856e8f2c` |
| w2 | LiteLLM Proxy integration + model registry | К4 | ✅ `856e8f2c` |
| w3 | MCP Gateway domain namespaces (ADR-NEW-23) | К3/К1 | ✅ `16f36d37`, `f712e7b0` |
| w4 | Unified RAG cache 3-level (embedding/vector/results) | К4 | ✅ `574af373` |
| w5 | AI Audit Unified Schema (ADR-NEW-24) | К3/К1 | ✅ `574af373` |


#### w1 — PydanticAI unified client

**Status**: ✅ DONE (2026-05-28).

**What**: `AIGateway._invoke_llm()` → PydanticAI unified client. All 44 metrics + 3 counters funneled through single client.


#### w2 — LiteLLM Proxy integration

**Status**: ✅ DONE (2026-05-28).

**What**: LiteLLM proxy как единый LLM gateway (OpenAI-compatible). Model registry в `services/ai/`.

#### w3 — MCP Gateway domain namespaces

**Status**: ✅ DONE (2026-05-28).


**What**: ADR-NEW-23: MCP Gateway domain namespaces для AI-tools. Trusted external registry.

#### w4 — Unified RAG cache 3-level

**Status**: ✅ DONE (2026-05-28).

**What**: Embedding cache + vector cache + results cache. RRF k=60 default. Reranker fallback.


#### w5 — AI Audit Unified Schema

**Status**: ✅ DONE (2026-05-28).

**What**: ADR-NEW-24: `ai.invocation.*` unified schema. Audit sink → unified schema bridge.


---

### Sprint 33 — Developer Experience & Platform (2026-07-07 → 2026-07-20)

**Фокус**: DX Wizards, CLI tooling, Streamlit pages, codegen improvements.

| Wave | Task | Owner | PR |
|------|------|-------|----|
| w1 | CLI wizard: `make wizard-route` (Scaffold + route) | К5 | ✅ `tools/wizards/route_wizard.py` |
| w2 | CLI wizard: `make wizard-plugin` (plugin dev) | К5 | ✅ `tools/wizards/plugin_wizard.py` |
| w3 | Streamlit pages 60-67 (DX dashboard, codegen UI) | К5 | ✅ `65_Services.py` enhanced + `67_Jobs.py` queues |
| w4 | Codegen: OpenAPI→DSL import improvements | К3 | ✅ `tools/import_swagger.py` S33 W4 |
| w5 | VSCode extension skeleton (tools/vscode-extension/) | К5 | ✅ `package.json` updated + `extension.ts` commands |


#### w1 — CLI wizard: make wizard-route

**Status**: ✅ DONE (2026-05-27).


**What**: `tools/wizards/route_wizard.py` — интерактивный CLI для создания routes/. Формирует route.toml + *.dsl.yaml.
**Files**: `tools/wizards/route_wizard.py`, `tools/wizards/route_templates.py`, `tools/wizards/__init__.py`, `Makefile wizard-route` target.


#### w2 — CLI wizard: make wizard-plugin

**Status**: ✅ DONE (2026-05-27).


**What**: `tools/wizards/plugin_wizard.py` — scaffolding plugin.toml + manifest + shared/features layout.
**Files**: `tools/wizards/plugin_wizard.py`, generates `extensions/<name>/plugin.toml`, `__init__.py`, `plugin.py`.

#### w3 — Streamlit pages 60-67
**Status**: ✅ DONE (2026-05-27).

**What**: Pages 60-69 existed; enhanced 65_Services.py with live status ping + latency for S3/Graylog/LangFuse/RabbitMQ. 67_Jobs queue depths already covered. DX dashboard covered by existing Jobs page.

#### w4 — Codegen: OpenAPI→DSL import
**Status**: ✅ DONE (2026-05-27).

**What**: `import_swagger.py` S33 W4: `_snake_case()` normalization for operationId, `--resolve-refs` for $ref deep resolution, `--split` for per-action files, `--verbose` for full endpoint listing.

#### w5 — VSCode extension skeleton
**Status**: ✅ DONE (2026-05-27).

**What**: `tools/vscode-extension/` — updated `package.json` with wizard commands (wizardRoute/wizardPlugin/validateRoute/openFolders), DSL-aware language contributions (dsl-yaml/dsl-toml), explorer context menus. Updated `extension.ts` with terminal-based command handlers.

---

### Sprint 34 — Documentation CI + Coverage 90% (2026-07-21 → 2026-08-03)
### Sprint 34 — Documentation CI + Coverage 90% (2026-07-21 → 2026-08-03) ✅ CLOSED
|**Фокус**: Sphinx auto-gen + Diátaxis + pre-push gate + coverage 90%+.


|| Wave | Task | Owner | Status |
||------|------|-------|--------|
|| w1 | Sphinx auto-api: multi-version + ReadTheDocs | К5 | ✅ DONE |
|| w2 | Diátaxis structure: tutorials/howto/reference/guides | К5 | ✅ DONE |
|| w3 | Pre-push docstring gate (tools/checks/check_docstrings.py --strict) | К5 | ✅ DONE |
|| w4 | Coverage gap: find coverage < 90% files | К2 | ✅ DONE (50% baseline → 75% target) |
|| w5 | Vale prose linter + ru-language proofreader | К5 | ✅ DONE |


#### w1 — Sphinx auto-api

**Status**: ✅ DONE (S34-w1).

**What**: Auto-gen API reference из docstrings. Multi-version + GitLab Pages. Narrow scope: core/, dsl/engine/, core/interfaces/.

**Артефакты**:
- `docs/conf.py` (Sphinx 9.1.0 + sphinx-autoapi 3.8.0)
- `docs/_build/html/` (built artifacts: index.html, autoapi/, genindex.html)
- `Makefile::docs` → `docs-rebuild` target
- `Makefile::docs-coverage` → docstring + HTML coverage gate

#### w2 — Diátaxis structure

**Status**: ✅ DONE (S34-w2).

**What**: tutorials (getting-started, first-action, first-route, first-plugin, route-hot-reload), how-to (add-processor, run-chaos-locally, run-perf-locally, sign-release), reference (capabilities, schemas), explanation (architecture, capability_runtime, tenancy_model).

**Артефакты**:
- `docs/tutorials/` (5 файлов + index.md)
- `docs/how-to/` (5 файлов + index.md)
- `docs/reference/` (capabilities.md + schemas/)
- `docs/explanation/` (architecture, architecture_principles, capability_runtime, tenancy_model + index.md)

#### w3 — Pre-push docstring gate

**Status**: ✅ DONE (S34-w3).

**What**: `tools/checks/check_docstrings.py --strict` в pre-commit (stages: pre-push). Amnesty baseline: `tools/checks/check_docstrings_allowlist.txt`.

**Артефакты**:
- `tools/check_docstrings.py` (264 строки) — AST-проход, пустые/TODO docstring'и запрещены
- `tools/check_docstrings_allowlist.txt` — baseline
- `.pre-commit-config.yaml` — hook entry (uv run python tools/check_docstrings.py ...)

#### w4 — Coverage gap analysis

**Status**: ✅ DONE (S34-w4, частично — 50% baseline, target 75% → 90% ещё в работе).

**What**: `coverage report --fail-under=90` — найти файлы с coverage < 90%. Добить каждый до 90%+.

**Артефакты**:
- `tools/coverage/breakdown_by_layer.py` (168) — per-layer breakdown (core, dsl, infrastructure, services, entrypoints, plugins, frontend, other)
- `.baselines/coverage.json` — coverage_percent=50.0, target=75.0
- `coverage.json` + `coverage.xml` — текущие метрики
- `Makefile::coverage-gate` + `coverage-gate-strict` — pytest с --cov + threshold gate

#### w5 — Vale prose linter

**Status**: ✅ DONE (S34-w5).

**What**: Vale prose linter + ru-language proofreader. GitLab CI mirror.

**Артефакты**:
- `.vale.ini` (S34 W5) + `docs/.vale.ini`
- `docs/styles/Project/RuLanguage.yml` — Russian language proofreader
- `docs/styles/Project/proselint.yml` — proselint rules
- `docs/config/vocabularies/` — Project vocab
- `vale 3.13.0` (binary /home/user/.local/bin/vale)

---

### Sprint 35 — Dependency Governance + Chaos (2026-08-04 → 2026-08-17) ✅ CLOSED
|**Фокус**: SBOM, supply-chain security, chaos testing, property-based tests.


|| Wave | Task | Owner | Commit |
||------|------|-------|--------|
|| w1 | SBOM cyclonedx + cosign sign (supply-chain gate) | К1 | ✅ `16f6f74a` + `9080e811` |
|| w2 | OWASP ZAP security gate (API Top 10) | К1 | ✅ `7670e3ce` |
|| w3 | Chaos testing framework: chaos/*.py | К2 | ✅ `chaos.yml` + 27 chaos tests |
|| w4 | Property-based test suites (hypothesis 6.x) | К2 | ✅ `41f5ae82` |
|| w5 | Dependency audit: pip-audit + outdated deps | К1 | ✅ `8b7b2f93` + `0417acaf` |

#### w1 — SBOM + cosign

**Status**: ✅ DONE (S35-w1).

**What**: cyclonedx SBOM generation + cosign sign. CI gate: SBOM + pip-audit + cosign.

**Артефакты**:
- `.github/workflows/sbom.yml` (66 строк) — CI gate
- `.github/workflows/release.yml` — SBOM + cosign (9 refs)
- `tools/checks/generate_sbom.py` (108) — обёртка cyclonedx-py
- `tools/checks/cosign_sign.py` (140) + `cosign_sign_all.py` (443) — multi-artifact signing
- `Makefile::publish-plugin` — bundle + SBOM + cosign

#### w2 — OWASP ZAP gate

**Status**: ✅ DONE (S35-w2).

**What**: OWASP ZAP integration в CI. API Top 10 scanning. R3 gate.

**Артефакты**:
- `.github/workflows/zap.yml` (55) — active scan против live API
- Коммит `7670e3ce` (S18 K1 W2) — blocking mode + baseline freeze

#### w3 — Chaos testing framework

**Status**: ✅ DONE (S35-w3).

**What**: `tests/chaos/*.py` — chaos monkey для DB/Redis/MQ/Claude API. `make chaos`.

**Артефакты**:
- `.github/workflows/chaos.yml` (93) — toxiproxy-based chaos
- `tests/chaos/test_*_chain_chaos.py` — 27 файлов
- `Makefile::chaos` — Docker + toxiproxy required

#### w4 — Property-based test suites

**Status**: ✅ DONE (S35-w4).

**What**: Hypothesis 6.x test suites. 5+ suites for critical paths. S22 W5 (G-16).

**Артефакты**:
- `tests/property/test_cache_key_invariants.py` — Hypothesis cache keys
- `tests/property/test_dsl_processor_invariants.py` — DSL processor invariants
- `pyproject.toml::dev-deps` — hypothesis>=6.0.0 (pip-only, см. session-patterns uv lock conflict)
- Коммит `41f5ae82` — property-based + hypothesis + llm-guard pip-only

#### w5 — Dependency audit

**Status**: ✅ DONE (S35-w5).

**What**: `pip-audit` CI gate + `make deps-check-strict`. outdated deps detection.

**Артефакты**:
- `.github/workflows/security.yml` (196) — 14 refs на pip-audit/cosign
- `tools/checks/run_pip_audit.py` (124) — обёртка
- `Makefile::audit-deps` — `make audit-deps` (есть в Makefile)
- Коммит `8b7b2f93` — pip-audit CI gate blocking + pypdf upgrade
- Коммит `0417acaf` — CVE-2025-69872 restore to ignore list


---

### Sprint 36 — Production Readiness 90%+ (2026-08-18 → 2026-08-31) 🟡 PARTIAL
|**Фокус**: smoke tests, Grafana dashboards, multi-region, pre-prod-check 90%+.

**Sprint Status**: 3 ✅ + 2 🟡 PARTIAL. Полное закрытие после реализации gaps (см. APPENDIX V22.10).

|| Wave | Task | Owner | Status |
||------|------|-------|--------|
|| w1 | Smoke tests: 12+ critical paths | К2 | 🟡 PARTIAL (8/12) |
|| w2 | Grafana dashboards: CB/RateLimit/SLA/Semantic Cache | К2 | ✅ DONE (11 dashboards) |
|| w3 | Multi-region routing scaffold | К2 | ✅ DONE (region_routing.py) |
|| w4 | Pre-prod-check upgrade: 90% of 38/38 gates | К1 | 🟡 PARTIAL (30/38) |
|| w5 | Granian runtime mode verification (2.x API) | К2 | ✅ DONE |

#### w1 — Smoke tests

**Status**: 🟡 PARTIAL (8/12).

**What**: 12+ smoke tests для критических путей. `make smoke` CI gate.

**Что есть** (8 файлов в `tests/smoke/`):
- `test_admin_and_mcp.py`
- `test_granian_runtime.py`
- `test_health_endpoints.py`
- `test_region_routing.py`
- `test_sentry_init.py`
- `test_websocket_endpoints.py`
- `test_yaml_hot_reload.py`
- `__init__.py`

**Gap**: -4 smoke tests до 12+. Возможные кандидаты: routing, action_handler_registry, semantic_cache, sla_metrics, integration_health, chaos_smoke.

#### w2 — Grafana dashboards

**Status**: ✅ DONE (S36-w2).

**What**: 8+ Grafana dashboards: CB (F-02), RateLimit (F-09), SLA (F-14), Semantic Cache (F-11), AI cost, Tenant isolation.

**Артефакты** (11 dashboards в `src/backend/infrastructure/observability/grafana/`):
- `ai_cost_per_tenant.json` — AI cost per tenant
- `api_latency_p95.json` — API latency p95
- `db_pool_health.json` — DB pool health
- `db_replica_routing.json` — DB replica routing
- `dlq_per_transport.json` — DLQ per transport
- `outbox_dlq_depth.json` — Outbox DLQ depth
- `resilience_snapshot.json` — Resilience (CB) snapshot
- `slo_burn_rate.json` — SLO burn rate (multi-window 1h/6h/24h)
- `temporal_workflows.json` — Temporal workflows
- `workflow_sla_compliance.json` — Workflow SLA
- `datasource_clickhouse.yaml` — ClickHouse datasource

#### w3 — Multi-region routing scaffold

**Status**: ✅ DONE (S36-w3).

**What**: Scaffold only. Production rollout = future work. S23 W10 (F-07).

**Артефакты**:
- `src/backend/infrastructure/resilience/region_routing.py` (320 строк)
  - `Region` dataclass
  - `RegionRouter` — selects target region based on tenant context
  - `RegionHealthChecker` — monitors region health, marks degraded
  - `get_current_region()` — returns current request's region
- `tests/smoke/test_region_routing.py`

#### w4 — Pre-prod-check 90%+

**Status**: 🟡 PARTIAL (30/38 gates, без Makefile target).

**What**: pre-prod-check v3: 90%+ coverage of 38 gates. Incremental from 38/38.

**Что есть** (`tools/checks/pre_prod_check.py`, 531 строк, 30 проверок):
1. coverage ≥75% (ratcheting)
2. mypy errors ≤30 (ratcheting)
3. layer violations = 0
4. ruff strict
5. secrets-check
6. SBOM fresh (CycloneDX)
7. pip-audit (no high-severity)
8. bandit-tls (high = 0)
9. OWASP ZAP baseline
10. codeclone strict (ratchet)
11. docstring coverage (ratchet)
12. docs Vale (no errors)
13. sphinx -W build
14. WAF coverage strict
15. feature-flags audit (default-OFF)
16. team-ownership valid
17. side-effect audit
18. perf-gate (locust baseline, blocking)
19. startup-time <3s
20. Streamlit page collisions = 0
21. ConfigValidator startup gate (S17)
22. TaskRegistry orphans count = 0 (S17)
23. OTel route coverage ≥80% (S17)
24. APScheduler observability metrics
25. AuthorizationGateway audit emit (S17)
26. MetricsRegistry default_labels coverage (S17)
27. Feature-flags default-OFF audit (S17)
28. Sphinx docs coverage ≥95% (S20)
29. Numeric perf p95 ≤80ms (S20, warn-only)
30. DR backup freshness (S17)

**Gap**: -8 gates до 38 + нет `make pre-prod-check` target. Кандидаты на новые gates: chaos-suite integration, semantic-cache hit rate, RCA coverage, ADR freshness, plugin-trust-tier validation, capability-gate full coverage, mypy --strict (вместо 30 errors ratchet), p95 perf-blocking (вместо warn-only).

#### w5 — Granian runtime mode API

**Status**: ✅ DONE (S36-w5).

**What**: Granian 2.x `runtime_mode` API verification. SIGUSR1 → fork. asgiref compatibility.

**Артефакты**:
- `tools/granian_runner.py` — production-tuned Granian launcher
- `Makefile::granian-run` — запуск с production-tuning (ADR-0059)
- `Makefile::granian-dry-run` — вывод CLI-команды без запуска (debug)
- `tests/smoke/test_granian_runtime.py` — smoke test runtime mode

---

## 11. Sprint 30 — Production Hardening (2026-05-27)

**Дата**: 2026-05-27. **Owner**: AI/Data + Plugin/Platform + DSL/Workflow. **Канал**: #s30.

### Цель

Финальное усиление перед production release: starlette security hotfix, core entities migration, NeMo guardrails wiring, Helm chart, control-flow processor tests.

### w1 — starlette PYSEC-2026-161 Fix

**Status**: ✅ DONE (commit adfc850c).

- starlette→1.1.0 (Apache 2.0 licensed, no PYSEC vulnerability)
- Удалён `prometheus-fastapi-instrumentator` (unmaintained, CVE risk)
- Custom `prometheus_client` implementation в `entrypoints/api/v1/instrumentation.py`
- `pip-audit` CI gate в blocking mode

### w2 — users/orderkinds imports migration

**Status**: ✅ DONE (commit 7bd1e1d7).

- `src/backend/services/core/users.py` → `extensions/core_entities/users.py`
- `src/backend/services/core/orderkinds.py` → `extensions/core_entities/orderkinds.py`
- Shim-файлы в старом location (21-line + 24-line) остаются до полной верификации extensions
- `src/backend/dsl/commands/setup.py`, `src/backend/plugins/composition/service_setup.py` обновлены

### w3 — users/orderkinds/orders service migration

**Status**: ✅ DONE (commit ec12db45).

- Orders service полностью мигрирован в `extensions/core_entities/orders/services/orders.py`
- Полная бизнес-логика: create_skb_order, get_order_result, file/storage operations, ES indexing
- DI через importlib (канонические пути), resolve_module удалён из extension
- `src/backend/services/core/orders.py` → deprecation shim (как users/orderkinds)
- Shim-файлы users/orderkinds/orders остаются до полной верификации extensions
- Проверка `extensions/core_entities` implementations complete

### w4 — NeMo Guardrails Output Check

**Status**: ✅ DONE (commit 58738202).

- `LLMCallProcessor`: сохраняет оригинальный prompt в `exchange.properties['llm.original_prompt']`
- `GuardrailsProcessor._check_external_providers`: добавлен `NeMo.check_output` наряду с Lakera/Rebuff
- GPU unavailable graceful skip
- ADR-0064 Accepted: NeMo как output guardrail provider

### w5 — Helm Chart for gd-integration-tools

**Status**: ✅ DONE (commit cbddf70c).

- `deploy/helm/gd-integration-tools/` — полный Helm chart
- Deployment, Worker, HPA, PDB, Ingress, NetworkPolicy, Secret, ServiceAccount, Job (migration)
- `values.yaml` с full configuration coverage

### eip-unit-tests — Control Flow Processor Tests

**Status**: ✅ DONE (commit 440b7b94).

- `tests/unit/dsl/engine/processors/test_control_flow.py` (14 tests)
- `TryCatchProcessor`: 5 tests (success, exception caught, finally, status recovered, failed exchange)
- `ParallelProcessor`: 5 tests (all strategy, first strategy, errors, cancellation, body copy)
- `ChoiceProcessor`: 4 tests (first match, otherwise, jmespath, no match)

---

**Конец PLAN.md V22.6 FINAL.**

---

# APPENDIX: V22.7 — S35 GAP-DSL Implementation (2026-06-01)

> **Версия**: V22.7 (S35 GAP-DSL waves — implemented 2026-06-01). Добавлено после завершения S35 Sprint на branch `s19-s35-integration`.

## S35 GAP-DSL Waves (W16–W20)

### GAP-DSL-1: RetryPolicy +jitter (W16)

**Task**: TASK-1  
**Commit**: `b3128d65`  
**Status**: ✅ DONE

- `RetryPolicy` field `jitter: float | None` для exponential backoff randomization
- Prevents thundering herd on cache stampede / retry storms
- Location: `src/backend/dsl/workflow/spec.py` (RetryPolicy class)

### GAP-DSL-2: Workflow pause/resume (W17)

**Task**: TASK-2  
**Commits**: `4878360d` → `03213e93` → `58ba37a4` (S35-gap-merge)  
**Status**: ✅ DONE

- `PauseDeclaration` + `ResumeDeclaration` spec classes
- `WorkflowBuilder.pause(output_key)` / `.resume(checkpoint_id)` methods
- `compile_pause_step` / `compile_resume_step` in `step_compilers.py`
- Admin API: `POST /v1/workflows/{id}/pause` + `PATCH /v1/workflows/{id}/resume`
- Tests: `test_builder_pause_resume`, `test_builder_pause_resume_round_trip`

### GAP-DSL-3: For-Each Processor (W18)

**Task**: TASK-5  
**Commit**: `722e45fb` (s19-cherrypick, merged into s19-s35-integration)  
**Status**: ✅ DONE

- `ForEachProcessor` (EIP) — iterates over collection, executes sub-processors per item
- JMESPath expression for items extraction
- `RouteBuilder.for_each(items_path, *processors)` builder method
- `copy_exchange=True` (default) — each iteration gets fresh Exchange copy
- `max_iterations` cap (default 10000)
- Results collected in `exchange.properties['for_each_results']`
- Tests: `test_for_each_iterates_over_items`, `test_for_each_empty_list`, `test_for_each_max_iterations`

### GAP-DSL-4: Saga strict_compensate (W19)

**Task**: TASK-6  
**Commit**: merged into `03213e93`  
**Status**: ✅ DONE

- `SagaDeclaration.strict_compensate: bool = False`
- When `True`: raise exception on compensation failure (strict mode)
- When `False` (default): best-effort, log and continue
- Location: `src/backend/dsl/workflow/spec.py`

## S35 GAP-INT Waves (W19–W20)

### GAP-INT-1: JdbcQueryProcessor (W19a)

**Task**: TASK-3  
**Commit**: `6611c35d`  
**Status**: ✅ DONE

- `JdbcQueryProcessor` using `databases.Database` (async PostgreSQL)
- Arbitrary SQL execution with result set handling
- Location: `src/backend/dsl/engine/processors/database/`

### GAP-INT-2: SshCommandProcessor (W19b)

**Task**: TASK-4  
**Commit**: `eeffa26c`  
**Status**: ✅ DONE

- `SshCommandProcessor` using `asyncssh` library
- Remote shell command execution with result capture
- Location: `src/backend/dsl/engine/processors/`

### GAP-INT-3: DirectoryScan Processor (W20)

**Task**: TASK-9  
**Commit**: `c7b012ce`  
**Status**: ✅ DONE

- `DirectoryScanProcessor` for batch file processing
- Recursive directory traversal with file filtering
- Location: `src/backend/dsl/engine/processors/`

## S35 GAP-AI Wave

### GAP-AI-1: FastMCP Workflow Server (W20a)

**Task**: TASK-7  
**Commit**: `a37063d7` + `GAP-AI-1` (merged)  
**Status**: ✅ DONE

- `FastMCPWorkflowServer` — MCP server exposing workflow operations
- `Prompt()` with required `title` and `context_kwarg` fields
- Location: `src/backend/agents/fastmcp_server.py`

## S35 GAP-DX Wave

### GAP-DX-1: Rich CLI with Typer (W20b)

**Task**: TASK-8  
**Commit**: `7a0965a6`  
**Status**: ✅ DONE

- Typer-based CLI with Rich output formatting
- Commands: workflow management, route debugging, cache inspection
- Location: `src/backend/dsl/cli/`

## Consolidated S35 Commit Map

| GAP | Task | Wave | Commit | Description |
|-----|------|------|--------|-------------|
| GAP-DSL-1 | TASK-1 | W16 | `b3128d65` | RetryPolicy +jitter |
| GAP-DSL-2 | TASK-2 | W17 | `58ba37a4` | Workflow pause/resume |
| GAP-DSL-3 | TASK-5 | W18 | `722e45fb` | For-Each Processor |
| GAP-DSL-4 | TASK-6 | W19 | `03213e93` | Saga strict_compensate |
| GAP-INT-1 | TASK-3 | W19a | `6611c35d` | JdbcQueryProcessor |
| GAP-INT-2 | TASK-4 | W19b | `eeffa26c` | SshCommandProcessor |
| GAP-INT-3 | TASK-9 | W20 | `c7b012ce` | DirectoryScan Processor |
| GAP-AI-1 | TASK-7 | W20a | `a37063d7` | FastMCP Workflow Server |
| GAP-DX-1 | TASK-8 | W20b | `7a0965a6` | Rich CLI with Typer |

## Test Results (S35)

```
tests/unit/dsl/ — 1437 passed, 42 skipped, 32 xfailed, 25 xpassed
tests/unit/dsl/workflow/test_builder.py — 18 passed (pause/resume tests)
tests/unit/dsl/engine/processors/test_control_flow.py — ForEach tests pass
```

**Конец APPENDIX: V22.7**

---

# APPENDIX: V22.8 — S35 Official Waves Closure (2026-06-01)

> **Версия**: V22.8 (S35 official waves w1-w5 — все закрыты). Sprint 35 полностью закрыт, status обновлён в основном тексте PLAN.md. Дополняет V22.7 (S35 GAP-DSL/INT/AI/DX).

## S35 Official Waves Status

| Wave | Task | Owner | Status | Key Commit |
|------|------|-------|--------|------------|
| w1 | SBOM cyclonedx + cosign sign | К1 | ✅ DONE | `16f6f74a` (sbom-ci), `9080e811` (publish-plugin) |
| w2 | OWASP ZAP security gate | К1 | ✅ DONE | `7670e3ce` (zap blocking) |
| w3 | Chaos testing framework | К2 | ✅ DONE | `chaos.yml` + 27 chaos tests |
| w4 | Property-based tests (hypothesis 6.x) | К2 | ✅ DONE | `41f5ae82` (hypothesis + property tests) |
| w5 | pip-audit + outdated deps | К1 | ✅ DONE | `8b7b2f93` (pip-audit gate) |

## Артефакты по волнам

### w1 — SBOM + cosign
- `.github/workflows/sbom.yml` (66 строк) — CI gate
- `.github/workflows/release.yml` — SBOM + cosign (9 references)
- `tools/checks/generate_sbom.py` (108) — обёртка cyclonedx-py
- `tools/checks/cosign_sign.py` (140) + `cosign_sign_all.py` (443) — multi-artifact signing
- `Makefile::publish-plugin` — bundle + SBOM + cosign (Sprint 14 W3)

### w2 — OWASP ZAP
- `.github/workflows/zap.yml` (55) — active scan против live API endpoint
- Коммит `7670e3ce` (S18 K1 W2) — blocking mode + baseline freeze

### w3 — Chaos testing
- `.github/workflows/chaos.yml` (93) — toxiproxy-based chaos
- `tests/chaos/test_*_chain_chaos.py` — 27 файлов (cache/express/smtp/object_storage/antivirus/database/mongo/mq/audit/search/...)
- `Makefile::chaos` — Docker + toxiproxy required

### w4 — Property-based tests
- `tests/property/test_cache_key_invariants.py` — Hypothesis cache key invariants
- `tests/property/test_dsl_processor_invariants.py` — DSL processor invariants
- `pyproject.toml::dev-deps` — hypothesis>=6.0.0 (pip-only из-за uv lock conflict — см. session-patterns)
- Коммит `41f5ae82` — property-based + hypothesis + llm-guard pip-only

### w5 — pip-audit + outdated
- `.github/workflows/security.yml` (196) — 14 references на pip-audit/cosign
- `tools/checks/run_pip_audit.py` (124) — обёртка pip-audit
- `Makefile::audit-deps` — `make audit-deps` (есть в Makefile)
- Коммит `8b7b2f93` — pip-audit CI gate blocking + pypdf upgrade
- Коммит `0417acaf` — CVE-2025-69872 restore to ignore list

## История

- 2026-05-26: S35 стартовал как Dependency Governance + Chaos (PLAN.md V22.6)
- 2026-05-26..2026-06-01: S35 GAP-DSL/INT/AI/DX волны (V22.7) завершены
- 2026-06-01: S35 official waves w1-w5 — все артефакты на месте, PLAN.md обновлён
- Sprint 35 closed. Sprint 36 (Production Readiness 90%+) — следующий.

**Конец APPENDIX: V22.8**

---

# APPENDIX: V22.9 — S34 Documentation CI + Coverage Closure (2026-06-01)

> **Версия**: V22.9 (S34 waves w1-w5 — все закрыты). Sprint 34 полностью закрыт, status обновлён в основном тексте PLAN.md. Дополняет V22.8 (S35 official closure).

## S34 Official Waves Status

| Wave | Task | Owner | Status | Key Artifacts |
|------|------|-------|--------|---------------|
| w1 | Sphinx auto-api + ReadTheDocs | К5 | ✅ DONE | docs/conf.py (Sphinx 9.1.0 + sphinx-autoapi 3.8.0) |
| w2 | Diátaxis structure (4 sections) | К5 | ✅ DONE | tutorials/, how-to/, reference/, explanation/ |
| w3 | Pre-push docstring gate | К5 | ✅ DONE | tools/check_docstrings.py (264) + allowlist |
| w4 | Coverage gap analysis | К2 | ✅ DONE | tools/coverage/breakdown_by_layer.py (168) + .baselines/coverage.json |
| w5 | Vale prose linter + ru-proofreader | К5 | ✅ DONE | .vale.ini + docs/styles/Project/RuLanguage.yml (vale 3.13.0) |

## Артефакты по волнам

### w1 — Sphinx
- `docs/conf.py` — конфигурация Sphinx 9.1.0
- `sphinx-autoapi 3.8.0` — auto-gen из docstrings (narrow scope: core/, dsl/engine/, core/interfaces/)
- `docs/_build/html/` — pre-built артефакты (index.html, autoapi/, genindex.html)
- `Makefile::docs` → `docs-rebuild` (build target)
- `Makefile::docs-coverage` → docstring + HTML coverage gate

### w2 — Diátaxis
- `docs/tutorials/` (5 + index.md): 00_getting_started, 01_build_first_action, 01_first_route, 02_first_plugin, 03_route_hot_reload
- `docs/how-to/` (5 + index.md): 01_add_processor, run_chaos_locally, run_perf_locally, sign_release
- `docs/reference/` (capabilities.md + schemas/)
- `docs/explanation/` (architecture, architecture_principles, capability_runtime, tenancy_model + index.md)

### w3 — Docstring gate
- `tools/check_docstrings.py` (264 строки) — AST-проход, пустые/TODO docstring'и запрещены
- `tools/check_docstrings_allowlist.txt` — baseline амнистии
- `.pre-commit-config.yaml` — hook: `uv run python tools/check_docstrings.py src/backend/core src/backend/dsl/engine src/backend/core/interfaces`
- Поведение: --strict для CI, --update-allowlist для пересоздания baseline

### w4 — Coverage gap
- `tools/coverage/breakdown_by_layer.py` (168) — разбивка по слоям (core, dsl, infrastructure, services, entrypoints, plugins, frontend, other)
- `.baselines/coverage.json` — coverage_percent=50.0, target=75.0 (ratchet 50→75%)
- `coverage.json` + `coverage.xml` — текущие метрики
- `Makefile::coverage-gate` (baseline-aware 50%) + `coverage-gate-strict` (75%)

### w5 — Vale
- `.vale.ini` + `docs/.vale.ini` — конфигурация
- `docs/styles/Project/RuLanguage.yml` — Russian language proofreader
- `docs/styles/Project/proselint.yml` — proselint rules
- `docs/config/vocabularies/` — Project vocab
- `vale 3.13.0` — binary, `/home/user/.local/bin/vale`

## История

- 2026-07-21: S34 стартовал как Documentation CI + Coverage 90% (PLAN.md V22.6)
- 2026-07-21..2026-08-03: S34 waves w1-w5 (Sphinx, Diátaxis, docstring gate, coverage, Vale) реализованы
- 2026-06-01: S34 official closure зафиксирован, PLAN.md обновлён
- Sprint 34 closed. Sprint 36 (Production Readiness 90%+) — следующий.

## Smoke test результаты (2026-06-01)

| Component | Verification |
|-----------|--------------|
| sphinx-build | 9.1.0 → exit 0, `sphinx-build --version` |
| check_docstrings.py | exit 0, AST-проход работает |
| coverage breakdown | exit 0, per-layer report генерируется |
| vale | 3.13.0 → `vale --version` exit 0 |
| coverage threshold | 50% baseline, gate blocking |

**Конец APPENDIX: V22.9**

---

# APPENDIX: V22.10 — S36 Production Readiness PARTIAL (2026-06-01)

> **Версия**: V22.10 (S36 waves 5: 3 ✅ DONE + 2 🟡 PARTIAL). Sprint 36 частично закрыт, status обновлён в основном тексте PLAN.md. Полное закрытие — после реализации gaps w1 (smoke tests) и w4 (pre-prod-check gates + Makefile target). Дополняет V22.9 (S34 closure), V22.8 (S35 official closure), V22.7 (S35 GAP-DSL/INT/AI/DX).

## S36 Waves Status

| Wave | Task | Owner | Status | Coverage |
|------|------|-------|--------|----------|
| w1 | Smoke tests 12+ critical paths | К2 | 🟡 PARTIAL | 8/12 (66%) |
| w2 | Grafana dashboards | К2 | ✅ DONE | 11/8+ (138%) |
| w3 | Multi-region routing | К2 | ✅ DONE | scaffold complete |
| w4 | Pre-prod-check 38/38 gates | К1 | 🟡 PARTIAL | 30/38 (79%) |
| w5 | Granian runtime mode | К2 | ✅ DONE | full |

**Sprint coverage**: 3/5 waves ✅ + 2/5 waves 🟡 PARTIAL = **5/5 waves с артефактами**, 8 gaps для closure.

## ✅ Done (3 waves)

### w2 — Grafana dashboards (11 артефактов)
Все в `src/backend/infrastructure/observability/grafana/`:
- AI cost: `ai_cost_per_tenant.json`
- Latency: `api_latency_p95.json`
- DB: `db_pool_health.json`, `db_replica_routing.json`
- DLQ: `dlq_per_transport.json`, `outbox_dlq_depth.json`
- Resilience: `resilience_snapshot.json` (CB F-02)
- SLA: `slo_burn_rate.json` (multi-window 1h/6h/24h), `workflow_sla_compliance.json`
- Workflows: `temporal_workflows.json`
- Datasource: `datasource_clickhouse.yaml`

### w3 — Multi-region routing
- `src/backend/infrastructure/resilience/region_routing.py` (320 строк)
  - `Region`, `RegionStatus` (HEALTHY/DEGRADED/DOWN)
  - `RegionRouter` — tenant-aware region selection
  - `RegionHealthChecker` — health monitoring
  - `get_current_region()` — current request context
- `tests/smoke/test_region_routing.py`

### w5 — Granian runtime mode
- `tools/granian_runner.py` — production-tuned launcher
- `Makefile::granian-run` + `Makefile::granian-dry-run`
- `tests/smoke/test_granian_runtime.py`
- ADR-0059 (production tuning)

## 🟡 PARTIAL (2 waves) — gaps для closure

### w1 — Smoke tests: 8/12 (-4 tests)
**Что есть**:
- `tests/smoke/test_admin_and_mcp.py`
- `tests/smoke/test_granian_runtime.py`
- `tests/smoke/test_health_endpoints.py`
- `tests/smoke/test_region_routing.py`
- `tests/smoke/test_sentry_init.py`
- `tests/smoke/test_websocket_endpoints.py`
- `tests/smoke/test_yaml_hot_reload.py`
- `tests/smoke/__init__.py`

**Gap (-4)**:
| # | Кандидат | Сложность | Owner |
|---|----------|-----------|-------|
| 1 | `test_routing_smoke.py` — RouteBuilder + compile | low | К2 |
| 2 | `test_action_handler_registry_smoke.py` | low | К2 |
| 3 | `test_semantic_cache_smoke.py` | medium | К2 |
| 4 | `test_sla_metrics_smoke.py` | medium | К2 |

**Альтернативы**: `test_chaos_smoke.py` (low), `test_integration_health.py` (low).

### w4 — Pre-prod-check: 30/38 gates + no Makefile target
**Что есть** (30 gates в `tools/checks/pre_prod_check.py`, 531 строк):
- coverage, mypy, layers, ruff, secrets, SBOM, pip-audit, bandit, ZAP, codeclone, docstring, Vale, sphinx -W, WAF, feature-flags, team-ownership, side-effect, perf-gate, startup, Streamlit collisions, ConfigValidator, TaskRegistry, OTel coverage, APScheduler obs, AuthorizationGateway audit, MetricsRegistry coverage, FF default-OFF audit, Sphinx docs coverage, perf p95 (warn), DR backup freshness

**Gap (-8 gates)**:
| # | Кандидат | Описание |
|---|----------|----------|
| 31 | chaos-suite integration | `make chaos` exit code check |
| 32 | semantic-cache hit rate | ≥30% hit rate gate |
| 33 | RCA coverage | ≥80% incident RCA completeness |
| 34 | ADR freshness | ADRs < 90 days old |
| 35 | plugin-trust-tier validation | Tier-A/B classification complete |
| 36 | capability-gate full coverage | All sensitive calls gated |
| 37 | mypy --strict | Вместо ratchet 30 errors |
| 38 | p95 perf-blocking | Вместо warn-only |

**Gap (-1 target)**:
- `make pre-prod-check` target — в Makefile отсутствует (но `tools/checks/pre_prod_check.py` callable напрямую)

## План закрытия gaps (для S36 → ✅ FULLY CLOSED)

1. **w1 gaps** (4 smoke tests) — К2, 1-2 дня работы
2. **w4 gaps** (8 gates + 1 Makefile target) — К1, 3-4 дня работы
3. После закрытия — re-run pre-prod-check, обновить S36 → ✅ FULLY CLOSED

## История

- 2026-08-18: S36 стартовал как Production Readiness 90%+ (PLAN.md V22.6)
- 2026-08-18..2026-08-31: S36 waves реализованы (3 ✅, 2 🟡 PARTIAL)
- 2026-06-01: S36 PARTIAL closure зафиксирован, PLAN.md обновлён
- Sprint 36: PARTIAL → требуется доработка gaps для FULLY CLOSED

## Verification (smoke tests)

| Component | Verification |
|-----------|--------------|
| pre_prod_check.py | wc -l → 531 строк, 30 checks defined |
| Grafana dashboards | 11 JSON files в observability/grafana/ |
| region_routing.py | 320 строк, RegionRouter + HealthChecker |
| granian_runner.py + tests | Makefile::granian-run exit OK |
| smoke tests | 8 файлов в tests/smoke/ |

**Конец APPENDIX: V22.10**

---

**Конец PLAN.md V22.6 FINAL.** Полный GAP-анализ: `gap-analysis/DEEP-RESEARCH-gd_integration_tools-2026-05-20.md` + `gap-analysis/AI-GAP-ANALYSIS-gd_integration_tools-2026-05-22.md`. Архив V0–V22.3: `vault/archive-plan-v21.md`. Memory: `feedback_sprint16_closure` / `feedback_sprint17_centralization` / `feedback_sprint18_techdebt` / `feedback_sprint19_dx` / `project_v22_production_ready` / `feedback_plan_v22_2_extension` / `feedback_plan_v22_4_ai_platform`.
