# PLAN.md — gd_integration_tools V22 FINAL

> **Версия**: V22.0 FINAL (production-ready roadmap, ≤ 10 недель).
> **Дата**: 2026-05-21.
> **Замещает**: V21.0 (архив → `vault/archive-plan-v21.md`).
> **Срок**: 2026-05-22 → 2026-07-31 (5 спринтов × 2 недели × 5 команд).
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

### Sprint 17 — Centralization Hardening (NEW, 2 недели: 2026-06-05 → 2026-06-18)

**Owner**: К1 (D10/D14) + К2 (D11/D13a/D13b/ResilienceCoordinator) + К3 (correlation_id) + К5 (D9 UI).
**Приоритет**: **P1** (производственная архитектура, разблокирует Sprint 20 final security audit и production-rollout).
**Источник**: GAP V3.0 D9–D14 + memory `feedback_wave_integration_pattern`.

#### Wave 0 — Backbone (обязательный pre-commit, по правилу `feedback_s2_multi_agent_kickoff`)
- `[wave:s17/backbone]` — 8 default-OFF feature-flags (`config_validator_enabled` / `metrics_registry_strict` / `task_registry_strict` / `apscheduler_metrics` / `authz_gateway_enabled` / `audit_correlation_required` / `tenant_feature_flag_ui` / `resilience_coordinator_enabled`) + team_s17.k1..k5 в `.claude/team-ownership.toml` + KNOWN_ISSUES.md секция.

#### Wave 1–8 (8 GAP V3.0 пунктов)
- `[wave:s17/k1-w1-config-validator]` — **D14**: `core/config/validator.py::ConfigValidator` — cross-settings validator при startup. ≥5 production-safety rules: DEBUG+PROD fail / CORS="*" fail / JWT_SECRET length ≥32 / Vault unreachable fail / feature-flag dependency check.
- `[wave:s17/k1-w2-authorization-gateway]` — **D10**: `core/auth/gateway.py::AuthorizationGateway.authorize(principal, resource, action)` — фасад поверх Casbin → OPA → CapabilityGate с единым `correlation_id`. Миграция всех endpoint-guard'ов на gateway. Единый audit-event на каждое решение.
- `[wave:s17/k2-w1-metrics-registry]` — **D11 backbone**: `infrastructure/observability/metrics_registry.py::MetricsRegistry.counter/histogram/gauge(name, label_set, ...)` с обязательным `{tenant_id, route_id, component, env}`. Idempotent registration (для hot-reload плагинов). Registry-singleton + initial 5 reference metrics.
- `[wave:s17/k2-w2-metrics-migrate]` — **D11 sweep**: миграция 52 inline `= Counter(...) / = Histogram(...) / = Gauge(...)` callsites на `MetricsRegistry.get_*()`. CI-gate `tools/checks/check_metrics_registry.py`.
- `[wave:s17/k2-w3-task-registry-coverage]` — **D13a**: миграция 34 orphan `asyncio.create_task(...)` callsites на `task_registry.create_task(name, deadline, lifecycle)`. CI-gate `tools/checks/check_task_registry.py --fail-on-orphans`. `copy_context()` propagation для structlog в background tasks (correlation_id в task-логах).
- `[wave:s17/k2-w4-apscheduler-observability]` — **D13b**: Prometheus metrics `scheduler_job_executions_total{status="success|missed|error"}` + `scheduler_job_duration_seconds` + `scheduler_jobstore_type{type="memory|sqlalchemy"}`. Grafana alert при `status="missed" > 0` и при `type="memory"` в prod.
- `[wave:s17/k3-w1-correlation-id-end-to-end]` — **D12**: contextvars propagation через middleware → audit → outbound_http → DSL processors. AuditService обязательно содержит `correlation_id` из contextvars. End-to-end test: HTTP request → workflow → outbound HTTP → ClickHouse audit_events; единый запрос `SELECT * FROM audit WHERE correlation_id = X` возвращает события от ≥3 источников.
- `[wave:s17/k5-w1-tenant-runtime-feature-toggle]` — **D9**: REST endpoint `POST /admin/feature-flags/<flag>/tenant/<id>` + Redis pub/sub broadcast (<100ms propagation) + audit trail (event `feature.toggled` с actor/value/old_value/correlation_id). Streamlit page `61_Feature_Flags.py` (или эквивалент с учётом текущего page-numbering).
- `[wave:s17/k2-w5-resilience-coordinator-class]` — `core/resilience/coordinator.py::ResilienceCoordinator` class. 12 fallback chains (antivirus / audit / cache / db / express / mongo / mq / object_storage / search / secrets / smtp / graylog / genai) wired через registry. Init в lifespan startup. Метрики через `MetricsRegistry`.

