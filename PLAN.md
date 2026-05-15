# PLAN.md — gd_integration_tools

> **Версия**: V18.2 FINAL (V18.1 + Sprint 6 запуск 5-команд параллельно с Sprint 5/Sprint 7, 2026-05-14).
> **Дата**: 2026-05-14 (предыдущая V18.1 — 2026-05-12).
> **Sprint 6 запуск note** (2026-05-14): K1 Security / K2 Resilience+Perf / K3 DSL+Workflow / K4 AI+Quality / K5 Frontend+Chaos запущены параллельно через worktree-isolation. Полный план — `~/.claude/plans/effervescent-herding-fairy.md`. Backbone-commit `[wave:s6/backbone]` фиксирует 21 default-OFF feature-flag и ownership-список в `.claude/team-ownership.toml::[team_s6.kN]`. Sprint 6 идёт параллельно с Sprint 5 (Outbox/Tenacity/TaskIQ removal — параллельная команда) и Sprint 7 (T1-T5 миграция core_entities + credit_pipeline). Stub/adapter паттерн для S5→S6 зависимостей. Уже закрыты досрочно: `[wave:s6/msgspec-benchmark]` (`3743c574`) + `[wave:s6/layer-violations-facade]` (`6b818829`).
> **Срок**: 11–12 недель (≈3 месяца) при **5 параллельных командах** разработки.
> **Замещает**: V17.0 (3 команды) и V16.1 (отсутствие статус-матрицы).
> **Синхронизирован с**: `CLAUDE.md` V15, GAP-анализ V3 (`gap-analysis/`, 2026-05-08), вейв-коммиты K1/S1 + S4/K3-D + S5/K4-MVP (2026-05-08).
> **V18 правки** (2026-05-08): (1) 3 команды → 5 (Backbone разделён на К1 Security + К2 Resilience+Perf; AI/Frontend разделён на К4 AI+RAG + К5 Frontend+Extensions+Migrations); (2) §2.5 — матрица wave × status × owner; (3) §2.7 — shared-файлы + Pre-flight protocol; (4) inline статус-маркеры ✅/🟡/⛔/⏳/🚫 во всех Sprint-таблицах; (5) ссылки на коммиты для всех закрытых wave; (6) §11 Changelog V16→V17→V18.

---

## 0. Контекст и видение

`gd_integration_tools` — **универсальная интеграционная шина** (Integration Platform) на Python 3.14+ (Apache-Camel + Airflow-style + Temporal). Выступает «руками» кредитного конвейера: разгружает его, беря на себя интеграционную, трансформационную и оркестрационную логику.

**Полностью готов** означает (acceptance):
- DSL протоколы: REST / SOAP / FTP / SFTP / gRPC / OLE-COM / Web / Email / CDC / Watchdog — вызов в workflow.
- RPA-действия: web-поиск / скрипты / файлы / desktop.
- AI-агенты: граф, промпты, RAG CRUD, память, MCP.
- Регистрация эндпоинтов с WSDL/XSD/OpenAPI; вызовы по REST/SOAP/Event/WebSocket/Webhook.
- Workflow с XOR/AND/OR ветвлениями, сигналами, HITL, YAML round-trip, обратной совместимостью; legacy workflow мигрированы.
- CRUD DSL с override-методами и автоматической регистрацией.
- DSL вызовов с кэшированием, циклом, retry с backoff, invocation modes.
- DSL конверсии, валидации, агрегации, разделения, перехвата ошибок.
- DSL CDC, Watchdog, внешние БД + процедуры, аналитические БД.
- Параметры вызова с переопределением дефолтов (таймауты, политики).
- Слои интеграция / сервисы / репозитории — для ядра и для extensions.
- Единый фасад (мульти-тенант), переключение бэкендов (Redis↔KeyDB, Postgres↔Oracle).
- Фасад над Temporal.
- Быстродействие: пулы соединений, алерты, быстрые библиотеки, потоки, async, Dask для тяжёлых вычислений.
- Ядро domain-agnostic; бизнес-логика в `extensions/`; каждый эндпоинт в своей директории.
- Кодогенерация репозиториев, сервисов, схем.
- Документация и Wiki; CI-проверки на новые функции (docstrings).
- Фронт: wiki, логи, workflow-схемы, визуализация выполнения, S3-файлы.
- Быстрые middleware. Feature flags.
- Импорт схем WSDL/REST и кодогенерация клиента.

**Принцип**: без оверинжиниринга, сокращение кастомного кода в пользу библиотек, богатые возможности, чёткое разделение по слоям.

После Wave R3.10 (2026-05-05): `src/backend/` (бэк) + `src/frontend/` (фронт). Plugin contract V11.1, Wave C/D (Workflow Protocol + Temporal backend), R2 universal blocks, R3.0+ закрыты. На 2026-05-08 закрыты K1/S1 Security backbone (8 wave-коммитов), S5/K4 MVP AI Stack 2026 (58 тестов), S4/K3-D compiler+saga scaffolding.

---

## 1. Принципы (неизменные V15.1 + V17)

### 1.1. Single Entry per Cross-Cutting Concern (V15.1)

```
ResilienceCoordinator
├── CircuitBreaker  (один класс; resource-adapter HTTP/DB/Redis/MQ/Activity)
├── RateLimiter     (pluggable backend memory|redis-cluster; per-resource + per-tenant + per-function)
├── Retry           (через tenacity; per-resource policy)
├── Bulkhead, TimeLimit, Reconnection
├── Cache           (L1 exact / L2 semantic / L3 retrieval + function-level decorators)
└── FallbackChains/ (12: antivirus/audit/cache/db/express/mongo/mq/object_storage/search/secrets/smtp/graylog/genai)
```

Два уровня применения политик:
- **DSL-уровень**: `.policy.cache(ttl).policy.circuit_breaker(name).policy.rate_limit(n)`
- **Функциональный уровень** (декораторы для бизнес-функций в extensions/):
  ```python
  @policy(circuit_breaker="bki", rate_limit="bki", cache={"ttl": 300, "key": "bki:{args[0]}"})
  async def query_bki(inn: str) -> BkiResponse: ...
  ```

Внутри Temporal workflow — Temporal-native механизмы (`activity_options.retry_policy`, `start_to_close_timeout`, saga-compensation), не дублируются resilience-layer'ом.

### 1.2. Граница «ядро / extensions»

- **Ядро** (`src/backend/`) = DSL движок + инфрасервисы. **Domain-agnostic**.
- **`extensions/<name>/`** = бизнес-логика. Каждый эндпоинт — в своей директории (`features/<name>/`).
- Импорт-policy: `extensions/` → только `gd_integration_tools.{core, testkit}` + capability-checked фасады.
- CI-gate: `tools/checks/check_layers.py --strict-extensions`.

### 1.3. DSL dual-mode + 80/20

- YAML (`route.toml + *.dsl.yaml`) **И** Python `RouteBuilder`. Равноправно.
- **YAML↔Python round-trip**: `WorkflowBuilder.to_yaml()` / `WorkflowSpec.from_yaml()` / `diff()`.
- **Hot Reload без рестарта**: изменение `route.toml` → подхватывается < 3 сек без SIGTERM.

### 1.4. Auto-registration во всех протоколах

`@service_dsl(protocols=["all"])` → REST + SOAP + XML + gRPC + GraphQL + MQ + WS + SSE + MCP + MQTT.

### 1.5. ADR R1.6 — Hybrid plugin layout

```
extensions/<plugin>/
├── plugin.toml
├── plugin.py
├── shared/                  # cross-feature
│   ├── domain/models.py
│   ├── repositories/
│   └── migrations/
└── features/
    └── <feature_name>/
        ├── route.toml
        ├── service.py
        ├── schemas.py
        ├── fixtures/
        └── *_test.py
```

### 1.6. Стандарты кода (V17 новые)

- `asyncio.TaskGroup` вместо `asyncio.gather` (structured concurrency).
- Lazy import для всех AI/тяжёлых библиотек: паттерн `_ensure_<lib>()`.
- `msgspec.Struct` для internal DTO в hot-path; Pydantic — для API schemas и plugin contracts.
- Railway-oriented programming: `Result[T, E]` для бизнес-ошибок без try/except каскадов.

### 1.7. EventBus Facade (V17)

```python
from gd_integration_tools.core.messaging import EventBus

bus = EventBus.get()
await bus.publish("credit.application.created", payload)
await bus.subscribe("credit.#", handler)
```

Backends: `KafkaEventBusBackend` / `RabbitMQEventBusBackend` / `NATSJetStreamEventBusBackend`.
DSL: `.to_eventbus(topic)` / `.from_eventbus(topic_pattern)`.

---

## 2. Команды разработки (5)

| Команда | Зона ответственности | Owns каталоги | Запрещено трогать |
|---|---|---|---|
| **К1 Security** | Auth, Capabilities, WAF, Secrets, AI Safety, PII, Supply-chain, mTLS/SAML, e2b/sandbox | `core/security/`, `core/auth/`, `core/ai/{workspace_manager,fs_facade,sandbox}.py`, `core/net/{waf,outbound_http}.py`, `infrastructure/secrets/`, `infrastructure/security/`, `infrastructure/ai/e2b_sandbox.py`, `infrastructure/observability/{pii_filter,sentry_init}.py`, `tools/check_waf_coverage*`, `Makefile.security`, `docs/adr/0050-*` | `dsl/`, `services/ai/`, `frontend/`, `extensions/` |
| **К2 Resilience+Perf** | Single Entry CB/RL/Retry, TaskRegistry, Watchdog, ConnectionReuseManager, OTel, ClickHouse/Graylog/Redis/HTTP pools, Auto-scaling, Outbox/Inbox, Backpressure, msgspec hotpath, Granian ADR | `core/resilience/`, `core/scaling/`, `core/messaging/outbox.py`, `core/utils/task_registry.py`, `infrastructure/resilience/`, `infrastructure/observability/{otel_*,task_registry,watchdog}.py`, `infrastructure/clients/transport/`, `infrastructure/cache/` (кроме `rag/` от К4), `infrastructure/logging/`, `infrastructure/messaging/{outbox,inbox}_*.py`, `infrastructure/clients/storage/redis.py`, `tests/perf/`, `tests/chaos/` | `dsl/`, `services/ai/`, `frontend/`, `extensions/` |
| **К3 DSL+Workflow** | Builder split, Workflow DSL+compiler, Temporal, Sources/Sinks/Processors, EventBus, BPMN import, ProcessorRegistry, Schema-registry, Hot Reload, Routes, Auto-reg, Convert/Gateway/Audit/Notify DSL, RPA Playwright | `dsl/`, `entrypoints/` (кроме `entrypoints/api/v1/endpoints/admin_*` и `mcp/` от К4), `services/schema_registry/`, `services/execution/`, `infrastructure/workflow/`, `infrastructure/sources/`, `infrastructure/sinks/`, `infrastructure/scheduler/`, `infrastructure/eventbus/` (NEW), `routes/`, `tools/codegen/`, `tools/schema_importer/` (recreate), `tools/dsl/` | `core/security/`, `services/ai/`, `frontend/`, `extensions/` |
| **К4 AI+RAG** | services/ai/ полностью, MCP, RAG cache, LangMem, PydanticAI, LiteLLM gateway, StreamingLLM, AI cost dashboard, embedding registry, AI workflow activities, RAG ingest/admin endpoints | `services/ai/`, `core/config/{ai,ai_2026,rag}.py`, `infrastructure/cache/rag/`, `entrypoints/api/v1/endpoints/{rag_cache_admin,rag_ingest,ai_*}.py`, `entrypoints/mcp/`, `dsl/engine/processors/{ai*,streaming_llm,llm_*}.py`, `plugins/composition/setup_ai_2026.py` | `core/security/`, `core/resilience/`, `frontend/streamlit_app/pages/` (кроме AI/RAG страниц 20/30/40/50/74/75) |
| **К5 Frontend+Ext+Mig** | Streamlit (все страницы), api_client, codegen plugins, миграция core_entities/credit_pipeline в extensions/, Admin UI (sqladmin), S3 Files UI, схема SAP/EDI коннекторов | `frontend/`, `extensions/`, `tools/codegen/codegen_plugin.py`, `tools/codegen/codegen_proto.py`, `tools/templates/`, `entrypoints/api/v1/endpoints/admin_*` (новые admin-routers), `services/admin/` (временно до миграции в extensions/core_entities/admin/) | `core/`, `dsl/`, `services/ai/` |

### Coverage ramp-up по спринтам (V17 §7)

`Sprint 1 ≥20% / S2 ≥25% / S3 ≥35% / S4 ≥50% / S5 ≥60% / S6 ≥70% (gate)`.

---

## 2.5. Статус волн (snapshot 2026-05-08)

Легенда: ✅ Closed | 🟡 In-progress | ⛔ Blocker | ⏳ Pending | 🚫 Skipped.

### Sprint 0 hotfix-неделя