#### Closure
- `[wave:s17/closure]` — DoD grep verify + memory `feedback_sprint17_centralization` + CONTEXT.md update.

**DoD Sprint 17 (10 критериев)**:
1. ✅ `[wave:s17/backbone]` landed: 8 default-OFF flags + team_s17.k1..k5.
2. ✅ ConfigValidator валидирует ≥5 rules при startup; `APP_PROFILE=prod DEBUG=true uv run python -m src.backend.main` fail-fast с CRITICAL.
3. ✅ AuthorizationGateway покрывает 100% non-public endpoints; `grep "if request.user.is_admin"` ad-hoc auth = 0.
4. ✅ MetricsRegistry содержит ≥50 регистрированных метрик; `grep -rn "= Counter(\|= Histogram(" src/backend/` (вне registry) → **0**.
5. ✅ `tools/checks/check_task_registry.py` зелёный; `grep -rn "asyncio.create_task" src/ | grep -v task_registry` → **0**.
6. ✅ APScheduler exporter: `scheduler_job_executions_total` visible в Prometheus; alert правила в `ops/grafana/alerts/scheduler.yml`.
7. ✅ correlation_id присутствует во всех audit events (ClickHouse query verify); `tools/checks/check_correlation_id.py` зелёный.
8. ✅ Per-tenant feature toggle через UI; audit-event записан; Redis pub/sub broadcast подтверждён в integration test (<100ms).
9. ✅ ResilienceCoordinator класс инициализируется в lifespan; 12 fallback chains зарегистрированы; smoke-test для каждого backend.
10. ✅ coverage ≥77% (от 75% gate); mypy 0 сохранён; layer violations 0 сохранён; memory note `feedback_sprint17_centralization`.

---

### Sprint 18 — Tech Debt + Acceptance (2 недели: 2026-06-19 → 2026-07-02)

**Owner**: К1 (WAF + supply-chain) / К2 (Coverage + failing tests + F-2 sandbox) / К3 (Core entities + EventBus DSL) / К4 (AI handlers + LangFuse + multimodal-rag) / К5 (F-5 stubs + Layer violations Protocol-extraction).
**Приоритет**: **P1** (techdebt cleanup + acceptance carryover; разблокирует Sprint 20 strict gates).
**ВАЖНО (clarification 2026-05-21)**: credit-pipeline 5 интеграционных клиентов (DaData/БКИ/СМЭВ/ЦБ/1С) — **НЕ В ЭТОМ ПЛАНЕ**. Пользователь делает отдельно.

#### Wave 0 — Backbone
- `[wave:s18/backbone]` — 6 default-OFF feature-flags (`waf_strict_zero_allowlist` / `failing_tests_quarantined_off` / `sandbox_amortised_final` / `core_entities_legacy_off` / `eventbus_dsl_enabled` / `langfuse_production_wired`) + team_s18.k1..k5.

#### Wave 1–12 (4 техдолг + 4 carryover + 3 routes verify + 1 closure)
- `[wave:s18/k1-w1-waf-allowlist-tightening]` — миграция оставшихся 23 callsites в `tools/check_waf_coverage_allowlist.txt` на `make_http_client()`. Список: express_bot / telegram_bot / opa / clickhouse / vault_cipher / ml_inference / proxy/forward / imports endpoint / webhook handler/transformer / search_providers / Vault×2 / bots×2.
- `[wave:s18/k1-w2-supply-chain-finale]` — SBOM CycloneDX + cosign sign + pip-audit zero HIGH/CRITICAL; secrets-check zero-tolerance; `make security` exit 0.
- `[wave:s18/k2-w1-coverage-ramp-70]` — ratchet coverage 50→70%; coverage breakdown by layer; команды добавляют тесты в свои зоны (К1 security 75%+, К2 resilience 80%+, К3 dsl 75%+, К4 ai 65%+, К5 frontend 60%+).
- `[wave:s18/k2-w2-failing-tests-triage]` — разобрать ~91 pre-existing failing tests (S9 audit); либо fix, либо `xfail` с явным ADR / skip с feature-flag.
- `[wave:s18/k2-w3-sandbox-f2-final]` — **F-2 carryover**: PluginSandboxAdapter overhead 137% → <5%. Strategy decision per ADR R1.20: amortised psutil snapshot (раз в N вызовов) / fire-and-forget task / e2b enforcement / DoD relaxation для dev_light.
- `[wave:s18/k3-w1-core-entities-final-cleanup]` — удалить `src/backend/services/core/{users.py,orders.py,orderkinds.py}` legacy остатки. Все импортёры переключаются на `extensions/core_entities/`. `grep "from gd_integration_tools.services.core.(users\|orders\|orderkinds)"` → 0.
- `[wave:s18/k3-w2-eventbus-dsl-methods]` — `RouteBuilder.to_eventbus(topic, payload_ref)` + `.from_eventbus(topic_pattern, ack_mode)` + 2 new step-type в `dsl/engine/processors/eventbus.py`. `make routes` показывает 2 новых step-type.
- `[wave:s18/k4-w1-ai-workflow-handlers]` — bound handlers в `services/ai/workflows/{rag_query,multi_agent_supervisor,e2b_execute}.py` для 3 yaml templates (`extensions/credit_pipeline/workflows/` существующих). LangFuse production wiring через `LangfusePromptStorage` + prompt versioning + cost tracking dashboard.
- `[wave:s18/k4-w2-multimodal-rag-pipeline]` — **S11 K4 W2 carryover**: full pipeline ingest → chunking → embedding → Qdrant (modal payload) → retrieval → rerank → LLM context. Очистка untracked WIP + commit с regression-tests.
- `[wave:s18/k5-w1-pyi-stub-fidelity]` — **F-5 carryover**: `tools/gen_dsl_stubs._resolve_annotation` через `typing.get_type_hints` + `get_origin/get_args`. PEP-695 fidelity для `.pyi` (`TypeAlias`, type-parameters).
- `[wave:s18/k5-w2-layer-violations-protocol-extraction]` — Layer violations 73 → 0. Protocol-extraction: composition-root из `core/` в `infrastructure/` + DI binding в svcs_registry. Allowlist пуст. `make layers` (strict, без `--use-allowlist`) zero-error.
- `[wave:s18/verify-routes-integration]` — Integration verification трёх existing routes (`routes/health_proxy_demo/`, `routes/echo_demo/`, и CRUD routes из `extensions/core_entities/`) с новым функционалом ConfigValidator + MetricsRegistry + EventBus DSL + TaskRegistry. Testcontainers (PG/Redis/MinIO/Temporal) + mock backend (DaData/СКБ-Техно если есть) + 5+ assertion checkpoint на каждый route (auth / config-validation / metrics-emission / correlation-id propagation / fallback-chain).

#### Closure
- `[wave:s18/closure]` — DoD verify + memory `feedback_sprint18_techdebt`.

**DoD Sprint 18 (12 критериев)**:
1. ✅ `[wave:s18/backbone]` landed.
2. ✅ WAF allowlist пуст: `tools/check_waf_coverage_allowlist.txt` = 0 lines (production paths); `python tools/check_waf_coverage.py --strict` zero violations.
3. ✅ Supply-chain: `make security` exit 0 (SBOM + cosign verify + pip-audit zero HIGH).
4. ✅ Coverage ≥70%; per-layer breakdown отчёт; pre-existing failing tests = 0 (fix или quarantined с ADR).
5. ✅ F-2 sandbox: overhead <5% (или ADR R1.20 relaxation для dev_light); `tests/perf/test_plugin_sandbox_overhead.py` зелёный.
6. ✅ 0 файлов `users.py/orders.py/orderkinds.py` в `src/backend/services/core/`; `make layers` зелёный.
7. ✅ `RouteBuilder.to_eventbus()` + `.from_eventbus()` доступны; `make routes` показывает 2 новых step-type.
8. ✅ 3 AI workflow handlers in production: `services/ai/workflows/{rag_query,multi_agent_supervisor,e2b_execute}.py`; LangFuse cost tracking dashboard работает; prompt v1 visible.
9. ✅ Multimodal RAG pipeline проходит regression-test (PDF+image+audio ingest → cross-modal retrieval).
10. ✅ F-5 `.pyi` stubs covers 100% public DSL API; PEP-695 type-parameters resolved корректно.
11. ✅ Layer violations 0 (`make layers` strict, без allowlist); Protocol-extraction wave документирован.
12. ✅ Verification routes: 3 existing routes (СКБ-Техно если есть / DaData / CRUD) проходят integration smoke с новым функционалом; assertion checkpoints зелёные.