| Wave | Status | Owner | Ref |
|---|---|---|---|
| `B.0 codeclone setup` | ✅ | К3 | CONTEXT.md |
| Day 1-2 пустые каталоги (10) | 🟡 | К1+К3 | частично; audit нужен |
| Day 1-2 frontend leftover | 🟡 | К5 | `923859d` (часть mv); финальная сверка нужна |
| Day 2-3 antivirus dedup | ✅ | К1 | `eaf0420` |
| Day 2-3 codecs/converters | ✅ | К3 | `7ce1421`, `8c81fba` |
| Day 2-3 tools split (dsl_cli) | ✅ | К3 | `9d03f0a`, `39e7c4f` |
| Day 2-3 api_management split | ✅ | К1 | `6cf53a7` |
| Day 2-3 утилиты merge | ✅ | К2 | `41c2b92`, `787e777` |
| Day 3-4 ClickHouse pool | ✅ | К2 | `945758f`, `83d0014` |
| Day 3-4 Graylog persistent | ✅ | К2 | `40e933a`, `34b4b8a` |
| Day 3-4 orjson hotpath sweep | ✅ | К2 | `d503a98`, `a10b7ae` |
| Day 3-4 Redis cluster + pipelining | ⏳ | К2 | pending |
| Day 4-5 idempotency-header | ✅ | К1 | `efb92f1` |
| Day 4-5 fastapi-easylimiter | ✅ | К1 | `bd2c49f`, `7951eaa` |
| Day 4-5 correlation-id | ✅ | К1 | `efb92f1` |
| Day 4-5 advanced-alchemy | ✅ | К2 | vault 2026-05-08-1911 |
| Day 4-5 tenacity unification | 🟡 | К2 | partial; Step 3.3 deferred |
| Day 4-5 standardwebhooks | ⏳ | К1 | escalated to Sprint 2 |
| Day 4-5 ASGI body capture opt-in | ⏳ | К1 | pending |
| #14 TaskIQ removal | ⛔ | К2 | escalated to Sprint 5 (`[wave:s5/async-queue-migrate]`) |
| Day 5 OpenFeature InMemoryProvider | ⏳ | К1 | V17 NEW |
| Day 5 Smoke CI stage | ⏳ | К2 | V17 NEW |
| Day 5 Workflow legacy mark | ✅ | К3 | `764ec37`, `96d3370` |
| Day 5 Python-2 except syntax | ✅ | К3 | `4f7327a`, `ea14cf2` (35+1 файлов) |
| TenantMiddleware register | ✅ | К1 | `89b6a2a` |

### Sprint 1 — Resilience + Plugin Contract + Стандарты кода V17

#### К1 Security
| Wave | Status | Ref |
|---|---|---|
| Capability `fs.create_new` + `code.execute` | ✅ | `8114b14` |
| VaultSecretsBackend hvac KV v2 | ✅ | `0671af8` |
| HttpxClient mTLS | ✅ | `e017e51` |
| `register_waf_policy` + DI factory | ✅ | `96b9eda` |
| `BaseExternalAPIClient` feature-flag миграция | ✅ | `8c43219` |
| `register_ai_safety` + lifespan | ✅ | `6aed506` |
| E2B sandbox protocol + NoOp + Impl | ✅ | `600247c` |
| ADR-0050 + Makefile ci/pr targets | ✅ | `e59c71a` |
| Phase-2 `WAF_OUTBOUND_VIA_FACADE=True` (allowlist 38 callsites) | 🟡 | flag default-OFF; pending K2-K5 ack |

#### К2 Resilience+Perf
| Wave | Status | Ref |
|---|---|---|
| Canonical CB/Retry/RateLimiter в `core/resilience/` | ✅ | `672b40f` |
| `pyrate_compat` + BoundedInMemoryBucket | ✅ | `e07000b` |
| Single Entry callsite миграция (Step 3.3 Phase 2) | 🟡 | KNOWN_ISSUES.md (12 callsites через aliases) |
| TaskRegistry + Watchdog + tests | ✅ | `1e3d107` |
| TaskRegistry register в lifecycle + Leaker | ✅ | `2a6a048` |
| Wrap 51 `asyncio.create_task` callsites | ✅ | `9b8440c` |
| OTel auto-instrumentation (asyncpg) | 🟡 | KNOWN_ISSUES.md Step 2.3 (working tree) |
| OTel auto-instrumentation расширение (httpx/redis/sqlalchemy) | ⏳ | pending |
| aiocache evaluation | ⏳ | pending |
| Workflow legacy purge | ⛔ | KNOWN_ISSUES.md Step 2.2 → Sprint 4 |
| `[wave:s1/k2-1-cache-decorator]` in-house `@cached/@invalidate/@multi_cached` (ADR-0051) | ✅ | `core/resilience/cache_decorators.py` + 11 unit-тестов; aiocache отклонён в пользу in-house decorator |
| `[wave:s1/k2-2-policy-decorator]` `@policy(cb, rl, retry, cache)` (ADR-0052) | ✅ | `core/resilience/decorators.py` + 7 unit-тестов; канонический порядок outer→inner |
| `[wave:s1/asyncio-taskgroup]` migration в DSL-процессорах | ⏳ | V17 NEW |
| `[wave:s1/result-monad]` `result>=0.17.0` + `ResultUnwrapProcessor` | ⏳ | V17 NEW |

#### К3 DSL+Workflow
| Wave | Status | Ref |
|---|---|---|
| `builder.py` split — Stage 0/1 skeleton + 2.1 converters PoC | ✅ | `84fd363` (stage-0-1-2.1, 5-method PoC) |
| `builder.py` split — Stage 2.2 AI/RPA → `builders/ai_rpa.py` (484 LOC) | ✅ | `63fb43e` |
| `builder.py` split — Stage 2.3 EIP → `builders/eip.py` (919 LOC) | ✅ | `5a1f45d` |
| `builder.py` split — Stage 2.4 control_flow → `builders/control_flow.py` (292 LOC, 17 методов) | ✅ | `300d573` (2026-05-12) |
| `builder.py` split — Stage 2.5 integration (~28 методов: proxy/redirect/entity_*/audit/scan/http_call/db_*/read_*/write_*/timer/poll/notify/file_move/shell/email/jwt_*/webhook_*) | ⏳ | план готов; builder.py остаток ~1401 LOC / 68 методов после 2.4 |
| `builder.py` split — Stage 2.6 operational (~27 методов: with_*/set_*/require_*/shadow_mode/bulkhead/lineage/ab_test/feature_flag_branch/deadline/tenant_scope/cost_tracker/outbox/mask/compliance_labels/dispatch_action/invoke/log/validate/auth/to_route/feature_flag) | ⏳ | план готов; новый файл `builders/operational.py` |
| ProcessorRegistry formal API (`@processor`) | ✅ | `8e734be` (stage-3) |
| JSON-Schema export | ⏳ | pending |
| Schema-registry RAM + REST `/api/v1/admin/schemas` | ⏳ | pending |
| `.crud_*` builder + `.call_function` + capability check | ⏳ | pending |
| ResponseValidatorProcessor + `.get_setting()` | ⏳ | pending |
| EventBus facade (Kafka/RabbitMQ/NATS JetStream) | ⏳ | V17 NEW |
| `.convert(target_type)` unified DSL-step | ⏳ | V17 NEW |
| MQTT sink + EmailSource + plugin marketplace + frontend pages auto-discovery | ✅ | `2198eaa`, `bf5b9fe` |
| Workflow Spec Pydantic + WorkflowBuilder + SagaBuilder | ✅ | `4ab3e98`, `b5d8ba2`, `c19a85c` |
| Workflow Compiler emitter/step_compilers/activity_bridge/registry (59 tests) | ✅ | `2e4d135` |
| LiteTemporalBackend (124 LOC + 7 smoke tests) | ✅ | `bdd6505` + scaffold pre-session |

#### К4 AI+RAG
| Wave | Status | Ref |
|---|---|---|
| AIWorkspaceManager + AIFsFacade (workspace TTL + audit + quota) | ✅ | `6aed506` |
| PII-filter в structlog | ✅ | vault 2026-05-08-1433 |
| PydanticAI baseline | ✅ | vault 2026-05-08-1510 |
| K4 MVP scaffold (LiteLLM gateway / 3-tier RAG cache / BGE-M3 / LangMem / PydanticAI / StreamingLLM / 2 Streamlit / 58 tests) | ✅ | `8c43219` (часть) + `2c38a57` (wiring) |
| testkit/ skeleton (recorder/replay/route_runner/fixtures/pytest-plugin) | 🟡 | partial |
| LangFuse cost-tracking dashboard v0 | ⏳ | pending |
| AI hotfix: register extended providers / semantic_cache fix / agent_memory ensure_indexes / параметризация MCP tools input_schema | ⏳ | E.2 vault 2026-05-08-1911 |
| `[wave:s1/policy-observability]` OTel span attributes | ⏳ | V17 NEW |
| `[wave:s1/ai-lazy-import]` стандарт `_ensure_<lib>()` | ⏳ | V17 NEW |

#### К5 Frontend+Ext+Mig
| Wave | Status | Ref |
|---|---|---|
| Plugin marketplace dashboard (часть) | ✅ | `2198eaa` (frontend pages auto-discovery) |
| Streamlit pages 00/10/20/30/40/50/60 | 🟡 | continued from Wave 10 |

### Sprint 2 — ASGI middleware + Repository + Auth + Hot Reload + Audit + Schema Import

#### К1 Security
| Wave | Status |
|---|---|
| Idempotency middleware wire-up POST/PATCH (RedisNxBackend SET NX EX + _LazyRedisProxy DI + 9 unit + 3 integration tests) | ✅ `b5527ec` (2026-05-12) |
| AuthBackend ABC + JWT (joserfc) + API-key + mTLS (51/69 → 69/69) | 🟡 in-progress: shim ready, cutover отдельной Wave |
| Webhook standardwebhooks 4 inline callsites consolidation | ⏳ |
| Per-plugin rate-limit | ⏳ |
| F2.1 `core/auth/protocols.py` AuthBackend Protocol | ✅ (vault 2026-05-08-1911 в working tree) |
| signatures.py extend (`WebhookSignatureConfig`, `compose_signature`) | ✅ (vault 2026-05-08-1911 working tree) |
| F2.3 JWTBackend через joserfc + RS256/HS256/ES256 + JWKS-кэш + Redis blacklist | 🟡 shim `[wave:s2/k1-w1-joserfc]` `af0c4f5` (2026-05-13): jwt_backend_joserfc.py (373 LOC) + 14 unit-тестов под `feature_flag.auth_joserfc` default-OFF; cutover после staging-smoke |
| Python-2 except hotfix repo-wide (20 callsites/15 файлов) | ✅ `[wave:s2/k10-w2-py2-syntax]` `461a6ce` (2026-05-13) |
| Multi-agent kickoff backbone — 10-team ownership + 22 feature-flags + 3 blocker tracker | ✅ `[wave:s2/k10-backbone]` `371eace` + `[wave:s2/k10-features-extend]` `07512b4` (2026-05-13) |

#### К2 Resilience+Perf
| Wave | Status |
|---|---|
| Wave F AsyncRepository[T] + advanced-alchemy + Oracle dialect test | ⏳ |
| alembic-postgresql-enum >=1.4.0 (safe ENUM migration) | ⏳ |
| OTel asyncpg auto-instrumentation + tenacity unification (3 callsites) | ✅ `[wave:s2/k3-w1-otel-tenacity]` `42ed620` (2026-05-13) under `feature_flag.otel_asyncpg` |
| TaskWatchdog deadline-эскалация + AIWorkspaceCleaner TTL (4+5 unit-тестов) | ✅ `[wave:s2/k3-w2-watchdog-deadline]` `d9beed9` + fix `5549127` (2026-05-13) under 2 feature flags |
| perf-gate Makefile + CI workflow + baseline.json skeleton (3 endpoints) | ✅ `[wave:s2/k3-w4-perf-gate-ci]` `26aa05a` (2026-05-13) — warn-only до S3 |
| ConnectionPoolHealthMonitor scaffold (idle ping + reuse-on-demand) | ✅ `[wave:s2/k8-w5-pool-health]` `2aa4544` (2026-05-13) under `feature_flag.pool_health_monitor` |
| testkit/pytest_plugin.py entry-point (закрывает блокер make test) | ✅ `[wave:s2/k10-w1-testkit]` `8af96c1` (2026-05-13) |

#### К3 DSL+Workflow
| Wave | Status |
|---|---|
| `routes/<name>/route.toml + *.dsl.yaml` + RouteLoader full-cycle | 🟡 2 reference routes готовы `[wave:s2/k5-w5-routes-v11-refs]` `dc33a03` (2026-05-13) — RouteLoader full-cycle отдельно |
| `[wave:s2/hot-reload-dsl]` watchfiles graceful drain < 3 сек | ⏳ V17 NEW |
| `[wave:s2/schema-import-codegen]` zeep + openapi-python-client | ⏳ V17 NEW |
| `[wave:s2/multi-tenant-route-overrides]` per-tenant timeout/retry/quota | ⏳ V17 NEW |
| ResponseValidatorProcessor + `.get_setting()` builder | 🟡 |
| Universal Recorder testkit | ⏳ |
| ProcessorRegistry @processor + JSON-Schema export (ADR-0058, 17 unit-тестов) | ✅ `[wave:s2/k5-w3-processor-registry]` `f2f5b14` (2026-05-13) |
| FileWatcherSource через watchfiles.awatch (4 unit-тестов) | ✅ `[wave:s2/k7-w4-file-watcher]` `dacd89c` (2026-05-13) under `feature_flag.eventbus_file_watcher` |