---

### Sprint 19 — DX & Innovation (2 недели: 2026-07-03 → 2026-07-16)

**Owner**: К3 (LSP финал + Visual Editor) / К4 (AI PR review + Adaptive RAG strategy finale) / К5 (VSCode extension + Quick wins + Arch Map) / К2 (Adaptive timeout + Coverage ratchet) / К1 (F-6 sys._current_frames).
**Приоритет**: **P2** (innovation + DX; не блокирует production, но даёт финальный signoff + developer experience baseline для onboarding ≤ 1 час).

#### Wave 0 — Backbone
- `[wave:s19/backbone]` — 5 default-OFF feature-flags (`vscode_extension_published` / `lsp_server_strict` / `dsl_visual_editor_drag_drop` / `ai_pr_review_enabled` / `adaptive_timeout_enabled`) + team_s19.k1..k5.

#### Wave 1–12 (4 DX + 4 carryover + 4 ADR-закрытие + closure)
- `[wave:s19/k5-w1-vscode-extension]` — `tools/vscode-extension/` `.vsix` пакет: syntax highlighting + hover docs + "Run step" CodeLens + LSP client (подключается к S16 K3 W1 server). Private marketplace publish (ADR R1.14 → private).
- `[wave:s19/k3-w1-lsp-server-finale]` — расширение `tools/dsl_lsp/server.py` (S16 baseline): YAML schema completion через JSON Schema export для route.toml + workflow.yaml + service.toml; diagnostics через DSL Linter integration.
- `[wave:s19/k3-w2-dsl-visual-editor-finale]` — `frontend/streamlit_app/pages/31_DSL_Visual_Editor.py` финал: drag-drop + YAML/BPMN export + undo/redo + step palette с capability descriptions. Закрывает S9 carryover.
- `[wave:s19/k4-w1-ai-pr-review-action]` — `.github/workflows/ai-pr-review.yml` через Claude API: layer-policy + security + perf-regression + coverage delta. Prompt caching ≥80% hit rate; latency ≤3 минут per PR; cost ≤$0.10 per PR.
- `[wave:s19/k5-w2-quick-wins-pack]` — пакет 4 quick wins за 1 wave: `make new-adr TITLE="..."` (ADR scaffolding + auto-number) + `manage.py completions install` (zsh+bash auto-gen Typer) + `make release-notes` (Conventional Commits parser, changelog между tags) + `frontend/streamlit_app/pages/05_Architecture_Map.py` (D3.js, нажать модуль → docstring + deps + tests + impact analysis).
- `[wave:s19/k2-w1-manage-py-diagnose]` — `manage.py diagnose` aggregator (dep graph + cycles + layer-viol + dead code + unused features). JSON output для CI integration. Single-command pre-prod-check.
- `[wave:s19/k1-w1-current-frames-fallback]` — **F-6 carryover**: `infrastructure/observability/plugin_resource_monitor._collect_cpu_share` через `sys._current_frames()` с graceful PyPy/Jython fallback (return `{}`). Best-effort attribution.
- `[wave:s19/k2-w2-adaptive-timeout-policy]` — `.policy.adaptive_timeout(percentile=99, safety_factor=1.5)` builder API + per-host p99 tracking + Prometheus metric + 5 reference routes.
- `[wave:s19/k4-w2-adaptive-rag-strategy-finale]` — расширение S16 K4 W1 (QueryClassifier) до production: динамический выбор strategy (dense/hybrid/hyde/multi_query) через LLM-classifier + accuracy +15% bench + latency overhead < 50ms.
- `[wave:s19/k2-w3-coverage-ratchet-75]` — ratchet 70→75% checkpoint; per-layer enforcement.
- `[wave:s19/adr-w1-r1-1-r1-5-r1-7]` — финализация **ADR R1.1** (plugin.toml capability synthax) + **R1.5** (SLO формат) + **R1.7** (Single Entry policy naming).
- `[wave:s19/adr-w2-r1-8-r1-9-r1-20]` — финализация **ADR R1.8** (EventBus production backend: NATS vs Kafka vs RabbitMQ) + **R1.9** (Granian RSGI vs Uvicorn benchmark + decision) + **R1.20** (F-2 PluginSandboxAdapter final strategy).