#### К4 AI+RAG
| Wave | Status |
|---|---|
| Token-based + recursive chunking RAG (advanced-alchemy в RAG-collections) | ✅ vault 2026-05-08-1911 E.4 |
| AsyncAPI 3 export для FastStream-источников | 🟡 stub-only |
| RAG citations | ⏳ E.5 |
| LangFuse 3.x parallel shim (callback_v3 240 LOC + 4 unit-тестов) | ✅ `[wave:s2/k6-w1-langfuse-v3]` `ca5429d` (2026-05-13) under `feature_flag.langfuse_v3` |

#### К5 Frontend+Ext+Mig
| Wave | Status |
|---|---|
| Plugin codegen `make new-plugin NAME=x` | ⏳ |
| `[wave:s2/audit-trail-dsl]` ClickHouse `audit_events` + Streamlit `35_Audit_Log.py` | ⏳ V17 NEW |
| Example route `routes/order_processing/route.toml` | ✅ vault 2026-05-08-1911 E.8 |

#### Sprint 2 Summary (2026-05-13 multi-agent kickoff)
14 wave-коммитов, 46 unit-тестов green, 22 feature-flag default-OFF.
Memory: [[feedback_s2_multi_agent_kickoff]].
Отложено в Sprint 3 (см. ниже): SBOM/cosign supply-chain, OWASP ZAP gate, WAF Phase-2 38 callsites, TaskIQ removal, Workflow legacy purge.

### Sprint 3 — Plugin runtime + 3-tier auto-reg + Sinks + Protocols + Notifications + Schema Registry UI

**ЗАКРЫТ 2026-05-14**: 25/25 wave-задач выполнены, 5 команд V18 (К1-К5), 41 wave-коммит в master,
45 feature-flag default-OFF, ~310 unit-тестов green. Подробная матрица — §4 Sprint 3 ниже.

#### К1 Security (5 waves)
| Wave | Status | Ref |
|---|---|---|
| Vault secret rotation hook (без рестарта) | ✅ | `003d33c` `[wave:s3/k1-w1-vault-rotation]` |
| OTel baggage propagation (route_name/tenant_id/business_op/correlation_id) | ✅ | `1df3b26` `[wave:s3/k1-w2-tracing-baggage]` |
| Supply-chain CI gate scaffold (cyclonedx SBOM + pip-audit + cosign) | ✅ | `c8c8a5a` `[wave:s3/k1-w3-supply-chain-ci]` |
| Plugin manifest semver-check final | ✅ | `a3df2a6` `[wave:s3/k1-w5-plugin-semver]` |

#### К2 Resilience+Perf (4 waves)
| Wave | Status | Ref |
|---|---|---|
| PerHostMeter early-signal (request_count, p50/p95) | ✅ | `1e11122` `[wave:s3/k2-w1-per-host-metering]` |
| ConnectionReuseManager (idle ping + auto-recycle) | ✅ | `e12b41e` `[wave:s3/k2-w2-connection-reuse]` |
| AsyncBulkhead + HighWatermark/LowWatermark alerts | ✅ | `a241c85` `[wave:s3/k2-w3-bulkhead-alerts]` |
| K8sHPAMetricsExporter (auto-scaler уровень 3) | ✅ | `182a538` `[wave:s3/k2-w4-k8s-hpa-exporter]` |

#### К3 DSL+Workflow (8 waves)
| Wave | Status | Ref |
|---|---|---|
| Apprise notification DSL (.notify_apprise / .notify_multi) | ✅ | `d404ee2` `[wave:s3/k3-w1-notification-dsl]` |
| NATS JetStream DSL (.from_nats_js / .to_nats_js) | ✅ | `7711a4a` `[wave:s3/k3-w2-nats-jetstream]` |
| FTP/SFTP DSL (aioftp + asyncssh + .from_ftp/.ftp_upload/.sftp_get/.sftp_put) | ✅ | `83ae219` `[wave:s3/k3-w3-ftp-sftp-dsl]` |
| Workflow gateways (.gateway_xor/.gateway_and/.gateway_or → Temporal branching) | ✅ | `7a7b170` `[wave:s3/k3-w4-workflow-gateways]` |
| Builder source-сахар (.from_kafka/.from_rabbit/.from_mqtt/...) | ✅ | `0299e2b` `[wave:s3/k3-w5-builder-source-sugar]` |
| EmailIMAPSource + .from_imap() через aioimaplib | ✅ | `3c01362` `[wave:s3/k3-w5-email-imap-source]` |
| GraphQLSubscriptionSource (@strawberry.subscription via WebSocket) | ✅ | `a3854dd` `[wave:s3/k3-w5-graphql-subscription]` |
| service.toml loader + ServiceDSLRegistry | ✅ | `5ed7c20` `[wave:s3/k3-w5-yaml-service-toml]` |

#### К4 AI+RAG (5 waves)
| Wave | Status | Ref |
|---|---|---|
| LangMem 3-tier memory (episodic/semantic/procedural) | ✅ | `d7bfe42` `[wave:s3/k4-w1-langmem-baseline]` |
| SearXNG provider (free self-hosted meta-search, PLAN #5) | ✅ | `3bb83f0` `[wave:s3/k4-w4-searxng-provider]` |
| MCP tools input_schema resolver (Pydantic reflection) | ✅ | `495e818` `[wave:s3/k4-w2-mcp-input-schema]` |
| LangfusePromptStorage (prompt-registry migration) | ✅ | `886e346` `[wave:s3/k4-w3-prompt-registry-langfuse]` |
| MultimodalRAG scaffold (text/image/audio embeddings) | ✅ | `7253103` `[wave:s3/k4-w4-multimodal-rag]` |

#### К5 Frontend+Ext+Mig (4 waves)
| Wave | Status | Ref |
|---|---|---|
| Schema Registry UI (Streamlit 40_Schema_Registry.py, 6-tab) | ✅ | `52fb231` `[wave:s3/k5-w1-schema-registry-ui]` |
| Action Bus UI (Streamlit 50_Action_Bus.py) | ✅ | `75376ee` `[wave:s3/k5-w2-action-bus-ui]` |
| Plugin Marketplace UI (Streamlit 60_Plugin_Marketplace.py) | ✅ | `18fada6` `[wave:s3/k5-w3-plugin-marketplace]` |
| Admin REST endpoints для Action-Bus + Plugin-Marketplace | ✅ | `4f39641` `[wave:s3/k5-w4-admin-marketplace-endpoints]` |

### Sprint 4 — Workflow DSL ⭐ КЛЮЧЕВОЙ + BPMN + YAML round-trip — ✅ **ЗАКРЫТ 2026-05-14**

| Wave | Status | Ref |
|---|---|---|
| К3 Workflow Spec Pydantic + WorkflowBuilder + SagaBuilder | ✅ | `4ab3e98`, `b5d8ba2`, `c19a85c` (Sprint 4 Wave A pre-pull) |
| К3 Compiler emitter + step_compilers + activity_bridge + registry (59 tests) | ✅ | `2e4d135` |
| К3 LiteTemporalBackend + smoke tests (7 cases) | ✅ | `bdd6505` |
| К3 Saga 2 production examples (orders + payments) | ✅ | Phase 1 Explore confirmed (orders_saga.py + payments_saga.py + tests) |
| К3 Workflow legacy purge (4 файла + 19 импортёров) | ✅ | де-факто purged до Sprint 4 (см. Phase 1 Explore) |
| К3 BPMN-import (stdlib `xml.etree` offline-friendly) → WorkflowDeclaration → Temporal compiler | ✅ | `eb935d1` `[wave:s4/k3-bpmn-import]` |
| К3 YAML round-trip `to_yaml()` / `from_yaml()` / `diff()` + semver `version` | ✅ | `1fb3ffb` (Wave A merged via race с параллельной сессией) |
| К4 LLM-activity для Temporal (`@activity.defn` + cost + retry + Heartbeat + structured output) | ✅ | `43084b1` `[wave:s4/k4-llm-activity-temporal]` |
| К4 LangGraph checkpoints в Postgres | ⏳ | → Sprint 5 (escalated) |
| К4 StreamingLLMProcessor (token-level → SSE/WS) | ✅ | Phase 1 Explore confirmed (`dsl/engine/processors/streaming_llm.py` готов) |
| К4 Workflow-replay UI Streamlit | ✅ | `30ddd06` `[wave:s4/k5-workflow-replay-ui]` |
| К1 Capability-проверка для Temporal activities + Vault rotation | ✅ | `3974537` `[wave:s4/k1-activity-capability-gate]` |
| К2 Auto-scaling 3 уровня (LocalProcessScaler + BulkheadScaler + K8sHpaExporter facade) | ✅ | `b38a422` `[wave:s4/k2-auto-scaling-final]` |
| К2 ConnectionReuseManager + ClickHouse pool + Graylog pool | ⏳ | → Sprint 5 (escalated — connection-pools финал) |
| Wave G — координация hotfix (spec.version восстановление + ruff cleanup) | ✅ | `ad3b5aa` `[wave:s4/g-hotfix]` |

### Sprint 5–9

Все ⏳ кроме K4 MVP scaffold (✅ Sprint 5 предварительно: `8c43219` + `2c38a57`). Подробно — §4 Sprint 5–9.

---

## 2.7. Shared-файлы и протокол координации

### Shared-файлы (требуют координатора)

| Файл | Owner координатора | Протокол модификации |
|---|---|---|
| `pyproject.toml` | Backbone-координатор (К1) | Каждая команда добавляет deps в собственный extra; конфликты разрешаются через мердж + `uv sync` |
| `src/backend/main.py` | Координатор + К3 | Только additive: новый router include / middleware register |
| `src/backend/plugins/composition/lifecycle.py` | К1 (security-startup); К4 (ai_2026); К3 (workflow) | Каждая команда имеет именованный `register_<feature>()` + `start_<feature>()/stop_<feature>()` блок |
| `src/backend/entrypoints/api/v1/routers.py` | К3 | Только additive: `include_router(<router>)` |
| `src/backend/core/config/__init__.py` | Backbone (К1+К2) | Composition root через `BaseSettings` mixin |
| `src/backend/core/svcs_registry.py` / `providers_registry.py` | К1+К2 | Lazy registration через `app_state_singleton(factory=)` |
| `Makefile`, `Makefile.{dev,test,docs,security,codegen,deploy}` | Каждая команда владеет своим `Makefile.<dom>`; общий `Makefile` — координатор | Composite-цели только в корневом `Makefile` |
| `.github/workflows/ci.yml` | Координатор | Add stage через PR с явным review |
| `CLAUDE.md`, `PLAN.md`, `ARCHITECTURE.md` | Координатор | Изменения только batched |

### Pre-flight protocol

Перед commit любая команда обязана:

```bash
git diff --cached --stat | grep -E "(pyproject|main\.py|lifecycle\.py|routers\.py|providers_registry\.py)"
```

Если есть совпадение — использовать `Agent isolation: worktree` или согласовать через координатора. Любая модификация shared-файла → отдельный wave-tag `[wave:shared/<task>]`.

### Worktree mandatory zones

| Зона | Причина |
|---|---|
| К1 × К2 | Resilience взаимодействует с capability-gate (decorators обращаются к `ResilienceCoordinator`) |
| К3 × К4 | DSL processors импортируют `services/ai/` для LLM/StreamingLLM/RAG-шагов |
| К5 миграция | Перемещение CRUD из `services/core/` в `extensions/core_entities/` касается импортёров через весь codebase |

### Auto-staging pre-commit hook (унаследовано)

При работе на shared FS:
- использовать узкоточечный `git add <файл>` (никогда `git add -A` / `.`);
- проверять `git diff --cached --stat` ДО `git commit`;
- идеально — `Agent isolation: worktree` для конкурентных Wave;
- не ожидать атомарных коммитов: pre-commit hooks могут добавить untracked файлы parallel-команд автоматически.

---

## 3. Hotfix-неделя (week 0, 5 дней) — со статусами

### Day 1 — B.0 codeclone setup ✅

```bash
uv tool install "codeclone[mcp]"           # ✅ 2026-05-06
codeclone-mcp --transport stdio
make review-clones-baseline                # docs/clone-baseline-pre-hotfix.json
```

`Makefile` targets: `review-clones`, `review-clones-baseline`, `review-clones-diff`. Перед merge крупных рефакторов обязательно `make review-clones`; similarity ≥0.85 без обоснования = block.

### Day 1-2 — Удалить пустые placeholder-каталоги (10 шт.) 🟡

`entrypoints/{legacy,web3,enterprise,iot}/`, `schemas/{auto,custom}/`, `infrastructure/datalake/`, `dsl/{importers,eip}/`. Все только с `__init__.py` или `.gitkeep`.

> **V17**: `tools/schema_importer/` НЕ удалять — воссоздать как `[wave:s2/schema-import-codegen]` (К3).

Owner: К1 (entrypoints/, schemas/, infrastructure/datalake/) + К3 (dsl/).

### Day 1-2 — Frontend leftover 🟡

`src/backend/static/` (css, dashboard, images, index.html, js) → `git mv → src/frontend/static/`. Обновить FastAPI пути. Часть выполнена в `923859d`. Owner: К5.

### Day 2-3 — Дедупликация (4 группы)

| # | Группа | Status | Ref |
|---|---|---|---|
| 1 | Antivirus → `infrastructure/antivirus/{backends/, factory.py, hash_cache.py, service.py}` | ✅ | `eaf0420` (К1) |
| 2 | Codecs/Converters → `dsl/codec/{base64.py, json.py, format_converters.py}` + `dsl/transforms/dataframes.py` | ✅ | `7ce1421`, `8c81fba` (К3) |
| 3 | Tools split: `tools/dsl_cli/` → `dsl/cli/`; `tools/schema_importer/` → recreate в Sprint 2 | ✅ part 1 | `9d03f0a`, `39e7c4f` (К3) |
| 4 | api_management → `core/auth/api_key_backend.py` + `core/tenancy/quotas.py` + `entrypoints/middlewares/versioning.py` | ✅ | `6cf53a7` (К1) |

### Day 2-3 — Утилиты merge ✅

| Текущее | Целевое | Ref |
|---|---|---|
| `core/async_utils.py` | `core/utils/async_utils.py` | ✅ `41c2b92` |
| `utilities/web.py` | `core/net/http_utils.py` | ✅ |
| `utilities/async_helpers.py` | `core/utils/async_helpers.py` | ✅ |
| `utilities/admin_panel/` | `services/admin/` (временно; Sprint 7 → `extensions/core_entities/admin/`) | 🟡 partial |

Owner: К2.

### Day 3-4 — Performance P0 hotfix

| # | Действие | Effort | Impact | Status | Ref |
|---|---|---|---|---|---|
| 1 | ClickHouse pool: connection pooling в `ClickHouseClient` | 4h | -50..100ms latency, +80% RPS | ✅ К2 | `945758f`, `83d0014` |
| 2 | Graylog persistent connection: structlog handler + persistent socket / UDP batch | 5h | -2..5ms per log | ✅ К2 | `40e933a`, `34b4b8a` |
| 3 | orjson hotpath sweep: `resilience/components/{mongo_chain, mq_chain}`, `storage/sqlite_doc_store`, `ClickHouseClient` | 3h | -5..10ms на batch | ✅ К2 | `d503a98`, `a10b7ae` |
| 4 | Redis cluster + pipelining: `redis.asyncio.cluster.RedisCluster` + batch ops | 4h | +30..50% throughput | ⏳ К2 | pending |

### Day 4-5 — Custom code → стандартные библиотеки

| # | Custom | Library | Status | Owner | Ref |
|---|---|---|---|---|---|
| 1 | Idempotency-Key middleware | `snok/asgi-idempotency-header` | ✅ | К1 | `efb92f1` |
| 2 | `services/decorators/limiting.py` | `fastapi-easylimiter` через ASGI middleware | ✅ | К1 | `bd2c49f`, `7951eaa` |
| 3 | Custom correlation-id | `asgi-correlation-id` | ✅ | К1 | `efb92f1` |
| 4 | `infrastructure/repositories/base.py` | `advanced-alchemy>=1.0.0` | ✅ | К2 | vault 2026-05-08-1911 |
| 5 | Custom `RetryPolicy`/`RetryBudget` (3 места) | `tenacity 9.0+` | 🟡 | К2 | partial; Step 3.3 deferred |
| 6 | TaskIQ removal | — (delete) | ⛔ | К2 | escalated to Sprint 5 `[wave:s5/async-queue-migrate]` |
| 7 | Custom HMAC webhook (98 LOC + 4 inline callsites) | `standardwebhooks 1.0.1` | ⏳ | К1 | escalated to Sprint 2 |
| 8 | ASGI `request_log` body capture | opt-in flag + `body_capture_max_bytes`/`skip_paths` | ⏳ | К1 | pending |

**#6 deferred reason** (V16.1): TaskIQ имеет 13 production use-sites — это реализация публичной фичи `InvocationMode.ASYNC_QUEUE`, не unused dep. Миграция требует ADR.

**#7 deferred reason** (V16.1 + V18): Variant A full spec (breaking) — стандартный wire-format `webhook-id`/`webhook-timestamp`/`webhook-signature: v1,<base64>`; 60-дневный sync-window через feature-flag `WEBHOOK_LEGACY_FORMAT_V1`.

### Day 5 — Feature Flags активация (V17 NEW)

```bash
uv add "openfeature-sdk>=0.9.0"
# core/feature_flags/__init__.py — InMemoryProvider
# APP_PROFILE=dev_light использует MemoryProvider
# Smoke test: feature_flag("dsl.hot_reload") → True/False
```

Status: ⏳ pending. Owner: К1.

### Day 5 — Smoke CI stage (V17 NEW)

```yaml
# .github/workflows/ci.yml — добавить stage:
smoke:
  needs: [build]
  steps:
    - name: Start app
      run: APP_PROFILE=dev_light uv run python -m src.backend.main &
    - name: Health check
      run: |
        sleep 5
        curl -f http://localhost:8000/health/live
        curl -f http://localhost:8501
```

Status: ⏳ pending. Owner: К2.

### Day 5 — Workflow legacy mark for removal ✅

Помечены DEPRECATED V16 (Owner: К3, ref: `764ec37`, `96d3370`):
- ❌ `infrastructure/workflow/{state, state_store, event_store, state_projector}.py` — Temporal native заменяет (purge → Sprint 4, Step 2.2 deferred).
- ✅ `infrastructure/workflow/{temporal_backend, pg_runner_backend}.py` — keep.
- ⚠️ `infrastructure/workflow/{runner, executor, factory, builder}.py` — refactor/migrate в `dsl/workflow/`.

### DoD hotfix-недели

10 пустых каталогов удалены (🟡); 4 группы дублей объединены (✅); frontend-leftover перенесён (🟡); 8 custom-code заменено (5/8 ✅, 3/8 ⏳); 4 P0 performance hotfixes (3/4 ✅); codeclone установлен (✅); `make review-clones-diff` показывает уменьшение дублей (✅); OpenFeature InMemoryProvider активен (⏳); Smoke CI зелёный (⏳); `make test` зелёный; `make routes` = 119.

**V18 параллельная декомпозиция Sprint 0**: 16 unit'ов в isolated worktrees через background-агентов (PR-per-unit). Координатор отслеживает merge-конфликты в `pyproject.toml` и `src/backend/main.py` (только #2 `static` + #12 `middlewares` + #14 `taskiq` + #15 `standardwebhooks` модифицируют общие файлы — низкий риск).

---

## 4. Sprint-расписание (5 команд × 9 спринтов = 11–12 недель)

### Sprint 1 — Resilience + Plugin Contract + Стандарты кода V17 (2 нед)

| Команда | Задачи |
|---|---|
| **К1 Security** | ✅ Capability `fs.create_new` + `code.execute` [`8114b14`]; ✅ VaultSecretsBackend hvac KV v2 [`0671af8`]; ✅ HttpxClient mTLS [`e017e51`]; ✅ register_waf_policy + DI factory [`96b9eda`]; ✅ BaseExternalAPIClient feature-flag миграция [`8c43219`]; ✅ register_ai_safety + lifespan [`6aed506`]; ✅ E2B sandbox [`600247c`]; ✅ ADR-0050 + Makefile ci/pr [`e59c71a`]; 🟡 Phase-2 `WAF_OUTBOUND_VIA_FACADE=True` (allowlist 38 callsites pending К2-К5 ack). |
| **К2 Resilience+Perf** | ✅ canonical CB/Retry/RateLimiter в `core/resilience/` [`672b40f`]; ✅ pyrate_compat + BoundedInMemoryBucket [`e07000b`]; ✅ TaskRegistry + Watchdog + tests [`1e3d107`, `2a6a048`, `9b8440c`]; 🟡 Single Entry callsite миграция (Step 3.3 Phase 2 — 12 callsites через aliases, KNOWN_ISSUES.md); ⛔ Workflow legacy purge — deferred to Sprint 4 (KNOWN_ISSUES.md Step 2.2); ⏳ OTel auto-instrumentation расширение (asyncpg частично); ⏳ aiocache evaluation; ⏳ `[wave:s1/cache-decorator-api]` `aiocache[redis]>=1.0.0a0` + `core/decorators/cache.py` (`@cached(ttl, key, backend)` / `@invalidate(key_pattern)` / `@multi_cached`); ⏳ `[wave:s1/resilience-decorator-api]` `core/resilience/decorators.py` (`@policy(cb, rl, retry, cache)`) поверх ResilienceCoordinator; ⏳ `[wave:s1/asyncio-taskgroup]` migration во всех DSL-процессорах; ⏳ `[wave:s1/result-monad]` `result>=0.17.0` + `ResultUnwrapProcessor`. |
| **К3 DSL+Workflow** | ⏳ builder.py split на 6 модулей в `dsl/builders/{control_flow, camel_eip, ai_rpa, integration, converters, base}/` (план: `~/.claude/plans/replicated-seeking-panda.md`); ⏳ Formal Plugin Processor API (`@processor` + ProcessorRegistry в `dsl/registry/`); ⏳ JSON-Schema export через интроспекцию registries; ⏳ Schema-registry RAM (`services/schema_registry/`) + REST `/api/v1/admin/schemas`; ⏳ `.crud_*` builder (5 шт., alias к entity_*); ⏳ `.call_function('module:fn')` builder + capability check + whitelist enforcement; ⏳ `[wave:s1/eventbus-facade]` `core/messaging/eventbus.py` + DSL `.to_eventbus(topic)` / `.from_eventbus(pattern)`; ⏳ `[wave:s1/unified-convert]` `.convert(target_type: Type)` (V17 NEW); ✅ MQTT sink + EmailSource + plugin marketplace + frontend pages auto-discovery [`2198eaa`, `bf5b9fe`]. |
| **К4 AI+RAG** | ✅ AIWorkspaceManager + AIFsFacade [`6aed506`]; ✅ PII-filter в structlog (vault 2026-05-08-1433); ✅ PydanticAI baseline (vault 2026-05-08-1510); 🟡 testkit/ skeleton — частично; ⏳ LangFuse cost-tracking dashboard v0; ⏳ AI hotfix (register extended providers / semantic_cache fix / agent_memory ensure_indexes / параметризация MCP tools input_schema, E.2 vault 2026-05-08-1911); ⏳ `[wave:s1/policy-observability]` OTel span attributes для `@policy/@cached` функций → Streamlit Resilience Dashboard; ⏳ `[wave:s1/ai-lazy-import]` стандарт `_ensure_<lib>()`; тест dev_light < 5 сек. |
| **К5 Frontend+Ext+Mig** | ⏳ Pages 00/10/20/30/40/50/60 финализация; ⏳ AI/RAG страницы 20/30/40/50/74/75 — координация с К4. |

**DoD Sprint 1**: Single Entry для CB/RL/Retry — реализован, старые удалены (🟡 в процессе через aliases); Capability-gate runtime отбрасывает несанкционированные обращения (✅); PII не утекает в логи (✅); ProcessorRegistry открыт для плагинов (⏳); AI workspace isolation работает (✅); Workflow legacy purged (⛔ → Sprint 4); testkit publishes editable из monorepo (🟡); `@policy` decorator работает (⏳); `@cached` decorator работает (⏳); EventBus facade с тремя backends (⏳); `.convert(TargetType)` единый (⏳); test dev_light < 5 сек (✅); coverage ≥ 20% (⏳); `make review-clones-diff` -8 крупных дублей (🟡).

---

### Sprint 2 — ASGI middleware + AsyncRepository + Auth + Routes V11.1a + Hot Reload + Audit + Schema Import (2 нед)

| Команда | Задачи |
|---|---|
| **К1 Security** | ⏳ Wave E pure ASGI middleware (idempotency wire-up Redis NX TTL 2min + smoke-test двойной POST); ⏳ AuthBackend ABC + JWT (joserfc RS256/HS256/ES256 + JWKS-кэш TTL=300s + Redis blacklist) + API-key + mTLS + 51/69 → 69/69 endpoints; ✅ F2.1 `core/auth/protocols.py` AuthBackend Protocol (vault 2026-05-08-1911 working tree); ✅ signatures.py extend `WebhookSignatureConfig`/`compose_signature`/`verify_compose_signature` (vault 2026-05-08-1911 working tree); ⏳ webhook standardwebhooks 4 inline callsites consolidation; ⏳ Per-plugin rate-limit (V16.1 P1 move from S5: `RateLimiter.apply(scope=plugin)` поверх per-tenant); ⛔ убрать `from jose import jwt` в `auth_selector.py:73,188` (python-jose НЕ в pyproject.toml — prod падает на ImportError при Bearer-токене). |
| **К2 Resilience+Perf** | ⏳ Wave F AsyncRepository[T] + advanced-alchemy глубинная (Oracle dialect тест обязателен в DoD) + DI lazy + bulk + observability hooks; ⏳ alembic-postgresql-enum >=1.4.0 (safe ENUM migration); ⏳ Step 3.3 единая Wave `[wave:s1/single-entry-migration]` (12 callsites + удаление shim'ов после слияния параллельных working tree). |
| **К3 DSL+Workflow** | ⏳ `routes/<name>/route.toml + *.dsl.yaml` + RouteLoader full-cycle + ScheduleSource (`from_schedule(cron)`); ⏳ `[wave:s2/hot-reload-dsl]` watchfiles graceful drain reload < 3 сек без SIGTERM (HOT_RELOAD feature-flag); ⏳ `[wave:s2/schema-import-codegen]` `tools/schema_importer/` recreate (zeep + openapi-python-client; `make import-wsdl URL=... NAME=...` → `extensions/<name>/features/<service>/client.py`; `make import-openapi URL=... NAME=...`) (V17 NEW); ⏳ `[wave:s2/multi-tenant-route-overrides]` `route.toml::tenant_overrides.<tenant_id>` (V17 NEW); 🟡 ResponseValidatorProcessor (`.validate_response(schema, on_error="dlq"\|"fail"\|"warn")`); 🟡 `.get_setting("path.to.value")` builder + capability `settings.read.<scope>`; ⏳ 3-tier auto-registration part 1 (REST autoloop + `tools/codegen/codegen_proto.py` для gRPC); ⏳ Universal Recorder testkit (HAR cassettes). |
| **К4 AI+RAG** | ✅ Token-based + recursive chunking RAG (vault 2026-05-08-1911 E.4); ⏳ Citations в RAG output (E.5); 🟡 AsyncAPI 3 export для FastStream-источников (E.6 stub-only). |
| **К5 Frontend+Ext+Mig** | ⏳ Plugin codegen `tools/codegen/codegen_plugin.py` (`make new-plugin NAME=x`); ⏳ `[wave:s2/audit-trail-dsl]` `.audit_log(action, entity, entity_id, actor, metadata)` DSL-шаг + ClickHouse `audit_events(action, entity, entity_id, actor_id, tenant_id, timestamp, metadata_json)` + Streamlit `35_Audit_Log.py` (V17 NEW; ISO 27001 / PCI DSS); ✅ example route `routes/order_processing/route.toml` с `requires_plugins` (vault 2026-05-08-1911 E.8). |

**DoD Sprint 2**: idempotency для всех POST/PATCH; rate-limit через ASGI; AuthBackend (3 backend) защищает все 69/69 endpoints; AsyncRepository[T] + bulk + Oracle dialect test зелёный; route.toml hot-reload < 3 сек; `make new-plugin` за 60 сек; `make import-wsdl` за 60 сек генерирует клиент; `.audit_log()` пишет в ClickHouse; coverage ≥ 25%.

---

### Sprint 3 — Plugin runtime + 3-tier auto-reg + Sinks + Protocols + Notifications + Schema Registry UI (2 нед)

| Команда | Задачи |
|---|---|
| **К1 Security** | ⏳ Plugin manifest semver-check финал; ⏳ Centralized Vault Secret-broker rotation без рестарта; ⏳ Tracing baggage propagation (route_name/tenant_id/business_op/correlation_id обязательны); ⏳ supply-chain CI gate alpha (cyclonedx SBOM + pip-audit warn-only + cosign sign keys). |
| **К2 Resilience+Perf** | ⏳ Per-host outbound metering (early signal); ⏳ ConnectionReuseManager (idle ping + reuse-on-demand) скелет. |
| **К3 DSL+Workflow** | ⏳ **3-tier auto-reg full**: GraphQL Strawberry runtime auto-schema + WS/SSE/Webhook/Express унификация через ActionDispatcher + Pydantic→protobuf nullable mapping ADR; ⏳ `[wave:s3/strawberry-auto]` migration на встроенный `strawberry.auto` (Strawberry ≥0.262); −70 LOC; ⏳ **Wave 3 Sinks 8+**: HTTP / gRPC / SOAP / MQ (Kafka/Rabbit/Redis-Streams/NATS) / WS / Webhook / File / Email + 5 DSL-процессоров sink_publish + SinkRegistry; ⏳ `[wave:s3/ftp-sftp-dsl]` `aioftp>=0.26.0` + `asyncssh>=2.19.0` + DSL `.from_ftp/.ftp_upload/.sftp_get/.sftp_put` (V17 NEW); ⏳ `[wave:s3/nats-jetstream-builder]` JetStream streams + durable consumers + DSL `.from_nats_js/.to_nats_js` (V17 NEW); ⏳ `[wave:s3/graphql-subscription-source]` `@strawberry.subscription` WebSocket + DSL `.from_graphql_subscription` (V17 NEW); ⏳ NATS+MQTT bidirectional (`nats-py` + `gmqtt`/`aiomqtt`) — pub+sub tests; ⏳ Builder source-сахар (`.from_cdc/.from_kafka/.from_rabbit/.from_mqtt/.from_redis_streams/.from_filewatcher/.from_webhook/.from_schedule/.from_imap`); ⏳ EmailTriggerProcessor + `.from_imap(folder, subject_filter, from_filter)` (IMAP IDLE через `aioimaplib`); ⏳ YAML `service.toml` loader + `service_dsl_registry`; ⏳ `[wave:s3/workflow-gateways]` DSL `.gateway_xor` (exclusive) / `.gateway_and` (parallel + join wait-all) / `.gateway_or` (inclusive + join wait-active); компиляция в Temporal branching (V17 NEW). |
| **К4 AI+RAG** | ⏳ LangMem baseline (long-term memory; episodic/semantic/procedural; Postgres + Qdrant); ⏳ Migration custom prompt-registry → langfuse storage backend; ⏳ MCP tools параметризация input_schema. |
| **К5 Frontend+Ext+Mig** | 🟡 Plugin marketplace dashboard Streamlit (часть в `2198eaa`); ✅ Plugin-local Streamlit pages auto-discovery (symlink factory в `loader_v11.py` post-load) [`2198eaa`]; ⏳ Action-bus Streamlit; ⏳ `[wave:s3/notification-dsl]` `apprise>=1.9.0` + DSL `.notify(channel, title, body, template)` / `.notify_multi(channels, title, body)` + CB→notify (V17 NEW); ⏳ `[wave:s3/schema-registry-ui]` Streamlit `40_Schema_Registry.py` (OpenAPI / WSDL/XSD / Protobuf / AsyncAPI / GraphQL SDL; Download / Diff / Validate) (V17 NEW). |

**DoD Sprint 3**: один пилотный action отвечает идентично через REST/gRPC/GraphQL/SOAP/MCP + 8 Sinks работают; FTP/SFTP DSL-шаги с тестами; NATS JetStream pub/sub; gateway_xor/and/or компилируются в Temporal; YAML service.toml hot-reload; SBOM в каждом релизе; plugin marketplace; plugin-local pages автоматически появляются; `.notify()` шлёт в Telegram/Slack; Schema Registry UI; coverage ≥ 35%.

---

### Sprint 4 — Workflow DSL обёртка над Temporal ⭐ КЛЮЧЕВОЙ + BPMN + YAML round-trip — ✅ **ЗАКРЫТ 2026-05-14**

| Команда | Задачи |
|---|---|
| **К1 Security** | ✅ Capability-проверка для activities (`@capability_guarded_activity` + `CapabilityContext` + audit на grant/deny + feature-flag `activity_capability_gate_enabled`) [`3974537`]; ✅ Vault rotation для long-running workflows (`LongRunningSecretRotator` с time-based cache + heartbeat sync/async + `asyncio.Lock`) [`3974537`]. |
| **К2 Resilience+Perf** | ✅ **Auto-scaling 3 уровня**: `core/scaling/auto_scaler.py` фасад + `local_process_scaler.py` (Granian SIGUSR1/SIGUSR2 + psutil) + `bulkhead_scaler.py` (adaptive HW/LW + _resize semaphore) + K8sHpaExporter integration; lifecycle start/stop через `asyncio.Task` + stop_event (V15 R-V15-11 leak prevention) [`b38a422`]; ⏳ TaskRegistry финал → Sprint 5; ⏳ Watchdog для long-running tasks → Sprint 5; ⏳ ConnectionReuseManager (idle ping + reuse-on-demand финал) → Sprint 5; ⏳ ClickHouse pool финал → Sprint 5; ⏳ Graylog persistent TCP/HTTPS pool + circuit breaker → Sprint 5. |
| **К3 DSL+Workflow** | ✅ К3-D Шаг 0 hotfix Python-2 except [`ea14cf2`]; ✅ К3-D Шаг 1 compiler tests (59 cases) [`2e4d135`]; ✅ К3-D Шаг 2 LiteTemporalBackend smoke (7 cases) [`bdd6505`]; ✅ К3-D Шаг 3 saga 2 production examples (`orders_saga`, `payments_saga`) + smoke compile (Phase 1 Explore confirmed); ✅ К3-D Шаги 4-6 (compiler finalize + legacy purge); ✅ **Workflow legacy purge** — де-факто purged (legacy state*.py файлы отсутствуют в `infrastructure/workflow/`); ✅ **Workflow DSL финал**: `WorkflowDeclaration` Pydantic + YAML loader + Python `WorkflowBuilder.activity().saga().wait_for_signal().sleep().sensor()`; ✅ **Compiler `WorkflowDeclaration → Temporal @workflow.defn`** через `activity_bridge.py` + `step_compilers`; ✅ `ActivityDeclaration.required_capabilities` для V15 R-V15-1 (capability-gate в Temporal compiler) [`3974537`]; ✅ DSL `.saga().forward(action, compensate=).step().step()` + YAML `saga: { steps, compensations }` (orders_saga); ✅ `[wave:s4/k3-bpmn-import]` stdlib `xml.etree` offline-friendly путь (вместо SpiffWorkflow extra) + `BpmnImportError`/`BpmnImportDisabledError` + `manage.py workflow import --format {bpmn,yaml} --file <path>` + `docs/bpmn/credit_scoring_sample.bpmn` + XOR/AND/OR gateways маппинг [`eb935d1`]; ✅ `[wave:s4/k3-workflow-yaml-roundtrip]` `WorkflowBuilder.to_yaml()` + `WorkflowDeclaration.from_yaml()` + `diff()` + `WorkflowDiff` + semver `version: "1.0"` + feature-flag `workflow_yaml_round_trip` [`1fb3ffb` — merged via race с параллельной сессией]; ⏳ Invoker `ASYNC_QUEUE` mode → Temporal-activity adapter → Sprint 5 `[wave:s5/async-queue-migrate]`; ⏳ Builder `.invoke_workflow(name, input, mode)` → Sprint 5; ⏳ Reply-channels полный → Sprint 5. |
| **К4 AI+RAG** | ✅ LLM-activity для Temporal (`@activity.defn(name="ai.llm.call")` обёртка для `LiteLLMGateway.acompletion` + cost tracking через `acost_estimate` + retry-policy + Heartbeat callback sync/async + structured output JSON parse + `register_llm_activity()` под feature-flag `ai_workflow_activity_enabled`) [`43084b1`]; ⏳ Saga для multi-step LLM (compensate) → Sprint 5; ⏳ LangGraph checkpoints в Postgres → Sprint 5; ⏳ AI Workflow примеры (RAG-augmented saga + multi-agent supervisor + Code-Interpreter loop) → Sprint 5; ✅ Workflow-replay UI Streamlit (`17_Workflow_Replay.py` drill-down + event-фильтры + waterfall) [`30ddd06`]; ✅ **StreamingLLMProcessor** (Phase 1 Explore confirmed: `dsl/engine/processors/streaming_llm.py` + `streaming_llm_publishers.py` — TokenStreamLLMProcessor MVP). |
| **К5 Frontend+Ext+Mig** | ✅ Workflow-replay UI компоненты (`pages/17_Workflow_Replay.py` + `APIClient.list_workflows`/`get_workflow_events` уже из IL-WF1.5 admin_workflows endpoints) [`30ddd06`]. |

**DoD Sprint 4 ✅ (2026-05-14)**: `workflow.yaml` (Python builder) → компилируется → Temporal-workflow выполняется через `LiteTemporalBackend` (dev_light) + реальный Temporal cluster (staging — готов через temporalio 1.27); LLM-activity работает с retry/cost/Heartbeat/structured output; YAML↔Python round-trip без потери данных (9 unit-тестов); `.bpmn` → Temporal workflow работает на примере credit_scoring (8 unit-тестов); XOR/AND/OR gateways импортируются корректно; StreamingLLM в `dsl/engine/processors/streaming_llm.py`; Workflow legacy purged; 55 новых unit-тестов в Sprint 4; coverage ≥ 50% по Sprint 4 модулям; ruff All checks passed; vault summary в `vault/session-2026-05-14-1430-sprint4-summary.md`.

---

### Sprint 5 — R2 Universal Building Blocks + AI Stack 2026 + Async Queue + Doc Generation + Web Search + Dry-run (2 нед)

| Команда | Задачи |
|---|---|
| **К1 Security** | ⏳ DLQ-replay endpoint security (rbac); ⏳ Inbox dedup audit (PII-mask). |
| **К2 Resilience+Perf** | ⏳ Tenacity unification финал; ⏳ Per-tenant rate-limit namespace; ⏳ Bulkhead defaults в ResilienceSettings; ⏳ 5 alerts-конфигов (CB/degradation/RL/queue/error-budget) + 2 новых fallback-chains (graylog_chain + genai_chain); ⏳ Outbox pattern (`core/messaging/outbox.py` + `infrastructure/messaging/outbox_dispatcher.py`); ⏳ **DLQ unified для HTTP/SOAP/gRPC/Webhook**: расширить outbox-pattern на все transport-types; DLQ-table в Postgres + replay API; DSL `.dlq(target, max_attempts=N)`; Streamlit DLQ-replay UI; ⏳ Inbox dedup fail-closed (`seen_or_mark()` при Redis-error → raise `InboxUnavailable`); ⛔ → ✅ `[wave:s5/async-queue-migrate]` ADR (Temporal-activity adapter рекомендован) + миграция `Invoker.ASYNC_QUEUE` + удаление `taskiq`/`taskiq-redis` deps + R-V15-7 compliance. |
| **К3 DSL+Workflow** | ⏳ Orchestration scaffold integration с builder (Sensor/Backfill/DryRun/HumanApproval → Temporal-activities); ⏳ R2.1 CDC enrichment + builder `.from_cdc(table, mode)`; ⏳ **CDC PostgreSQL logical replication**: `psycopg3 + pgoutput` decoder (или `wal2json`); publication + replication-slot в startup; ack-cursor через `WatermarkStore`; tests с PG INSERT/UPDATE/DELETE; ⏳ R2.2 `notify_cascade` policy formalization; ⏳ 4 Blueprint'а R2 dual-mode (api_normalize_persist_webhook, cdc_enrich_publish, ai_pipeline, saga_with_compensation); ⏳ Новые процессоры: `LdapQuery`, `WebDav`, `IcsCalendar`, `WebhookSignature`, `HtmlTemplate`, `PdfTemplate`, `JsonPath`, `Jq`, `RegexExtractor`, `UnitConversion`, `Geo`, `RateConvert`, `ZipArchive`; ⏳ `.db_call_procedure()` сахар; ⏳ `.policy.*` chainable финал; ⏳ `[wave:s5/dsl-web-search]` `tavily-python>=0.5.0` + `perplexityai>=1.0.0` + DSL `.web_search(engine, query, max_results=10)` / `.web_search_rpa(engine, query)` (V17 NEW); ⏳ `[wave:s5/doc-generation-dsl]` `docxtpl>=0.18.0` + `xlsxwriter>=3.2.0` + DSL `.render_docx/.render_xlsx/.render_to_s3` (V17 NEW); ⏳ `[wave:s5/dsl-dryrun]` `manage.py workflow dryrun <name> --input ... [--record\|--replay]` + JSON-отчёт (V17 NEW); ⏳ `[wave:s5/workflow-step-log]` `StepAuditMiddleware` → ClickHouse `workflow_step_log(workflow_id, step_id, step_name, correlation_id, tenant_id, duration_ms, status, input/output_schema_hash)` + OTel custom span attributes (V17 NEW). |
| **К4 AI+RAG** | ✅ K4 MVP scaffold (LiteLLM gateway / 3-tier RAG cache / BGE-M3 / LangMem / PydanticAI / StreamingLLM / 2 Streamlit / 58 тестов) [`8c43219` + `2c38a57`]; ⏳ MCP via FastMCP (auto-export Tier 1+2 actions + DSL-routes `expose_mcp = true` + LangFuse prompts → `@mcp.prompt`); ⏳ LiteLLM gateway финал; ⏳ RLM-toolkit MemGPT-style hierarchical memory; ⏳ 3-уровневый RAG cache (L1 exact / L2 semantic / L3 retrieval) + invalidation Redis pub/sub; ⏳ BGE-M3 + bge-reranker-v2.5 как параллельный EmbeddingProvider; ⏳ Multimodal RAG (docling + PaddleOCR/EasyOCR); ⏳ 7 Streamlit RAG страниц (Inspector/Trace/ClusterMap/EvalDashboard/CacheDashboard/Playground/IngestWizard); ⏳ `[wave:s5/dsl-rag-memory-steps]` `.rag_query/.rag_upsert/.rag_delete/.memory_write/.memory_read` + `mem0ai>=0.1.0` (V17 NEW); ⏳ `[wave:s5/pii-dsl-step]` `.mask_pii(fields, level)` / `.unmask_pii(fields, vault_key)` (V17 NEW). |
| **К5 Frontend+Ext+Mig** | ⏳ `[wave:s5/workflow-logs-ui]` Streamlit `50_Workflow_Logs.py` (фильтр workflow/tenant/date/status; waterfall-диаграмма тайминга; drill-down) (V17 NEW). |

**DoD Sprint 5**: tenacity единственный retry-engine; Outbox at-least-once; 4 Blueprint'а с тестами; FastMCP экспортирует tools; LiteLLM gateway; 3-уровневый RAG cache hit-rate ≥30%; Streamlit RAG визуализирует retrieval traces; TaskIQ удалён; DLQ replay UI работает; `.web_search()` через Tavily и Perplexity; `.render_docx()` создаёт Word по шаблону; dry-run mode для всех workflow; workflow step log в ClickHouse; RAG DSL-шаги с тестами; PII masking работает; coverage ≥ 60%.

---

### Sprint 6 — Performance + Chaos + Coverage + Security + OLE/COM + Observability (2 нед) — ✅ **ЗАКРЫТ 92.9% 2026-05-14** (24 wave-commits)

| Команда | Задачи |
|---|---|
| **К1 Security** | ✅ SAML adapter + AD integration test [`1565d338`, `8ca67968`]; ⏳ Per-host outbound metering (финал) → S7; ✅ supply-chain полный CI gate (SBOM + pip-audit error + cosign sign + bandit TLS) [`1df39670`]; ✅ OWASP API Top 10 audit + ZAP gate в CI [`5e79e334`]; ✅ Custom-code-audit (vulture --min-confidence 80 + manual review) [`5e79e334`]; ✅ codeclone CI gate переключить на `--fail-on-new-clones` [`5e79e334`]. |
| **К2 Resilience+Perf** | ✅ k6+locust perf-suite + CI perf-gate (p95<200ms / RPS>1000) [`51f2f847`]; ✅ Granian/uvloop tuning + DB pool min/max + msgspec hotpath sweep [`ef5334f3`, `08da1f13`]; ✅ structlog batching wrapper (50-event batch / 100ms timeout) → -1..3ms per log [`40a66577`]; ✅ Health-checks include processor-specific states (Kafka schema-registry up, Temporal server up, Vault sealed) [`83d933a4`]; ✅ Backpressure model для streaming consumers [`fd6f078d`]; ✅ `[wave:s6/msgspec-hotpath]` benchmark [`3743c574`]; ✅ `[wave:s6/granian-rsgi-adr]` ADR-0059 [`ef5334f3`]; ✅ `[wave:s6/api-fuzz-ci]` schemathesis [`db04d827`]; ✅ `[wave:s6/ci-service-doc-gate]` check_service_docs.py [`a0a87641`]. |
| **К3 DSL+Workflow** | ✅ e2e «один action × 6 протоколов» (REST/gRPC/GraphQL/SOAP/MCP/MQTT) [`b40e8331`]; ✅ Coverage gate ≥70% [`53c5ab57`]; ✅ Banking-процессоры unit-тесты (12 шт.) [`097a335a`]; ✅ DSL Linter CLI + LSP plugin-aware [`0c9a0742`]; ⏳ `[wave:s6/com-windows-sidecar]` Windows-specific → перенесён в S8 (вместе с RPA-волной). |
| **К4 AI+RAG** | ✅ Inspect AI eval framework (nightly regression) [`9ee277c0`]; ✅ DSPy для critical eval pipelines [`51752fa1`]; ✅ AI cost dashboard финал [`4a1f77f1`]. |
| **К5 Frontend+Ext+Mig** | ✅ Chaos-tests 33 шт. (testcontainers[toxiproxy], 11 chains × 3 сценария) [`e7b00bf8`]; ✅ OutboxBackend Protocol+Fake stub [`36ca6757`]; ⏳ DLQ-replay UI Streamlit → S8 (Outbox stub готов); ⏳ Resilience Dashboard Streamlit → S8; ⏳ Worker pool monitor + Connection pool monitor → S8; ⏳ 5 Grafana dashboards → S8; ✅ Layer-violations facade [`6b818829`]. |

**DoD Sprint 6 (13/14 = 92.9%)** ✅ (2026-05-14): ✅ p95<200ms / RPS>1000 baseline; ✅ 33 chaos-теста зелёные (warn-only CI); ✅ coverage ≥70% blocking; ✅ SAML+AD логин; ✅ SBOM в каждом релизе; ✅ OWASP ZAP gate (warn-only); ✅ codeclone gate `--fail-on-new-clones`; ⏳ COM-sidecar (Windows) → S8; ✅ CI docs-gate; ✅ schemathesis в CI (warn-only); ✅ msgspec hotpath benchmark; ✅ banking-processors tests + DSL Linter+LSP; ✅ layer-violations.

**24 wave-commits Sprint 6** (vault/session-2026-05-14-2025-sprint6-summary.md). Backbone: `2de9d733`. HEAD: `4f6e9dab`.

---

### Sprint 7 — Migration core → extensions/ + Blue/Green + Multi-agent + Feature Flags + Admin + Live UI (2 нед) — ✅ **100% ЗАКРЫТ 2026-05-15** (18 wave-commits)

| Команда | Задачи |
|---|---|
| **К1 Security** | ✅ Per-tenant billing/quotas [`4f6e9dab`]; ✅ supply-chain финал (multi-artifact cosign) [`fbf17665`]; ⏳ OpenFeature → Flagsmith → S8 (стэк готов в T5). |
| **К2 Resilience+Perf** | ✅ Blue/green compose + deploy/rollback runbook + ADR-0060 (от T5 + S7-K2); ✅ httpx unify (`httpx + httpx-retries + hishel`) [`036f59cc`]; ✅ 7 Grafana dashboards финал + 3 SLO-burn alerts [`4183c211`]. |
| **К3 DSL+Workflow** | ✅ Migrate `dsl/macros.py`/`dsl/blueprints.py` → `dsl/blueprints/` package [`12c2f25f`]; ✅ Workflow versioning (WorkflowVersionRegistry + Temporal patched API) [`116f40ec`]; ✅ plugin-hotswap (T5 `6e306d1f` + AUDIT-2 в `core/plugin_runtime/hot_swap.py` 279 LOC). |
| **К4 AI+RAG** | ✅ Multi-agent coordination (LangGraph supervisor) [`7ab41984`]; ✅ Voice (Whisper STT + Coqui TTS) [`17e97c58`]; ✅ Image generation через LiteLLM [`55c82d2f`]. |
| **К5 Frontend+Ext+Mig** | ✅ Migration credit_pipeline (T3 SKB-Техно) [`fdc80779`]; ✅ Migration core_entities (T1 [`6b027e3b`] + T2 [`9648772b`]); ✅ sqladmin + 3 Streamlit pages (T4) [`2ecaa919`]; ✅ DLQ Replay UI [`d0e5a371`]; ✅ Resilience Dashboard [`33aeb752`]; ✅ Pool Monitor [`67420ee2`]; ✅ `70_Tenants.py`/`71_Capabilities.py`/`30_Files_S3.py` [`e7051065`]; ⏳ `@st.fragment` live refactor → S8. |

**DoD Sprint 7 (14/14 = 100% запланированных)** ✅ (2026-05-15 finale): все wave из PLAN.md §6 §7 закрыты. Остаток — только `@st.fragment` live updates refactor (стилистическое улучшение, не блокер) и 5 quotas-тестов fix (техдолг → Sprint 8A K1 W0). 5 BLOCKER'ов из Sprint 5 carryover мигрированы в Sprint 8A.

**Sprint 7 wave-commits (18)**: T1 `6b027e3b`, T2 `9648772b`, T3 `fdc80779`, T4 `2ecaa919`, T5 `6e306d1f`; + Round 1: K1 per-tenant-billing `4f6e9dab`, K4 multi-agent `7ab41984`; + Round 2: K5 DLQ Replay `d0e5a371`, Resilience Dashboard `33aeb752`, Pool Monitor `67420ee2`, K4 Voice STT/TTS `17e97c58`, Image Generation `55c82d2f`, K1 supply-chain-finale `fbf17665`; + Finale: K3 blueprints migrate `12c2f25f`, K3 workflow versioning `116f40ec`, K5 3 streamlit pages `e7051065`, K2 httpx unify `036f59cc`, K2 7 Grafana + SLO `4183c211`. Сводки: `vault/session-2026-05-15-1030-s7-closure-round2-summary.md`.

---

### Sprint 8 — Migration finish + RPA stage 1 + HTTP/3 + Cleanup + Rule Engine (2 нед)

| Команда | Задачи |
|---|---|
| **К1 Security** | ⏳ Pre-receive hook на git-server для docstring; ⏳ Multi-version Sphinx + ReadTheDocs/GitLab Pages publish (security-runbooks). |
| **К2 Resilience+Perf** | ⏳ mypy ≤ 50 (R3 цель); ⏳ deptry/vulture clean + heavy deps в `[project.optional-dependencies]` (ai/rag/rpa/analytics/tracing); ⏳ Layer violations 6 baseline → 0 (фасад `services/dsl_portal/` для frontend→DSL); ⏳ DI container migration evaluation: prototype `core/di/providers.py` (625 LOC) на `dependency-injector.DeclarativeContainer` в ветке `prototype/di-container`; benchmark + test coverage diff; ADR-решение в Sprint 9. |
| **К3 DSL+Workflow** | ⏳ Миграция legacy DSL routes Python → YAML; ⏳ HTTP/3 + WebTransport opt-in через aioquic; ⏳ **RPA Universal stage 1**: `patchright>=1.0.0` (вместо playwright/selenium; anti-detection); `PlaywrightBrowserPool` (worker-pool N контекстов); DSL-шаги BrowserLaunch / Navigate / Click / Fill / Extract / WaitFor / Screenshot / Pdf; OCR через PaddleOCR/EasyOCR; integration tests с tracing-on-failure; ⏳ `[wave:s8/rpa-windows-desktop]` `pywinauto>=0.6.8` для Windows desktop UI automation (Win32/UIA backend); DSL `.desktop_rpa(app, action, params)` → Windows sidecar (V17 NEW); ⏳ `[wave:s8/rule-engine-dsl]` `.evaluate_rules(ruleset, input)` DSL-шаг + YAML-правила (`condition: "score < 500 OR debt_ratio > 0.7" → action: decline`) + `simpleeval` evaluator + хранение ruleset в БД + reload через feature flag (V17 NEW). |
| **К4 AI+RAG** | ⏳ Sophisticated prompt-injection guardrails (Lakera/Rebuff classifiers); ⏳ AI model registry (MLflow / Hugging Face Hub adapter); ⏳ Batch inference (vLLM / TGI client); ⏳ Code-Interpreter (e2b.dev / pyodide-wasm sandboxing); ⏳ `[wave:s8/llm-structured-dsl]` `.llm_structured(model, output_schema, prompt, retry=3)` DSL-шаг + `instructor>=1.7.0` retry-loop до валидного Pydantic объекта (V17 NEW). |
| **К5 Frontend+Ext+Mig** | ⏳ Миграция остальных 4 клиентов кредитного конвейера (DaData/БКИ/СМЭВ/ЦБ/1С) в feature-folders; ⏳ Streamlit Wiki расширение (Whoosh + live DSL examples + Diátaxis + Vale prose linter + ru-language proofreader). |

**DoD Sprint 8**: 5 клиентов конвейера через extensions; mypy ≤ 50; deptry/vulture green; HTTP/3 opt-in работает; AI model registry; Inspect AI nightly regression suite зелёный; patchright DSL с тестами; `.evaluate_rules()` работает на примере credit_scoring ruleset; `.llm_structured()` возвращает типизированный объект; Wiki с Whoosh.

---

### Sprint 9 — Финал + DSL Dry-run finalization + Documentation + Pre-prod Gate (1 неделя)

| Команда | Задачи |
|---|---|
| **К1 Security** | ⏳ Disaster recovery runbook + backup verification; ⏳ Feature flags (OpenFeature) внешний provider финал (Flagsmith); ⏳ Free-threading PEP 703 benchmark; ⏳ **Pre-production gate checklist** (V17 NEW): `make pre-prod-check` → 20 критериев (coverage ≥70%, chaos green, mypy ≤50, no layer violations, SBOM актуален, ZAP gate, всё на Temporal, все endpoints авторизованы, docstring gate, codeclone clean). |
| **К2 Resilience+Perf** | ⏳ Snapshot/restore profiles (БД/cache в SQLite) для dev_light. |
| **К3 DSL+Workflow** | ⏳ Tutorials ≥9 по Diátaxis (getting-started, build-first-action, build-rest-connector, build-grpc-service, write-dsl-route, plugin-development, RAG-setup, RPA-script, multi-tenant-setup); ⏳ ≥10 runbooks (deploy/rollback/scale-out/incident/db-migration/cache-flush/audit-export/key-rotation/plugin-install/cdc-restart); ⏳ `[wave:s9/dsl-visual-editor-final]` DSL Visual Editor — drag-drop + YAML/BPMN export + undo/redo + step palette с описаниями capability (V17 NEW); ⏳ Legacy workflow Python → YAML миграция финал. |
| **К4 AI+RAG** | ⏳ mem0/Zep persistent personalisation (opt-in для credit_pipeline); ⏳ Streamlit `60_AI_Agent_Monitor.py` (multi-agent trace viewer, OTel GenAI semantics). |
| **К5 Frontend+Ext+Mig** | ⏳ DSL Visual Editor расширение (drag-drop) на стороне Streamlit. |

**DoD Sprint 9**: `make pre-prod-check` зелёный по всем 20 критериям; ≥9 tutorials; ≥10 runbooks; Visual Editor экспортирует BPMN; система готова к production.

**Итого**: 9 спринтов × 1-2 недели = **11–12 недель** при 5 командах. Эффективная экономия ~25-30% от V15 4-командного варианта (14-15 нед) за счёт явной изоляции зон.

---

## 5. Финальная архитектура (V17, после Sprint 9)

```text
gd_integration_tools/
├── PLAN.md, CLAUDE.md, ARCHITECTURE.md, README.md
├── pyproject.toml             # packages = ["src/backend", "src/frontend/streamlit_app", "testkit"]
├── Makefile + Makefile.{dev,test,docs,security,codegen,deploy}
├── manage.py                  # единый CLI (Typer)
├── docker-compose.{yml,prod.yml,blue.yml,green.yml,windows-worker.yml}
├── .pre-commit-config.yaml + .mcp.json
├── .github/workflows/         # ci, docs-required, perf, chaos, security, api-fuzz, docs-gate
│
├── src/backend/               # ЯДРО (domain-agnostic)
│   ├── core/{config,di,exceptions,tenancy,enums,state,
│   │        interfaces/<11 доменов>,
│   │        plugin_runtime,workflow,actions,auth,ai,
│   │        net,messaging,scaling,resilience,
│   │        security/capabilities,orchestration,utils,
│   │        decorators/,feature_flags/}/   # NEW V17
│   ├── infrastructure/{antivirus,audit,cache,search,storage,secrets,
│   │                  messaging,logging,workflow,execution,
│   │                  scheduler,sources,sinks,repositories,
│   │                  observability,resilience,clients,
│   │                  notifications,policy,application,
│   │                  eventbus/}/          # NEW V17
│   ├── services/{core,ai,integrations,ops,execution,
│   │            plugins,schema_registry,notebooks}/
│   ├── dsl/{route,workflow,service,builders,codec,transforms,
│   │       contracts,engine/processors,blueprints,
│   │       adapters,helpers,versioning,integration_gateway,
│   │       orchestration,cli}/
│   ├── entrypoints/{api,grpc,soap,graphql,websocket,sse,
│   │               webhook,mqtt,cdc,filewatcher,scheduler,
│   │               email,stream,express,mcp,middlewares}/
│   ├── schemas/
│   └── main.py
│
├── src/frontend/              # ФРОНТ
│   └── streamlit_app/{app.py,api_client.py,pages/,components/,static/}
│   # Pages V17: 30_Files_S3.py, 35_Audit_Log.py, 40_Schema_Registry.py,
│   # 50_Workflow_Logs.py, 60_AI_Agent_Monitor.py,
│   # 70_Tenants.py, 71_Capabilities.py, 80_Admin_Models.py
│
├── extensions/                # БИЗНЕС-ПЛАГИНЫ (V15.1 hybrid layout)
│   ├── core_entities/         # users/orders/orderkinds/files
│   ├── credit_pipeline/       # СКБ-Техно/DaData/БКИ/СМЭВ/ЦБ/1С
│   └── example_plugin/
│
├── routes/<name>/{route.toml, *.dsl.yaml}      # DSL-routes (V11.1a)
├── testkit/                   # gd-integration-tools-testkit sub-package
├── tools/{checks,codegen,imports,migrations,dsl,build,templates,
│         schema_importer/}/   # RESTORED V17
├── docs/{source,tutorials,runbooks,reference,adr,
│        alerts,grafana,clone-baseline.json,clone-reports/}
├── tests/{unit,integration,e2e,perf,chaos}/
├── config_profiles/{base,dev,dev_light,staging,prod}.yml
├── windows_worker/            # NEW V17 — COM/Desktop RPA sidecar
│   ├── Dockerfile.windowsservercore
│   ├── main.py
│   └── handlers/{com_handler.py, desktop_rpa_handler.py}
└── .claude/                   # служебная память Claude
```

---

## 6. pyproject.toml — полный список зависимостей V17

```toml
[project.dependencies]
# === Ядро (уже есть или добавить) ===
"openfeature-sdk>=0.9.0",       # Feature flags (Sprint 0 Day 5)
"aiocache[redis]>=1.0.0a0",     # Cache decorators (Sprint 1)
"result>=0.17.0",               # Railway-oriented programming (Sprint 1)

[project.optional-dependencies]
notification = ["apprise>=1.9.0"]
workflow-bpmn = ["SpiffWorkflow>=3.0.0"]
sources-ftp = ["aioftp>=0.26.0", "asyncssh>=2.19.0"]
com-windows = ["pywin32>=308", "comtypes>=1.4.9"]            # Windows-only
rpa-windows = ["pywinauto>=0.6.8"]                            # Windows-only
admin = ["sqladmin>=0.20.1"]
doc-generation = ["docxtpl>=0.18.0", "xlsxwriter>=3.2.0"]
web-search = ["tavily-python>=0.5.0", "perplexityai>=1.0.0"]
schema-import = ["openapi-python-client>=0.24.0"]             # zeep уже в deps
alembic-extras = ["alembic-postgresql-enum>=1.4.0"]
analytics = ["dask[distributed]>=2025.0.0"]                   # перенести из core

# === ai-2026 (дополнить существующие) ===
# + "instructor>=1.7.0",  + "mem0ai>=0.1.0"
```

---

## 7. Финальный DoD V18

### Протоколы и интеграции
- ✅ REST / SOAP / gRPC / GraphQL / FTP/SFTP / Email / CDC / Watchdog — DSL-шаги с тестами.
- ✅ OLE/COM Windows sidecar + `.call_com()` DSL.
- ✅ Web-поиск DSL: Tavily / Perplexity / RPA fallback.
- ✅ WSDL/OpenAPI → codegen клиента за 60 сек.
- ✅ EventBus facade (Kafka/RabbitMQ/NATS JetStream) единый API.

### DSL обогащение
- ✅ `.convert(target_type)` единый унифицированный шаг.
- ✅ `.gateway_xor / .gateway_and / .gateway_or` — три типа ветвления.
- ✅ `.notify(channel, title, body)` — multi-channel notifications.
- ✅ `.audit_log(action, entity, ...)` — DSL audit trail.
- ✅ `.mask_pii / .unmask_pii` — PII защита.
- ✅ `.rag_query / .rag_upsert / .rag_delete / .memory_write / .memory_read`.
- ✅ `.render_docx / .render_xlsx` — генерация Word/Excel.
- ✅ `.web_search(engine, query)` — унифицированный поиск.
- ✅ `.evaluate_rules(ruleset, input)` — rule engine.
- ✅ `.llm_structured(model, schema, prompt)` — типизированный LLM.
- ✅ `.crud_*`, `.invoke_workflow`, `.call_function`, `.get_setting`, `.validate_response`, `.db_call_procedure`, `.policy.*` builder.
- ✅ Per-service timeouts + per-service pool config + retry-policy.
- ✅ Single Entry V15.1: один CB / RL / Retry / Bulkhead / Cache.
- ✅ `manage.py workflow dryrun` — dry-run mode.
- ✅ `manage.py workflow import --format bpmn` — BPMN import.
- ✅ YAML↔Python round-trip с diff() и версионированием.
- ✅ Hot Reload DSL без рестарта < 3 сек.
- ✅ Plugin hot-swap без рестарта.

### Workflow
- ✅ Workflow DSL обёртка над Temporal (activity/saga/signal/sleep/sensor декларативно).
- ✅ XOR/AND/OR gateways в DSL и BPMN.
- ✅ HITL (wait_for_signal), saga, sleep, sensor, continue_as_new.
- ✅ Workflow step log в ClickHouse + Streamlit waterfall.
- ✅ Legacy workflow мигрированы.
- ✅ Один action × 6+ протоколов (REST/gRPC/GraphQL/SOAP/MCP/MQTT/WS/SSE).

### AI
- ✅ AI в workflow (LLM-activity + saga + LangGraph checkpoints + multi-agent + code-interpreter).
- ✅ AI Safety: AI создаёт только новые файлы в `${AI_WORKSPACE}/<tenant>/<session>/`.
- ✅ MCP через FastMCP (auto-export Tier 1+2 actions).
- ✅ LangMem + RLM-toolkit + 3-уровневый RAG cache + 7 Streamlit RAG страниц.
- ✅ AI стек: PydanticAI, Instructor, LiteLLM, DSPy, mem0/Zep, multimodal RAG, voice, image, batch inference.
- ✅ AI ops: cost dashboard + Inspect AI nightly + model registry + GenAI OTel semantics.
- ✅ LangChain/LangGraph через lazy import (`_ensure_<lib>()`).
- ✅ PII маркировка + AI-агенты видят только маскированные данные.
- ✅ AI-агенты не получают доступ к файлам ядра (WAF-policy).
- ✅ Guardrails (Lakera/Rebuff) для prompt injection.

### Производительность и устойчивость
- ✅ 12 Sinks + 13 новых процессоров + 30/30 EIP.
- ✅ Auto-scaling 3 уровня + leak prevention (TaskRegistry + Watchdog + pool monitoring).
- ✅ 12 fallback chains + chaos-tests 33 шт. + 5 alerts.
- ✅ p95 < 200ms / RPS > 1000 + perf-gate в CI.
- ✅ Tenacity unification + whenever migration.
- ✅ ClickHouse pool + Graylog persistent TCP/HTTPS pool.
- ✅ ConnectionReuseManager (idle ping + reuse-on-demand).
- ✅ `asyncio.TaskGroup` вместо `asyncio.gather` во всех DSL-процессорах.
- ✅ `msgspec.Struct` в hot-path (benchmark до/после).
- ✅ Granian ASGI + uvloop ADR и benchmark.
- ✅ Pool connections везде: DB / Redis / ClickHouse / Graylog.
- ✅ Dask в `analytics` optional extra.

### Резилиентность и наблюдаемость
- ✅ `@policy(cb, rl, retry, cache)` декоратор на бизнес-функциях.
- ✅ `@cached(ttl, key, backend)` декоратор с invalidation.
- ✅ Decorated functions подсвечиваются в Resilience Dashboard.
- ✅ OTel custom span attributes для policy-decorated функций.
- ✅ Result[T, E] монада для бизнес-ошибок.

### Безопасность
- ✅ Auth полный: JWT+APIkey+mTLS+SAML+AD.
- ✅ Supply-chain: SBOM + pip-audit + cosign + OWASP ZAP gate + bandit TLS.
- ✅ WAF strict: все `:external` через WAF; `make check-waf-coverage` зелёный.
- ✅ V1-V24 уязвимости закрыты (включая FTP TLS hotfix).
- ✅ codeclone gate `--fail-on-new-clones` зелёный.
- ✅ AI safety: workspace dirs TTL, audit-event, size quota.

### Feature Flags
- ✅ OpenFeature InMemoryProvider — Sprint 0 Day 5.
- ✅ OpenFeature внешний provider (Flagsmith) — Sprint 7.
- ✅ `HOT_RELOAD`, `WEBHOOK_LEGACY_FORMAT_V1`, `CORE_ENTITIES_LEGACY_MODE`, `NEW_RESILIENCE_V2`, `WAF_OUTBOUND_VIA_FACADE` — все через OpenFeature.

### CI/CD
- ✅ Smoke CI stage (health check в CI).
- ✅ Coverage ramp-up: Sprint 1≥20%, S2≥25%, S3≥35%, S4≥50%, S5≥60%, S6≥70%.
- ✅ CI docs-gate: новый сервис без docstring → CI fail.
- ✅ schemathesis API fuzzing в CI.
- ✅ AsyncAPI diff = 0 gate.
- ✅ `make pre-prod-check` → 20 критериев.

### Архитектура и качество
- ✅ Frontend split: `src/frontend/streamlit_app/`.
- ✅ tools/ split на 6 подкаталогов; Makefile split на includes; manage.py — single CLI.
- ✅ mypy ≤ 50, coverage ≥70%, layer violations = 0.
- ✅ Миграция 4 CRUD из ядра в `extensions/core_entities/`.
- ✅ Миграция кредитного конвейера в `extensions/credit_pipeline/` (5 клиентов в feature-folders).
- ✅ V15.1 hybrid layout: shared + features per plugin.
- ✅ Multi-tenant route overrides.
- ✅ Oracle через advanced-alchemy (dialect тест).
- ✅ alembic-postgresql-enum для safe ENUM migration.
- ✅ Rule engine DSL (YAML-правила).
- ✅ Windows worker сидекар (COM + Desktop RPA).
- ✅ Admin UI: sqladmin (DevOps) + Streamlit (операторы).
- ✅ Каждый эндпоинт в своей директории (feature-slice).
- ✅ Кодогенерация: `make new-plugin / make new-feature / make import-wsdl / make import-openapi`.

### Документация
- ✅ Sphinx auto-gen API reference; multi-version + ReadTheDocs/GitLab Pages.
- ✅ Pre-push docstring gate + GitHub Action `docs-required.yml` + GitLab CI mirror.
- ✅ AsyncAPI 3 export; Diátaxis структура; Vale prose linter + ru-language proofreader.
- ✅ ≥9 tutorials + ≥10 runbooks.
- ✅ Wiki в Streamlit + Whoosh full-text + live DSL examples.
- ✅ OLE/COM documentation: отдельный раздел про Windows sidecar деплой.

### Фронтенд
- ✅ 8 Streamlit страниц V17: S3 Files / Audit Log / Schema Registry / Workflow Logs / AI Agent Monitor / Tenants / Capabilities / Admin.
- ✅ `@st.fragment(run_every=2)` для live-секций.
- ✅ DSL Visual Editor: drag-drop + YAML/BPMN export + undo/redo.

---

## 8. Открытые ADR-вопросы

- **ADR R1.1** — точный синтаксис capability в `plugin.toml` (массив `["host", "*.glob"]` vs flat-keys).
- **ADR R1.5** — формат SLO-конфига (sloth YAML vs `route.toml::slo`).
- **ADR R1.7** — Single Entry policy наименование (resilience.yaml vs route.toml::policy vs plugin.toml::policy).
- ✅ **ADR R1.6** — закрыт: hybrid layout (shared/ + features/) для extensions/.
- **ADR R1.8** (V17 NEW) — EventBus backend выбор для production: NATS JetStream (простота, < 100K msg/s) vs Kafka (> 500K msg/s, log retention) vs RabbitMQ (сложная маршрутизация, AMQP).
- **ADR R1.9** (V17 NEW) — Granian ASGI vs Uvicorn: benchmark результат → решение о merge в production Dockerfile.
- **ADR R1.10** (V17 NEW) — DI container: `core/di/providers.py` 625 LOC remain vs migrate to `dependency-injector.DeclarativeContainer`.

---

## 9. Команды финальной проверки

```bash
uv run pytest tests/ -v --cov=src --cov-report=term-missing  # ≥70%
python tools/checks/check_layers.py            # 0
python tools/checks/check_docstrings.py        # 0
python tools/checks/check_service_docs.py      # 0  (V17 NEW)
uv run mypy src/ --strict                      # ≤ 50
uv run vulture src/ --min-confidence 80        # 0
uv run deptry src/                             # 0
make review-clones-diff                        # 0 новых дублей
APP_PROFILE=dev_light uv run python -m src.backend.main &
sleep 5 && curl -f :8000/health/live && curl -f :8501  # 200, 200
python tools/dsl/dsl_coverage.py               # 100%
make chaos                                     # 33/33
k6 run tests/perf/k6_script.js                # p95 < 200ms, RPS > 1000
make check-waf-coverage                        # 0
make custom-code-audit                         # ≤5 необоснованных
schemathesis run http://localhost:8000/openapi.json --checks all  # 0 critical (V17 NEW)
asyncapi-diff ...                              # 0 breaking (V17 NEW)
make pre-prod-check                            # 20/20 (V17 NEW)
make new-plugin NAME=demo
make import-wsdl URL=http://example.com/service?wsdl NAME=example_service
curl :8000/api/v1/demo                         # 200 (от плагина)
manage.py workflow dryrun credit_scoring --input tests/fixtures/credit_input.json
manage.py workflow import --format bpmn --file docs/bpmn/credit_process.bpmn --name credit_process
```

---

## 10. Sources (web research 2026)

- PydanticAI / vs LangGraph 2026 / LangWatch frameworks 2026
- FastMCP / FastStream NATS+MQTT5+Redis / NATS Python / JetStream
- aioquic HTTP/3+QUIC+WebTransport
- BAAI/bge-m3 / BentoML embeddings 2026
- snok/asgi-idempotency-header / fastapi-easylimiter
- DBOS vs Temporal 2026 / Hatchet
- advanced-alchemy 1.0 (Oracle, bulk upsert, UUID7)
- Tacnode: Enterprise Integration Patterns 2026
- Modal Labs: Error Handling and Resilience
- Building Resilient Python with Tenacity / Signal Handling in Python
- codeclone (clone detection MCP)
- SpiffWorkflow BPMN 2.0 gateways (XOR/AND/OR) — spiffworkflow.readthedocs.io
- apprise>=1.9.0 (100+ notification channels) — github.com/caronc/apprise
- aioftp + asyncssh — github.com/aio-libs
- msgspec (10x faster than Pydantic) — jcristharif.com/msgspec/benchmarks
- NATS JetStream 2025 benchmarks
- Granian ASGI vs Uvicorn benchmarks — github.com/emmett-framework/granian
- aiocache decorators (redis cache, stampede protection) — aiocache.aio-libs.org
- pybreaker / circuitbreaker (per-function CB)
- pywin32 / comtypes (OLE/COM Windows) — pythonhosted.org/comtypes
- docxtpl (Word template + Jinja2)
- tavily-python + perplexityai SDK
- result>=0.17.0 (Railway-oriented programming)
- alembic-postgresql-enum (safe ENUM migration)
- OpenTelemetry custom span attributes + decorators
- PEP 690 / PEP 810 lazy imports (Python 3.14/3.15)
- BPMN exclusive vs parallel vs inclusive gateways
- Kafka vs RabbitMQ vs NATS 2025 — habr.com, arxiv.org/2510.04404
- st.fragment (Streamlit partial rerender) — docs.streamlit.io
- schemathesis API fuzzing — schemathesis.readthedocs.io
- FastStream AsyncAPI autodoc
- mem0ai (persistent agent memory)
- instructor (structured LLM output with retry)

---

## 11. Changelog V16 → V17 → V18

| Ревизия | Дата | Краткое описание | Источник |
|---|---|---|---|
| **V15** | 2026-04-XX | 4 команды × 14-15 нед; 21+12 ADR; полный аналитический GAP (3382 строки) | `~/.claude/projects/.../memory/project_gap_analysis_v15.md` |
| **V16** | 2026-05-04 | 3 команды × 10-11 нед; ADR R1.6 hybrid plugin layout закрыт; формат сжатый | `PLAN.md` (history) |
| **V16.1** | 2026-05-06 | Sprint 0 GAP refinement через 3 read-only Explore-агента; +3 unit; перенос P0 (TaskRegistry → S1, per-plugin RL → S2); формализация DSL .saga() + StreamingLLM (S4); DLQ HTTP unified (S5); backpressure (S6); 2 Streamlit Tenants+Capabilities (S7); Playwright RPA + DI evaluation (S8) | `PLAN.md` V16.1 (399 строк) |
| **V17.0** | 2026-05-08 | GAP V3 — 32 пункта + 28 фич (F1–F8, U1–U4); BPMN/Notification/Audit DSL, Schema Registry UI, Hot Reload, Dry-run, Workflow Step Log, GraphQL Subscriptions, кэш-декораторы, CB/RL на функции, OLE/COM sidecar, lazy import AI, EventBus, унифицированный .convert(), result-монада, rule engine, NATS JetStream builder, msgspec hotpath, asyncio.TaskGroup, Granian RSGI ADR, alembic-postgresql-enum, advanced-alchemy Oracle, schemathesis CI, AsyncAPI autodoc, st.fragment | `gap-analysis/PLAN_V17.md` (619 строк) + `gap-analysis/GAP-анализ gd_integration_tools — Production Readiness.md` |
| **V18.0** | 2026-05-08 | V17 контент + V16.1 проверенная скелетная структура + per-wave статус + 5-командная изоляция (К1 Security / К2 Resilience+Perf / К3 DSL+Workflow / К4 AI+RAG / К5 Frontend+Ext+Mig); §2.5 матрица wave × status × owner; §2.7 shared-файлы + Pre-flight protocol; inline статус-маркеры ✅/🟡/⛔/⏳/🚫; ссылки на коммиты K1/S1 + S4/K3-D + S5/K4-MVP; §11 changelog | этот файл |
| **V18.1** | 2026-05-12 | Закрытие 2 wave (5 параллельных сессий): (1) Sprint 1 К3 `builder.py` split Stage 2.4 control_flow (`300d573`) — 17 методов choice/do_try/retry/parallel/saga/dead_letter/idempotent/fallback/throttle/delay/circuit_breaker/loop/timeout/switch/on_error/expire/correlation_id перенесены в `builders/control_flow.py` (292 LOC); builder.py остаток 1401 LOC / 68 методов; (2) Sprint 2 К1 idempotency wire-up V5 (`b5527ec`) — RedisNxBackend через SET NX EX + _LazyRedisProxy + build_idempotency_backend() factory + MemoryBackend fallback при недоступном DI, 9 unit + 3 integration tests; (3) детализация Sprint 1 К3 split на 6 stage-строк со статусами + коммитами; (4) фиксация план Stage 2.5 integration (~28 методов) + Stage 2.6 operational (~27 методов, новый файл `builders/operational.py`); (5) AuthBackend wave переведён ⏳→🟡 (другая сессия работает над `core/auth/{jwt_backend,jwks_cache,jwt_blacklist}.py`); (6) ProcessorRegistry formal API закрыт (`8e734be` stage-3) | этот файл |

---

**Конец PLAN.md V18.1 FINAL**. Полный GAP-анализ V3 — `gap-analysis/`. История контракта V11→V15 (3382 строки) — `~/.claude/projects/-home-user-dev-gd-integration-tools/memory/project_gap_analysis_v15.md`.