#### Closure
- `[wave:s19/closure]` — DoD verify + memory `feedback_sprint19_dx`.

**DoD Sprint 19 (12 критериев)**:
1. ✅ VSCode extension `.vsix` published; completion + hover + Run step CodeLens работают; private marketplace доступен команде.
2. ✅ LSP server финал: YAML schema completion + diagnostics; integration test через pygls test-client.
3. ✅ DSL Visual Editor финал: drag-drop + BPMN export + undo/redo passes Playwright e2e.
4. ✅ AI PR review активен; runs on every PR; cache hit ≥80%; cost ≤$0.10/PR; finding-report attached.
5. ✅ Quick wins: `make new-adr` создаёт ADR-NNNN; `manage.py completions install` работает zsh+bash; `make release-notes` собирает changelog; Arch Map D3.js renders.
6. ✅ `manage.py diagnose` aggregator: JSON output; CI-integration; 0 findings на чистом master.
7. ✅ F-6 `sys._current_frames` graceful fallback; PyPy smoke-test return `{}`.
8. ✅ `.policy.adaptive_timeout()` доступен; 5 reference routes использует; per-host p99 metric visible.
9. ✅ Adaptive RAG strategy: динамика работает; bench accuracy +15% vs static; latency <50ms.
10. ✅ Coverage ≥75% ratchet checkpoint passed.
11. ✅ ADR R1.1 / R1.5 / R1.7 / R1.8 / R1.9 / R1.20 — Status: Accepted в `docs/adr/`.
12. ✅ Memory note `feedback_sprint19_dx`.

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
| **Streamlit pages** | 71 | 80+ | S17 +1 / S18 +5 / S19 +3 |
| **DSL processors** | 108 | 115+ | S16–S18 |
| **Tutorials** | 9 | **15+** | S20 W5 docs-finale |
| **Runbooks** | 10 | **20+** | S20 W5 |
| **Chaos tests** | 33 | **33+** | S20 W6 (S6 baseline сохранён) |
| **Feature-flags default-OFF** | 159 | **flip ~20 → default-ON** перед release | S20 W6 flip-plan |
| **Pre-prod-check gates** | 20 | **38** (20+10+8 grep) | S20 W6 |

---

## 9. Post-release backlog (отрезано из V22, для S21+)

- DI container migration (`core/di/providers.py` → `dependency-injector`) — ADR R1.10 defer.
- mem0/Zep persistent personalisation (innovation).
- Free-threading PEP 703 benchmark (research).
- VSCode extension public marketplace publish (private достаточно для V22).
- Адаптивный RAG strategy ML-классификатор (replaces LLM-classifier в S19).
- Multi-tenant cache invalidation через Redis pub/sub (расширение D9).
- Sphinx multi-version (для каждой минорной версии — defer).
- Vale prose linter custom rules per-language (defer).
- Interactive Architecture Map LLM search.

---

**Конец PLAN.md V22 FINAL.** Полный GAP-анализ: `gap-analysis/DEEP-RESEARCH-gd_integration_tools-2026-05-20.md`. Архив V0–V21: `vault/archive-plan-v21.md`. Memory: `feedback_sprint16_closure` / `feedback_sprint17_centralization` / `feedback_sprint18_techdebt` / `feedback_sprint19_dx` / `project_v22_production_ready`.
