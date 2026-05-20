# PLAN.md — gd_integration_tools

> **Версия**: V21.0 (Sprint 8/9/10/13/14 closed, S11 17/19 done, S12 16/17 done, Sprint 16 active — wave 1 in progress).
> **Дата**: 2026-05-20.
>
> **Главные изменения V21.0** (2026-05-20):
> - **Sync статусов S11/S12/S13/S14 с master git log**:
>   - **Sprint 11 AI/RAG Completion** — фактически 17/19 wave закрыто (PLAN.md V20 указывал 4/19): добавлены K1 W1/W2, K2 W1, K4 W1/W3/W4/W5/W6/W7/W8, K5 W1/W2/W3 + finale-closure.
>   - **Sprint 12 Workflow Enhancement** — фактически 16/17 wave закрыто (PLAN.md V20 указывал 0/17): K1 W1/W2, K2 W1/W2, K3 W1/W2/W3/W5/W6/W7/W8, K4 W2, K5 W1/W2/W3 + backbone.
>   - **Sprint 13 Infrastructure & Performance** — **закрыт** (19/19 + cleanup-lint + cleanup-type-check + cleanup-layers).
>   - **Sprint 14 Plugin Ecosystem** — **закрыт** (14/14 + cleanup A/B/C/D + wrapup-manage-cli).
> - **NEW Sprint 16 GAP-Closure 2 active** — Wave 1 = **L3-P0-1 OTel OTLP metrics** (минимальный риск, изолированный additive, стартуем с него вместо алфавитного порядка K1 W1).
> - **Carryover F-2/F-5/F-6** остаются в Sprint 15.
> - **Все BLOCKER'ы #1/#2/#3 закрыты**; AUDIT-1/2/3 закрыты.
>
> **Срок**: ~5-6 месяцев от 2026-05-20 (Sprint 16 active → финал) при **5 параллельных командах**.
> **Замещает**: V20.0 (Sprint 11 status outdated), V19.1.
> **Синхронизирован с**: `CLAUDE.md` V15, `gap-analysis/GAP-анализ gd_integration_tools актуальный.md` (2026-05-20), `KNOWN_ISSUES.md` (2026-05-20), `.claude/CONTEXT.md`.

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

## 2.5. Статус волн (snapshot 2026-05-20)

Sprint 0-10 + S13 + S14 **полностью закрыты**. Подробные wave-матрицы перенесены в `vault/session-*-summary.md` (см. колонку «Ключевая сводка»). Live wave Sprint 11 (17/19) + Sprint 12 (16/17) + Sprint 15 (planning) + Sprint 16 (active, wave 1 in progress) — §4 ниже.

| Sprint | Период | DoD итог | Wave-commits | Ключевая сводка |
|---|---|---|---|---|
| **S0 Hotfix** | 2026-05-04..05-07 | 80% (TaskIQ → S8, WAF → S8, OpenFeature → S8) | 20+ | `vault/session-2026-05-08-1911` (архив) |
| **S1 Resilience+Plugin** | 2026-05-08..05-11 | 90% (Single Entry, capability-gate, PydanticAI baseline, builder.py 2.4) | 18+ | `vault/session-2026-05-11` (архив) |
| **S2 ASGI+Repo+Auth** | 2026-05-12..05-13 | 92% (idempotency Redis NX, OTel asyncpg, perf-gate scaffold, ProcessorRegistry) | 14 | `feedback_s2_multi_agent_kickoff` |
| **S3 Plugin runtime+Sinks** | 2026-05-13..05-14 | 100% (25/25 wave, 41 commits, 310 unit-тестов, 45 feature-flags) | 25 | `feedback_s3_w3_orchestration_2026_05_13` |
| **S4 Workflow DSL+BPMN** | 2026-05-14 | 100% (Workflow DSL финал, BPMN-import, YAML round-trip, LLM-activity) | 14 | `feedback_sprint4_workflow_finale` |
| **S5 R2 Blocks+AI+Async** | 2026-05-13..05-14 | ~43% (17/40, остаток → S8 carryover) | 17 | `session-2026-05-15-0917-sprint5` (архив) |
| **S6 Perf+Chaos+Security** | 2026-05-14 | 92.9% (13/14, COM-sidecar → S8) | 24 | `session-2026-05-14-2025-sprint6` (архив) |
| **S7 Migration+Blue/Green** | 2026-05-15 | 100% (14/14, 5 carryover → S8) | 18 | `project_sprint7_status` |
| **S8 BLOCKER+Carryover+RPA+Rule** | 2026-05-15..05-18 | 100% (BLOCKER #3 WAF→0; +9 closure commits) | 30+ | `feedback_s8_closure` |
| **S9 GAP Closure+Pre-prod Gate**  | 2026-05-18..05-19 | 100% (36 wave + 12/12 DoD; 244 unit-тестов; pre-prod 20/20) | 36 | `project_sprint9_complete` |
| **S10 DSL Blueprint+DX Wizards**  | 2026-05-19..05-20 | 100% (24/24 wave + 5 s10-debt + 13 параллельных) | 42 | `project_sprint10_complete` |
| **S13 Infrastructure & Performance** | 2026-05-20 | 100% (19/19 wave + 3 cleanup: type-check + lint + layers) | 22 | `feedback_sprint13_closure` |
| **S14 Plugin Ecosystem** | 2026-05-20 | 100% (14/14 wave + 4 cleanup A/B/C/D + wrapup-manage-cli) | 19 | `feedback_s14_cleanup` |

**Все BLOCKER'ы закрыты на 2026-05-20**:
- ✅ **BLOCKER #1 TaskIQ removal** — CLOSED в S8 K2 W1 (`f36edd5e`).
- ✅ **BLOCKER #2 Workflow legacy purge** — CLOSED de-facto (S4 confirmed via Explore).
- ✅ **BLOCKER #3 WAF Phase-2** — CLOSED в S8 K1 W1 (`058705ed`, 0 violations).
- ✅ **AUDIT-1**: 5 quotas tests fix (S7 K1 regression) — закрыт в S8.
- ✅ **AUDIT-2**: Plugin hot-swap docs-drift — закрыт через `core/plugin_runtime/hot_swap.py`.
- ✅ **AUDIT-3**: windows-sidecar → windows_worker rename CLOSED (`aa987472`).

### Sprint 11-16 (active + planned)

| Sprint | Период | Focus | Команды |
|---|---|---|---|
| **S11 AI/RAG Completion**     | 2 нед | 17/19 закрыто; остаток: K4 W2 multimodal-rag-pipeline (untracked + WIP) | K1-K5 |
| **S12 Workflow Enhancement**  | 2 нед | 16/17 закрыто; остаток: K4 W1 ai-workflow-examples-lib (untracked yaml в `extensions/credit_pipeline/workflows/`) | K1-K5 |
| **S13 Infra & Perf**          | 2 нед | ✅ closed (19/19 + cleanup) | K1-K5 |
| **S14 Plugin Ecosystem**      | 2 нед | ✅ closed (14/14 + cleanup A/B/C/D + wrapup-manage-cli) | K1-K5 |
| **S15 DX Tooling + Innovation** | 2 нед | ⏳ planning + carryover S14 (F-2/F-5/F-6) | K1-K5 |
| **S16 GAP-Closure 2**         | 2 нед | **active**, wave 1 in progress (L3-P0-1 OTel OTLP metrics); 7 P0 + min cleanup (gap-analysis 2026-05-20) | K1-K5 |

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

## 3. Hotfix-неделя (Sprint 0, закрыта 80%)

20+ wave-commits в master. **Closed**: codeclone setup (`Makefile review-clones*`), antivirus dedup (`eaf0420`), codecs/converters (`7ce1421`, `8c81fba`), dsl/cli split (`9d03f0a`, `39e7c4f`), api_management split (`6cf53a7`), утилиты merge (`41c2b92`, `787e777`), ClickHouse pool (`945758f`, `83d0014`), Graylog persistent (`40e933a`, `34b4b8a`), orjson hotpath (`d503a98`, `a10b7ae`), idempotency-header (`efb92f1`), fastapi-easylimiter (`bd2c49f`, `7951eaa`), correlation-id (`efb92f1`), advanced-alchemy, TenantMiddleware (`89b6a2a`), Workflow legacy mark (`764ec37`, `96d3370`), Python-2 except syntax (`4f7327a`, `ea14cf2` 35+1 файлов).

**Carryover → Sprint 8**:
- ✅ TaskIQ removal — closed (`f36edd5e` S8 K2 W1, BLOCKER #1 CLOSED).
- 🔴 WAF Phase-2 — open (38 callsites, K1 W1 BLOCKER #3).
- ⏳ OpenFeature InMemoryProvider → Flagsmith — K1 W6.
- ⏳ Smoke CI stage → K2 W9.
- ⏳ Redis cluster + pipelining → deferred to S13 K2 W6.
- ⏳ ASGI body capture opt-in — pending.
- ⏳ standardwebhooks consolidation — pending (4 inline callsites).

Подробности — `vault/session-2026-05-08-*` + git-log закрытых S0 коммитов.

---

## 4. Sprint-расписание (S1-S7 закрыты + S8 active + S9-S15 планируемые)

### Sprint 1 — Resilience + Plugin Contract (закрыт 90%)

**DoD результат**: Single Entry CB/RL/Retry в `core/resilience/` (`672b40f`, `e07000b`), capability-gate runtime + `fs.create_new` + `code.execute` (`8114b14`), PII-filter в structlog, PydanticAI baseline, AIWorkspaceManager + AIFsFacade (`6aed506`), HttpxClient mTLS (`e017e51`), VaultSecretsBackend hvac KV v2 (`0671af8`), E2B sandbox (`600247c`), TaskRegistry + Watchdog (`1e3d107`, `2a6a048`, `9b8440c`), builder.py split stage 2.4 control_flow (`300d573`). 18+ wave-commits.

**Carryover → S8**: WAF Phase-2 callsites (38 шт, BLOCKER #3), `.crud_*` builder + schema-registry RAM, `@policy`/`@cached` decorators (S1 К2 W1-W2 закрыты в `core/resilience/cache_decorators.py` + `core/resilience/decorators.py`), Workflow legacy purge (закрыт de-facto в S4).

---

### Sprint 2 — ASGI middleware + AsyncRepo + Auth + Routes V11.1a (закрыт 92%)

**DoD результат**: idempotency middleware Redis NX TTL 2min (`b5527ec`), OTel asyncpg auto-instrumentation (`42ed620`), TaskWatchdog deadline + AIWorkspaceCleaner (`d9beed9`+`5549127`), perf-gate CI scaffold (`26aa05a`), ConnectionPoolHealthMonitor (`2aa4544`), testkit/pytest_plugin entry-point (`8af96c1`), ProcessorRegistry @processor + JSON-Schema (`f2f5b14`, ADR-0058), FileWatcherSource (`dacd89c`), 2 reference routes (`dc33a03`), AuthBackend Protocol + JWT joserfc shim (`af0c4f5`), LangFuse 3.x parallel shim (`ca5429d`), Python-2 except hotfix repo-wide 20 callsites (`461a6ce`), Multi-agent kickoff backbone (`371eace`, `07512b4`). 14 wave-commits.

**Carryover → S8**: AuthBackend cutover (joserfc default-ON), hot-reload watchfiles graceful drain, schema-import codegen (zeep+openapi-python-client), multi-tenant route overrides, audit trail DSL + ClickHouse `audit_events`, plugin codegen `make new-plugin`. Memory: [[feedback_s2_multi_agent_kickoff]].

---

### Sprint 3 — Plugin runtime + 3-tier auto-reg + Sinks + Notifications (закрыт 100%)

**DoD результат**: 25/25 wave, 41 commits, 310 unit-тестов, 45 feature-flags. Vault rotation hook (`003d33c`), OTel baggage propagation (`1df3b26`), supply-chain CI gate scaffold SBOM+pip-audit+cosign (`c8c8a5a`), Plugin manifest semver-check (`a3df2a6`), PerHostMeter (`1e11122`), ConnectionReuseManager (`e12b41e`), AsyncBulkhead+HW/LW alerts (`a241c85`), K8sHPAMetricsExporter (`182a538`), Apprise notification DSL (`d404ee2`), NATS JetStream DSL (`7711a4a`), FTP/SFTP DSL aioftp+asyncssh (`83ae219`), Workflow gateways XOR/AND/OR (`7a7b170`), Builder source-сахар (`0299e2b`), EmailIMAPSource (`3c01362`), GraphQLSubscriptionSource (`a3854dd`), service.toml loader+ServiceDSLRegistry (`5ed7c20`), LangMem baseline (`d7bfe42`), SearXNG provider (`3bb83f0`), MCP input_schema (`495e818`), LangfusePromptStorage (`886e346`), MultimodalRAG scaffold (`7253103`), Schema Registry UI (`52fb231`), Action Bus UI (`75376ee`), Plugin Marketplace UI (`18fada6`), Admin REST endpoints (`4f39641`).

Memory: [[feedback_s3_w3_orchestration_2026_05_13]].

---

### Sprint 4 — Workflow DSL обёртка над Temporal + BPMN + YAML round-trip (закрыт 100%)

**DoD результат**: WorkflowDeclaration Pydantic + YAML loader + WorkflowBuilder (`4ab3e98`, `b5d8ba2`, `c19a85c`), Compiler emitter + step_compilers + activity_bridge + registry 59 tests (`2e4d135`), LiteTemporalBackend + smoke 7 cases (`bdd6505`), Saga 2 production examples (orders+payments), BPMN-import stdlib `xml.etree` offline-friendly (`eb935d1`), YAML round-trip `to_yaml`/`from_yaml`/`diff` + semver (`1fb3ffb`), LLM-activity Temporal cost+retry+Heartbeat+structured output (`43084b1`), Workflow-replay UI Streamlit (`30ddd06`), Capability-gate activities + Vault rotation long-running (`3974537`), Auto-scaling 3 уровня (LocalProcessScaler+BulkheadScaler+K8sHpaExporter) (`b38a422`), Wave G hotfix (`ad3b5aa`). 14 wave-commits.

Memory: [[feedback_sprint4_workflow_finale]]. **Carryover → S5/S8**: ConnectionReuseManager+ClickHouse pool+Graylog pool финал, Invoker ASYNC_QUEUE → Temporal-activity adapter, `.invoke_workflow` builder, LangGraph checkpoints в Postgres, AI workflow examples.

---

### Sprint 5 — R2 Universal Blocks + AI Stack 2026 + Async Queue (закрыт ~43%)

**DoD результат**: K4 MVP scaffold — LiteLLM gateway / 3-tier RAG cache / BGE-M3 / LangMem / PydanticAI / StreamingLLM / 2 Streamlit pages / 58 тестов (`8c43219`+`2c38a57`); K3 R2 CDC enrichment + notify_cascade + blueprints subdir migration (`12c2f25f`); doc-generation DSL `.render_docx/.render_xlsx` (`30d24195` merged S5+S8 dual-tag). 17 wave-commits в master.

**Перенесено в S8 (carryover)**:
- K2 round 1: Outbox dispatcher (W2), DLQ unified для HTTP/SOAP/gRPC/Webhook (W3), Inbox dedup fail-closed (W4), 5 alerts+2 fallback chains (W5), Bulkhead defaults (W6), per-tenant RL namespace (W7).
- K4 round 1: Multimodal RAG (W1), RLM-hierarchical memory (W2), RAG cache invalidate Redis pub/sub (W3), BGE-M3 reranker (W4), `.rag_*/.memory_*` DSL + mem0ai (W6), Saga blueprint (W7), LiteLLM gateway final (W8).
- K3 round 2: workflow TaskGroup (W10), `.invoke_workflow` reply-channels (W11).
- K1 round 2: DLQ-replay RBAC (W2), Inbox audit PII-mask (W3).

Memory: `session-2026-05-15-0917-sprint5`.

---

### Sprint 6 — Performance + Chaos + Coverage + Security + Observability (закрыт 92.9%)

**DoD результат**: 24 wave-commits. SAML+AD adapter (`1565d338`, `8ca67968`), supply-chain финал — SBOM+pip-audit+cosign+bandit TLS (`1df39670`), OWASP API Top 10+ZAP+codeclone gate `--fail-on-new-clones` (`5e79e334`), k6+locust perf-suite + perf-gate CI p95<200ms RPS>1000 (`51f2f847`), Granian/uvloop + DB pool tuning + msgspec hotpath sweep (`ef5334f3`, `08da1f13`), ADR-0059 Granian RSGI, structlog batching wrapper (`40a66577`), Health-checks per-component (`83d933a4`), Backpressure model streaming (`fd6f078d`), msgspec benchmark (`3743c574`), schemathesis API fuzzing CI (`db04d827`), CI service-doc-gate `check_service_docs.py` (`a0a87641`), e2e×6 protocols (`b40e8331`), Coverage gate ≥70% (`53c5ab57`), Banking processors tests (`097a335a`), DSL Linter CLI+LSP (`0c9a0742`), Inspect AI eval (`9ee277c0`), DSPy critical (`51752fa1`), AI cost dashboard (`4a1f77f1`), 33 chaos-tests testcontainers (`e7b00bf8`), OutboxBackend Protocol+Fake (`36ca6757`), Layer-violations facade (`6b818829`).

**Carryover → S8**: COM Windows sidecar (RPA волна), DLQ-replay UI, Resilience Dashboard, Pool Monitor, 5 Grafana dashboards. HEAD: `4f6e9dab`. Memory: `session-2026-05-14-2025-sprint6`.

---

### Sprint 7 — Migration core → extensions/ + Blue/Green + Multi-agent + Live UI (закрыт 100%)

**DoD результат**: 18 wave-commits. T1 core_entities mv (`6b027e3b`+`9648772b`), T2 credit_pipeline SKB-Техно (`fdc80779`), T3 sqladmin+3 Streamlit pages (`2ecaa919`), T4 plugin-hotswap (`6e306d1f`+AUDIT-2 в `core/plugin_runtime/hot_swap.py` 279 LOC), per-tenant billing+quotas (`4f6e9dab`), supply-chain finale multi-artifact cosign (`fbf17665`), blue/green compose+ADR-0060, httpx unify httpx-retries+hishel (`036f59cc`), 7 Grafana dashboards+3 SLO-burn (`4183c211`), blueprints subdir migrate (`12c2f25f`), workflow versioning WorkflowVersionRegistry+Temporal patched API (`116f40ec`), multi-agent LangGraph supervisor (`7ab41984`), Voice Whisper STT+Coqui TTS (`17e97c58`), Image generation LiteLLM (`55c82d2f`), DLQ Replay UI (`d0e5a371`), Resilience Dashboard (`33aeb752`), Pool Monitor (`67420ee2`), 70_Tenants/71_Capabilities/30_Files_S3 (`e7051065`).

**Carryover → S8**: `@st.fragment` live refactor (стилистическое), 5 quotas-тестов fix (AUDIT-1 → S8 K1 W0). Memory: [[project_sprint7_status]].

---

### Sprint 8 — BLOCKER closure + Carryover + RPA stage 1 + HTTP/3 + Rule Engine (закрыт 100%) — см. §2.5 архив + memory `feedback_s8_closure`

---

### Sprint 9 — GAP Closure + Documentation + Pre-prod Gate (закрыт 100%) — см. §2.5 архив + memory `project_sprint9_complete`

---

### Sprint 10 — DSL Blueprint Expansion + DX Wizards (закрыт 100%) — см. §2.5 архив + memory `project_sprint10_complete`

---

### Sprint 11 — AI/RAG Completion (2 нед, 17/19 закрыто)

Завершение AI/RAG стека: Multimodal полный, Adaptive RAG, AI Model Registry UI, feedback loop с DSPy fine-tuning, batch inference production, distributed rate limiter Redis Cluster.

**S11 status (2026-05-20)**: 17/19 закрыто; финал-closure тоже зафиксирован (`c9629383`, `87156447`). Остаток: K4 W2 multimodal-rag-pipeline (в WIP/untracked-сессии).

| Команда | Wave | Wave-tag | Scope |
|---|---|---|---|
| **K1** | W1 ✅ | `[wave:s11/k1-w1-rag-pii-redaction]` `ab1307c6` | PII redaction в RAG retrieval (mask чувствительных полей в chunks перед LLM context). |
| **K1** | W2 ✅ | `[wave:s11/k1-w2-guardrails-per-tenant]` `c804ce15` | Lakera/Rebuff config per-tenant (банк vs SaaS разные thresholds). Config в `core/auth/tenant_settings`. |
| **K2** | W1 ✅ | `[wave:s11/k2-w1-distributed-rl-redis-cluster]` `1eca25a1` | INF-2.9: `redis-cell` CL.THROTTLE или Lua-скрипт для Redis Cluster, token-bucket per-tenant. |
| **K2** | W2 ✅ | `[wave:s11/k2-w2-db-read-replica-routing]` `41e2fffc` | PERF-6.7: `SmartSessionManager` — SELECT → replica, INSERT/UPDATE → primary. SQLAlchemy + asyncpg. |
| **K3** | W1 ✅ | `[wave:s11/k3-w1-adaptive-timeout-policy]` `159647cb` | INF-2.10: `.policy.adaptive_timeout(percentile=99, safety_factor=1.5)` — p99 за N запросов × safety_factor. |
| **K3** | W2 ✅ | `[wave:s11/k3-w2-rag-ingest-step]` `68192020` | DSL `.rag_ingest(source, modal="text"|"image"|"audio"|"video", collection)` step. |
| **K3** | W3 ✅ | `[wave:s11/k3-w3-rag-multi-query]` `fc9b6ef8` | DSL `.rag_query(strategy="dense"|"hybrid"|"hyde"|"multi_query", max_staleness_hours)` step. |
| **K4** | W1 ✅ | `[wave:s11/k4-w1-multimodal-rag-full]` `4913354f` | AI-3.1: markitdown (PDF/DOCX/HTML) + CLIP (images) + BLIP2 (image captions) + Whisper (audio). Cross-modal retrieval (text query → image+audio chunks). |
| **K4** | W2 ⏳ | `[wave:s11/k4-w2-multimodal-rag-pipeline]` | Pipeline: ingest → chunking → embedding → Qdrant (с modal payload) → retrieval → rerank → LLM context. **(WIP/untracked)** |
| **K4** | W3 ✅ | `[wave:s11/k4-w3-adaptive-rag-strategy]` `e1a5d814` | AI-3.9: query classifier (LLM-based) → select strategy (dense/hybrid/hyde/multi_query). Bench accuracy +15%. |
| **K4** | W4 ✅ | `[wave:s11/k4-w4-langgraph-checkpoint-ui]` `2e631ddc` | AI-3.5: `60_AI_Agent_Monitor.py` вкладка Checkpoints: active sessions → inspect state → time-travel restore. |
| **K4** | W5 ✅ | `[wave:s11/k4-w5-ai-feedback-dspy]` `95e42813` | AI-3.6: user feedback → dataset → DSPy BootstrapFewShot → optimized prompt → re-deploy. CRON nightly. |
| **K4** | W6 ✅ | `[wave:s11/k4-w6-ai-model-registry-ui]` `0e67a0c8` | AI-3.7: `49_Model_Registry.py` — статус, бенчмарки (latency/cost/quality), "Use in route" CTA. MLflow + HF Hub adapter. |
| **K4** | W7 ✅ | `[wave:s11/k4-w7-ai-route-optimization]` `34ecdd96` | AI-3.10: анализ логов outbound→inbound→processing → рекомендации (parallelization, caching, retry tuning). Generated PR с предложениями. |
| **K4** | W8 ✅ | `[wave:s11/k4-w8-embedding-ab-migration]` `39f55c34` | A/B migration между embedding моделями (BGE-M3 → BGE-M3-v2): индексация двух коллекций → A/B retrieval → switch без переиндексации. |
| **K5** | W1 ✅ | `[wave:s11/k5-w1-adaptive-rag-dashboard]` `f1b8c40c` | Streamlit dashboard для Adaptive RAG: strategy selection rate, accuracy per strategy. |
| **K5** | W2 ✅ | `[wave:s11/k5-w2-ai-feedback-page]` `83475c4b` | Streamlit `48_AI_Feedback.py` — collect feedback, view DSPy training runs. |
| **K5** | W3 ✅ | `[wave:s11/k5-w3-replica-dashboard]` `5790cdd4` | Grafana dashboard для read replica routing (SELECT replica vs primary ratio, lag). |
| **К1-К5** | finale | `[wave:s11/finale-closure]` `c9629383` + `[wave:s11/closure-summary]` `87156447` | DoD audit + CONTEXT/KNOWN_ISSUES/vault summary; compact session summary + CONTEXT topbar. |

**DoD Sprint 11** (10 критериев):
1. ✅ Multimodal ingest для PDF + image + audio + video с regression test.
2. ✅ Adaptive RAG strategy выбор работает (latency overhead < 50ms).
3. ✅ Model Registry UI с 5+ models и benchmarks.
4. ✅ Feedback loop → DSPy nightly run → measurable quality improvement.
5. ✅ Adaptive timeout per host (p99-based) активен в production routes.
6. ✅ Distributed RL Redis Cluster выдерживает 10K req/s.
7. ✅ Read replica routing с автоматическим failover.
8. ✅ LangGraph checkpoint UI restore работает.
9. ✅ PII redaction в RAG retrieval (test с CC/SSN data).
10. ✅ coverage ≥80%; p95 latency для RAG queries < 150ms.

---

### Sprint 12 — Workflow Enhancement (2 нед, 16/17 закрыто)

Visual diff, Cron UI, Cost estimation, Reactive workflows, Workflow template library, Saga compensation viewer, AI workflow examples library.

**S12 status (2026-05-20)**: 16/17 закрыто; backbone-features зафиксирован (`15fef108`). Остаток: K4 W1 ai-workflow-examples-lib (untracked yaml-файлы в `extensions/credit_pipeline/workflows/`: code_interpreter_loop, multi_agent_supervisor, rag_augmented_saga).

| Команда | Wave | Wave-tag | Scope |
|---|---|---|---|
| **К1-К5** | backbone | `[wave:s12/backbone-features]` `15fef108` | 18 S12 feature-flags + team_s12.k1..k5 ownership |
| **K1** | W1 ✅ | `[wave:s12/k1-w1-workflow-audit-log]` `c80a5b63` | Workflow execution audit log в ClickHouse (start/finish/cancel/signal events) с tenant-id + actor + duration. |
| **K1** | W2 ✅ | `[wave:s12/k1-w2-temporal-mtls-finale]` `97e25d98` | mTLS для Temporal worker → server cluster (production-ready security). |
| **K2** | W1 ✅ | `[wave:s12/k2-w1-workflow-sla-grafana]` `1a27c8c0` | Grafana dashboard «Workflow SLA compliance rate» (% workflow завершены в срок). |
| **K2** | W2 ✅ | `[wave:s12/k2-w2-temporal-worker-autoscale]` `4bded76c` | Auto-scale Temporal workers по queue depth (K8s HPA через PrometheusAdapter). |
| **K3** | W1 ✅ | `[wave:s12/k3-w1-visual-workflow-diff]` `6673b00e` | WF-4.2: `31_DSL_Visual_Editor.py` вкладка Workflow Diff — side-by-side Graphviz, color-coded (added=green/removed=red/modified=yellow). |
| **K3** | W2 ✅ | `[wave:s12/k3-w2-cron-builder-ui]` `1e03d67c` | WF-4.6: visual cron builder + preview Next 5 executions + timezone-aware (Москва) + dry-run simulation. Croniter library. |
| **K3+K4** | W3+W2 ✅ | `[wave:s12/k3-w3-k4-w2-workflow-cost-estimation]` `f26fbabc` | WF-4.7: cost estimator + LLM pricing (combined K3 W3 + K4 W2: historical p50/p95 + LLM tokens × model price). |
| **K3** | W4 ✅ | `[wave:s12/k3-w4-reactive-workflows]` `42d68e38` | WF-4.8: event-driven triggers (EventBus → workflow start) без polling. Debounce (5sec), deduplication (idempotency key). |
| **K3** | W5 ✅ | `[wave:s12/k3-w5-workflow-template-library]` `4ec774bc` | WF-4.3: `33_DSL_Templates.py` с живыми шаблонами (10 templates), semantic search (BGE-M3), one-click deploy. |
| **K3** | W6 ✅ | `[wave:s12/k3-w6-saga-compensation-viewer]` `4ea1bcc4` | UI просмотра статуса compensation steps при rollback (Streamlit page `17_Workflow_Replay.py` вкладка Saga). |
| **K3** | W7 ✅ | `[wave:s12/k3-w7-cancel-workflow-dsl]` `cca2d747` | DSL `.cancel_workflow(workflow_id, reason)` explicit cancel step + Temporal API integration. |
| **K3** | W8 ✅ | `[wave:s12/k3-w8-workflow-versioning-ui]` `c90ff8c8` | UI для VersionRegistry (`workflow.versioning_strategy = "patched"`) — pin version per route, rollback. |
| **K4** | W1 ⏳ | `[wave:s12/k4-w1-ai-workflow-examples-lib]` | 3 production-ready examples: RAG-augmented saga (credit risk), multi-agent supervisor (loan approval), Code-Interpreter loop (data analysis). **(WIP/untracked yaml в `extensions/credit_pipeline/workflows/`)** |
| **K5** | W1 ✅ | `[wave:s12/k5-w1-workflow-template-streamlit]` `5e4d38b1` | `33_DSL_Templates.py` Streamlit page (живые preview YAML + Mermaid рендер). |
| **K5** | W2 ✅ | `[wave:s12/k5-w2-hitl-history-viewer]` `7eb1d789` | UI history view для HITL approvals (кто/когда/решение/время) — продолжение S9 K3 HITL panel. |
| **K5** | W3 ✅ | `[wave:s12/k5-w3-cron-dashboard]` `4f4f2148` | Streamlit cron schedule dashboard — все scheduled workflows, last run, next run, success rate. |

**DoD Sprint 12** (10 критериев):
1. ✅ Visual workflow diff с color-coded changes.
2. ✅ Cron builder UI + preview работают.
3. ✅ Cost estimation pre-run точность ±20%.
4. ✅ Reactive workflows (event-driven) с тестом debounce.
5. ✅ Workflow template library с 10+ templates + semantic search.
6. ✅ Saga compensation viewer для production examples.
7. ✅ `.cancel_workflow()` DSL step + audit-event.
8. ✅ Temporal mTLS активен в staging compose.
9. ✅ Workflow SLA Grafana dashboard с 99% SLO.
10. ✅ coverage ≥80%; AI workflow examples деплоятся одной командой.

---

### Sprint 13 — Infrastructure & Performance (закрыт 100%) — см. §2.5 архив + memory `feedback_sprint13_closure`

**DoD результат**: 19/19 wave + 3 cleanup (type-check + lint + layers). HEAD: `1554cb8b`.

Закрыты: `5e0406d8` pii-streaming (K1 W1), `126f485a` degradation-rbac (K1 W2), `d43d12fe` rsgi-streaming-large-files (K2 W1), `26ef3548` clickhouse-columnar-builder (K2 W2), `bb821035` parallelism-analyzer (K2 W3), `0b8a5b54` graceful-degradation-finale (K2 W4), `0b787143` unified-retry-store (K2 W5), `58bdcd21` redis-cluster-pipelining (K2 W6), `e158852f` pool-warmup-finale (K2 W7), `3586383d` batch-processor (K3 W1), `60fc8980` webdav-source (K3 W2), `5d4857ec` eventbus-schema-validation (K3 W3), `19cdf141` dlq-ttl-policies (K3 W4), `9d911132` nats-consumer-lag-ui (K3 W5), `29aa1fa8` rag-cache-prewarm (K4 W1), `ea1c53a8` ai-batch-inference-prod (K4 W2), `14a166a1` degradation-panel (K5 W1), `62bee4eb` resilience-profile-editor (K5 W2), `75f46010` pipeline-parallelism-viewer (K5 W3), + cleanup `076a759d` type-check / `264be7dc` lint / `1554cb8b` layers.

---

### Sprint 14 — Plugin Ecosystem (закрыт 100%) — см. §2.5 архив + memory `feedback_s14_cleanup`

**DoD результат**: 14/14 wave + 4 cleanup A/B/C/D + wrapup-manage-cli. HEAD: `11305fb1`.

Закрыты: `0a601d58` compat-sandbox (K1 W1+W2), `9080e811` publish-plugin (K1 W3), `488ec423` capability-audit-extended (K1 W4), `11111a44` plugin-resource-monitor (K2 W1), `cfad3e94` sandbox-overhead-bench (K2 W2), `39dbb999` processor-catalog-search (K3 W1), `5cf0f52e` dsl-stubs-pyi (K3 W2), `07fb895a` ai-services-decorator (K4 W1), `9d206fe0` migration-generator (K5 W1), `de57180e` marketplace-admin (K5 W2-W3-W6), `fa1f1d66` plugin-dev-server (K5 W4), `fdaca95b` capability-graph-ui (K5 W5), + `11305fb1` wrapup-manage-cli (plugin publish + serve subcommands), + cleanup `9481993c` (F-1+F-4), `f71a59e4` (F-3), `a7e07f7c` (T-1..T-4), `85ae4457` (D-1 known-issues).

**Carryover S14 → S15** (документировано в `85ae4457`):
- F-2 PluginSandboxAdapter overhead 137% (target <5%, DoD §S14.5).
- F-5 `gen_dsl_stubs._resolve_annotation` fallback на `str(annotation)` (качество .pyi для PEP-695).
- F-6 `sys._current_frames()` приватный CPython API в `plugin_resource_monitor` — best-effort fallback.

---

### Sprint 15 — DX Tooling + Innovation (2 нед)

VSCode extension, ADR scaffolding, CLI completions, Changelog auto-gen, AI-assisted PR review, Interactive Architecture Map. Финальный спринт перед production-ready.

| Команда | Wave | Wave-tag | Scope |
|---|---|---|---|
| **K1** | W1 | `[wave:s15/k1-w1-vscode-ext-sign]` | Code-sign VSCode extension package (Microsoft cert или OVSX). |
| **K1** | W2 | `[wave:s15/k1-w2-final-security-audit]` | Финальный security audit (OWASP top 10 ZAP scan, OWASP API top 10, pip-audit с zero-tolerance). |
| **K2** | W1 | `[wave:s15/k2-w1-manage-py-diagnose]` | `manage.py diagnose` — граф зависимостей + циклические импорты + layer-violation + dead code. JSON output для CI integration. |
| **K2** | W2 | `[wave:s15/k2-w2-final-perf-bench]` | Финальный perf benchmark с baseline для production (p95 ≤80ms, RPS ≥1500). |
| **K2** | W3 | `[wave:s15/k2-w3-mypy-zero]` | Финал mypy reduction: ≤50 → 0 (zero errors). Strict mode enforced. |
| **K3** | W1 | `[wave:s15/k3-w1-vscode-lsp]` | LSP server для DSL (route.toml + workflow.yaml) — completion, hover docs, "Run step" CodeLens. |
| **K3** | W2 | `[wave:s15/k3-w2-dsl-visual-editor-finale]` | DSL Visual Editor финал — drag-drop + YAML/BPMN export + undo/redo + step palette с capability descriptions. Закрытие S9 carryover. |
| **K3** | W3 | `[wave:s15/k3-w3-yaml-schema-completion]` | YAML schema completion в VSCode (JSON Schema export → autocomplete для route.toml + workflow.yaml). |
| **K4** | W1 | `[wave:s15/k4-w1-ai-pr-review]` | DX-8.10: AI-assisted PR review GitHub Action — Claude analysis on PR (layer-policy / security / perf-regression / coverage delta). |
| **K4** | W2 | `[wave:s15/k4-w2-arch-map-llm-search]` | Semantic search в Interactive Arch Map (LLM-powered "find module that does X"). |
| **K5** | W1 | `[wave:s15/k5-w1-vscode-extension]` | DX-8.4: VSCode extension `.vsix` пакет в `tools/vscode-extension/`: highlighting + hover docs + "Run step" CodeLens + LSP client. |
| **K5** | W2 | `[wave:s15/k5-w2-make-new-adr]` | DX-8.7: `make new-adr TITLE="..."` — ADR scaffolding generator (template + автоматическая нумерация). |
| **K5** | W3 | `[wave:s15/k5-w3-cli-completions]` | DX-8.8: zsh/bash completions для `manage.py` (Typer auto-gen + install hooks). |
| **K5** | W4 | `[wave:s15/k5-w4-changelog-autogen]` | DX-8.9: changelog автогенерация из wave-коммитов (Conventional Commits parser). `make release-notes`. |
| **K5** | W5 | `[wave:s15/k5-w5-arch-map-streamlit]` | DX-8.11: Interactive Architecture Map в Streamlit (D3.js, нажать модуль → docstring + deps + tests + impact analysis). |
| **K5** | W6 | `[wave:s15/k5-w6-adr-log-wiki]` | DOC-7.4: ADR Decision Log в `60_Wiki.py` (Whoosh поиск + фильтр по статусу). |
| **K5** | W7 | `[wave:s15/k5-w7-dep-map-html]` | DOC-7.7: Интерактивная карта зависимостей (D3.js standalone HTML) — фильтры по слоям, "где используется X". |
| **K5** | W8 | `[wave:s15/k5-w8-tutorial-progress]` | Tutorial progress tracking в developer portal (галочки выполненных шагов + estimated time). |
| **K5** | W9 | `[wave:s15/k5-w9-changelog-diff-page]` | Streamlit page «Changelog Diff» между версиями (фильтр по команде/зоне). |
| **K1** | W3 | `[wave:s15/k1-w3-sandbox-overhead-reduction]` | **F-2 carryover (S14)**: PluginSandboxAdapter overhead 137% → <5%. Варианты: amortised psutil snapshot / fire-and-forget task / e2b enforcement / DoD relaxation для dev_light. |
| **K3** | W4 | `[wave:s15/k3-w4-pyi-stub-fidelity]` | **F-5 carryover (S14)**: `gen_dsl_stubs._resolve_annotation` через `typing.get_type_hints` + `get_origin/get_args`. Улучшение IDE-autocomplete для PEP-695. |

**Carryover S14 в S15**:
- F-2 PluginSandboxAdapter overhead 137% (target <5%, DoD §S14.5) → S15 K1 W3.
- F-5 `gen_dsl_stubs._resolve_annotation` fallback на `str(annotation)` (качество .pyi для PEP-695) → S15 K3 W4.
- F-6 `sys._current_frames()` приватный CPython API в `plugin_resource_monitor` — best-effort fallback (остаётся known-issue, не блокер).

**DoD Sprint 15** (11 критериев):
1. ✅ VSCode extension published (в private/public marketplace).
2. ✅ LSP server для DSL с completion + hover docs.
3. ✅ DSL Visual Editor финал (drag-drop + BPMN export + undo/redo).
4. ✅ AI PR review активен (GitHub Action runs on every PR).
5. ✅ `make new-adr` scaffolding в Makefile.
6. ✅ CLI completions для manage.py (zsh + bash).
7. ✅ Changelog auto-generated из wave-коммитов.
8. ✅ Interactive Arch Map в Streamlit с D3.js.
9. ✅ mypy errors = 0 (от ≤50 baseline).
10. ✅ coverage ≥83%; p95 ≤ 80ms; **система готова к production**.
11. ✅ PluginSandboxAdapter overhead <5% (или explicitly relaxed для dev_light с ADR).

---

### Sprint 16 — GAP-Closure 2 (active, P0 + критические P1 + min cleanup, 2 нед)

Закрытие 7 P0 задач из `gap-analysis/GAP-анализ gd_integration_tools актуальный.md` (2026-05-20)
+ минимальный cleanup (pyproject pruning, OE-3, DC-1).

**Порядок wave** (по риску, рекомендация explore-агента):
1. **Wave 1** = `[wave:s16/k2-w3-otel-otlp-metrics]` — L3-P0-1 (НИЗКИЙ риск, изолированный additive). **🔄 in progress**.
2. **Wave 2** = `[wave:s16/k3-w1-pygls-lsp-server]` — L4-P0-1 (НИЗКИЙ риск, новые файлы).
3. **Wave 3** = `[wave:s16/k4-w1-adaptive-rag-classifier]` — L5-P0-1 (НИЗКИЙ риск, расширение существующего).
4. **Wave 4** = `[wave:s16/k2-w1-asyncio-lock-registry]` — L1-P0-1 (ВЫСОКИЙ риск: 8 импортёров → await update).
5. **Wave 5** = `[wave:s16/k1-w1-asyncssh-pool]` — L1-P0-2/3 (СРЕДНИЙ риск, замена aioftp + SSL fix).
6. **Wave 6** = `[wave:s16/k2-w2-outbox-tx-atomic]` — L2-P0-1 (ВЫСОКИЙ риск, DB transactions, unit_of_work).

| Команда | Wave | Wave-tag | Scope |
|---|---|---|---|
| **K1** | W1 | `[wave:s16/k1-w1-asyncssh-pool]` | **L1-P0-2/3**: SFTP + FTP connection pooling через `asyncssh.SSHClient` (replace `infrastructure/clients/transport/ftp.py`). Session pool + reconnect + known_hosts. |
| **K2** | W1 | `[wave:s16/k2-w1-asyncio-lock-registry]` | **L1-P0-1 DEADLOCK FIX**: `services/schema_registry/registry.py:66` `threading.RLock` → `asyncio.Lock`; все `with self._lock:` → `async with self._lock:`. |
| **K2** | W2 | `[wave:s16/k2-w2-outbox-tx-atomic]` | **L2-P0-1**: Transactional Outbox — `infrastructure/messaging/outbox/dispatcher.py` пишет outbox event в **той же** DB-транзакции что и business data (advanced-alchemy unit_of_work). |
| **K2** | W3 🔄 | `[wave:s16/k2-w3-otel-otlp-metrics]` | **L3-P0-1** (Wave 1, in progress): подключить `OTLPMetricExporter` + `MeterProvider` + `PeriodicExportingMetricReader` в `infrastructure/observability/otel/setup.py` для workflow + REST endpoints. Default-OFF через ENV `OTLP_METRICS_ENABLED`. Grafana dashboard проверки. |
| **K3** | W1 | `[wave:s16/k3-w1-pygls-lsp-server]` | **L4-P0-1**: `tools/dsl_lsp/server.py` через `pygls>=2.0` (расширение текущего `dsl/cli/linter.py` batch-only). Completion + hover docs + diagnostics для route.toml + *.dsl.yaml. |
| **K4** | W1 | `[wave:s16/k4-w1-adaptive-rag-classifier]` | **L5-P0-1**: `QueryClassifier` (LLM-based) → выбор `RAGStrategy` (dense/hybrid/hyde/multi_query). Расширение S11 K4 W3 — добавить динамику. Bench accuracy +15%. |
| **K1** | W2 | `[wave:s16/k1-w2-jwt-introspection]` | **L7-P1-1**: endpoint `GET /auth/introspect` (RFC 7662) — token introspection. |
| **K1** | W3 | `[wave:s16/k1-w3-vault-rotation-impl]` | **L1-P1-4**: реализация ротации Vault secrets через `hvac` (flag `vault_rotation_enabled` уже есть). |
| **K2** | W4 | `[wave:s16/k2-w4-pybreaker-replace]` | **L1-P1-6**: заменить custom Circuit Breaker на `pybreaker>=1.2.0` (state persistence через Redis backend). |
| **K2** | W5 | `[wave:s16/k2-w5-redis-graceful-degrade]` | **L1-P1-3**: in-memory `TTLCache` fallback при Redis down (cachetools уже в deps). |
| **K5** | W1 | `[wave:s16/k5-w1-plugin-topo-sort]` | **L8-P1-1**: `PluginGraphResolver` через `cachetools.OrderedGraph` — topological sort + cycle detection для `plugin.toml::dependencies`. |
| **K5** | W2 | `[wave:s16/k5-w2-global-ratelimit-mw]` | **L9-P1-1**: ASGI-level `RateLimitMiddleware` (global) — `entrypoints/middlewares/global_rate_limit.py` через `fastapi-limiter`. |
| **K5** | W3 | `[wave:s16/k5-w3-coverage-gate-75]` | **L11-P1-1**: `[tool.coverage.report]::fail_under = 75` в pyproject.toml + `tools/coverage/breakdown_by_layer.py`. |

**Cleanup wave (cross-team, минимальный scope)**:

| Команда | Wave | Wave-tag | Scope |
|---|---|---|---|
| **K2** | W6 | `[wave:s16/k2-w6-litetemporal-simplify]` | **OE-3**: упростить `infrastructure/workflow/lite_temporal_backend.py` до thin wrapper (прямой вызов activity без full Temporal abstraction). |
| **K3** | W2 | `[wave:s16/k3-w2-routebuilder-clone-cleanup]` | **DC-1**: grep подтверждает 0 вызовов `RouteBuilder.clone()` → удалить метод и тесты. |
| **K1** | W4 | `[wave:s16/k1-w4-pyproject-prune-empties]` | Удалить 8 пустых extras из pyproject.toml: `iot`, `web3`, `legacy`, `banking`, `enterprise`, `datalake`, `temporal` (если пуст), `beam`. Добавить новые: `lsp = ["pygls>=2.0.0"]`, `circuit-breaker = ["pybreaker>=1.2.0"]`. |

**DoD Sprint 16** (10 критериев):
1. ✅ L1-P0-1 fixed: `asyncio.Lock` в schema_registry; 0 `threading.RLock` в async-коде (grep verify).
2. ✅ L1-P0-2/3: SFTP + FTP через asyncssh pool; reconnect автоматический; integration test с testcontainers.
3. ✅ L2-P0-1: Outbox dropped-message rate = 0 в chaos-test (kill между business-write и outbox-write).
4. ✅ L3-P0-1: OTel Metrics в Grafana visible; workflow duration + REST p95 экспортируются.
5. ✅ L4-P0-1: pygls LSP запускается, VSCode extension подключается, completion работает на route.toml.
6. ✅ L5-P0-1: Adaptive RAG QueryClassifier выбирает strategy динамически; bench accuracy +15% vs static.
7. ✅ JWT Introspection endpoint `/auth/introspect` отвечает 200/401 по RFC 7662.
8. ✅ Vault rotation реально ротирует secret раз в N часов (hvac call + audit-event).
9. ✅ pybreaker заменяет custom CB; state restored after restart.
10. ✅ Coverage gate 75% активен в CI; per-layer breakdown отчёт генерируется; pyproject pruning применён (0 пустых extras).

---

**Итого**: 16 спринтов (закрыты S0-S10, active S11+S14 partial, planned S12/S13/S15/S16). Из них первые 11 — за 2 недели, остальные — 2 недели каждый. Срок ~6-7 месяцев от 2026-05-20 до production-ready.

---

## 5. Финальная архитектура (V19, после Sprint 15)

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
│   │                  eventbus/,                                      # V17
│   │                  clients/clickhouse_bulk_writer.py,              # V19 NEW (S9 K2)
│   │                  sources/webdav.py,                              # V19 NEW (S13 K3)
│   │                  security/saml_backend.py,                       # V19 NEW (S9 K1)
│   │                  workflow/temporal_client.py}/                   # V19 NEW (S9 K3)
│   ├── services/{core,ai,integrations,ops,execution,
│   │            plugins,schema_registry,notebooks,
│   │            ai/gateway/token_budget.py}/                          # V19 NEW (S9 K1)
│   ├── dsl/{route,workflow,service,builders,codec,transforms,
│   │       contracts,engine/processors,blueprints,
│   │       adapters,helpers,versioning,integration_gateway,
│   │       orchestration,cli}/
│   ├── entrypoints/{api,grpc,soap,graphql,websocket,sse,
│   │               webhook,mqtt,cdc,filewatcher,scheduler,
│   │               email,stream,express,mcp,middlewares,
│   │               api/v1/endpoints/admin_dlq.py}/                    # V19 NEW (S9 K5)
│   ├── schemas/
│   └── main.py
│
├── src/frontend/              # ФРОНТ
│   └── streamlit_app/{app.py,api_client.py,pages/,components/,static/}
│   # Pages V17: 30_Files_S3.py, 35_Audit_Log.py, 40_Schema_Registry.py,
│   # 50_Workflow_Logs.py, 60_AI_Agent_Monitor.py,
│   # 70_Tenants.py, 71_Capabilities.py, 80_Admin_Models.py
│   # Pages V19 NEW: 30-39 DSL / 40-49 AI / 50-59 Ops / 60-69 Admin
│   # 47_AI_Safety.py (S9 K4 guardrails)
│   # 48_Prompt_Lab.py (S9 K4 LangFuse prompts)
│   # 48_AI_Feedback.py (S11 K5)
│   # 49_Model_Registry.py (S11 K4 MLflow+HF)
│   # 72_HITL_Panel.py (S9 K3 Temporal signal-wait approve/reject)
│   # 33_DSL_Templates.py (S12 K5 workflow templates)
│
├── extensions/                # БИЗНЕС-ПЛАГИНЫ (V15.1 hybrid layout)
│   ├── core_entities/         # users/orders/orderkinds/files
│   │   └── orders/workflows/  # V19 NEW (S9 K5 migration из src/backend/workflows/)
│   ├── credit_pipeline/       # СКБ-Техно/DaData/БКИ/СМЭВ/ЦБ/1С
│   │   └── workflows/         # V19 NEW (S9 K5 migration)
│   └── example_plugin/
│
├── routes/<name>/{route.toml, *.dsl.yaml}      # DSL-routes (V11.1a)
├── testkit/                   # gd-integration-tools-testkit sub-package
│   ├── recorder.py            # V19 NEW (S10 K5 cassette recorder)
│   └── cassettes/             # V19 NEW (VCR.py-style)
├── tools/{checks,codegen,imports,migrations,dsl,build,templates,
│         schema_importer/,
│         vscode-extension/}/  # V19 NEW (S15 K5 LSP+highlighting)
├── docs/{source,tutorials,runbooks,reference,adr,
│        alerts,grafana,clone-baseline.json,clone-reports/}
├── tests/{unit,integration,e2e,perf,chaos}/
├── config_profiles/{base,dev,dev_light,staging,prod}.yml
├── windows_worker/            # V17 → V19 renamed (AUDIT-3 closed `aa987472`)
│   ├── Dockerfile.windowsservercore
│   ├── main.py
│   └── handlers/{com_handler.py, desktop_rpa_handler.py, pywinauto_handler.py}
└── .claude/                   # служебная память Claude
```

---

## 6. pyproject.toml — полный список зависимостей V19

```toml
[project.dependencies]
# === Ядро (уже есть или добавить) ===
"openfeature-sdk>=0.9.0",       # Feature flags (Sprint 0 Day 5)
"aiocache[redis]>=1.0.0a0",     # Cache decorators (Sprint 1)
"result>=0.17.0",               # Railway-oriented programming (Sprint 1)

[project.optional-dependencies]
# === V17 (Sprint 3-8) ===
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

# === V19 NEW (Sprint 9-15) ===
rag-multimodal = ["markitdown>=0.0.1", "openai-whisper>=20240930", "torch>=2.5"]  # S11 K4 AI-3.1 multimodal
rpa-extra = ["pywinauto>=0.6.8", "patchright>=1.0.0"]         # S8 K3 RPA stage 1
http3 = ["aioquic>=1.2.0"]                                    # S8 K3 HTTP/3 + WebTransport
ai-registry = ["mlflow>=2.18.0", "huggingface-hub>=0.27.0"]   # S11 K4 Model Registry
ai-batch = ["vllm>=0.7.0"]                                    # S13 K4 batch inference (или transformers-cli)
ai-sandbox = ["e2b>=0.17.0"]                                  # S8 K4 code-interpreter
ai-structured = ["instructor>=1.7.0"]                          # S8 K4 .llm_structured()
ai-memory = ["mem0ai>=0.1.0"]                                  # S8 K4 mem0/Zep persistent
ai-dspy = ["dspy-ai>=2.5.0"]                                   # S11 K4 feedback→DSPy nightly
saml = ["pysaml2>=7.5.0"]                                      # S9 K1 SP-initiated SSO
plugin-sandbox = ["RestrictedPython>=8.0"]                     # S14 K1 plugin isolation
rate-limit-cluster = ["redis-cell"]                            # S11 K2 distributed RL Redis Cluster (via redis-cell module)
distributed-cache = ["hishel>=0.0.30"]                         # S7 уже подключён, для V19 reference
docling = ["docling>=2.20.0"]                                  # S11 K4 multimodal alternative
compression = ["brotli>=1.1.0"]                                # S10 K2 PERF-6.6 BrotliCompressionMiddleware

# === ai-2026 (дополнить существующие) ===
# + "instructor>=1.7.0",  + "mem0ai>=0.1.0",  + "dspy-ai>=2.5.0"

# === V20 NEW (Sprint 16) ===
lsp = ["pygls>=2.0.0"]                                         # S16 K3 W1 LSP server для DSL
circuit-breaker = ["pybreaker>=1.2.0"]                         # S16 K2 W4 pybreaker replace (state via Redis backend)

# === REMOVED V20 (empty extras, никогда не реализовано) ===
# iot = []          # удалено V20
# web3 = []         # удалено V20
# legacy = []       # удалено V20
# banking = []      # удалено V20
# enterprise = []   # удалено V20
# datalake = []     # удалено V20
# temporal = []     # удалено V20 (temporalio в base deps)
# beam = []         # удалено V20
```

---

## 7. Финальный DoD V19

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

### V19 NEW — GAP-closure (S9) acceptance criteria
- ✅ **Page numbering без коллизий** — Streamlit pages renumbered (DSL 30-39 / AI 40-49 / Ops 50-59 / Admin 60-69), удалены 2 дубликата.
- ✅ **Outbox/Inbox/DLQ финальная реализация** — `infrastructure/messaging/{outbox_dispatcher,inbox_dedup,dlq}.py` production-ready, при недоступном Redis Inbox → `InboxUnavailable`.
- ✅ **HITL Streamlit panel functional** — `pages/72_HITL_Panel.py` (Temporal signal-wait, approve/reject, st.fragment real-time).
- ✅ **Token budget per tenant enforced** — `services/ai/gateway/token_budget.py` (daily_limit + hourly_burst + Redis counter TTL 24h → 429 `TenantQuotaExceeded`).
- ✅ **RouteLoader hot-reload < 3 сек** — `dsl/route/loader.py` + watchfiles.
- ✅ **Plugin compatibility matrix enforces** — `plugin.toml::[plugin.compatibility]` блокирует несовместимые версии при загрузке.
- ✅ **Lazy processor loading + startup < 3s** — `LazyProcessorRegistry` + CI-gate.
- ✅ **ClickHouse bulk writer ≥ 10x throughput** — `clickhouse_bulk_writer.py` buffer + flush.
- ✅ **Adaptive RAG strategy** — query classifier → dense/hybrid/hyde/multi_query (S11 K4).
- ✅ **Visual workflow diff** — Graphviz color-coded (added=green/removed=red/modified=yellow).
- ✅ **Sandbox isolation для плагинов** — RestrictedPython + resource limits (overhead < 5%).
- ✅ **SAML SP-initiated SSO** — `infrastructure/security/saml_backend.py` pysaml2.
- ✅ **Pool warm-up** — `PoolWarmup` в lifespan (p95 < 50ms на холодном старте).

### V19 NEW — Innovation criteria
- ✅ **AI route optimization recommendations** — анализ outbound→inbound→processing → generated PR с предложениями (S11 K4 W7).
- ✅ **Adaptive timeout per host** — `.policy.adaptive_timeout(percentile=99, safety_factor=1.5)` (S11 K3 W1).
- ✅ **Reactive workflows (event-driven)** — EventBus → workflow start без polling + debounce 5s + deduplication (S12 K3 W4).
- ✅ **Interactive Architecture Map** — D3.js в Streamlit (нажать модуль → docstring + deps + tests + impact) (S15 K5 W5).
- ✅ **AI-assisted PR review** — Claude analysis on every PR (layer-policy / security / perf-regression / coverage delta) (S15 K4 W1).
- ✅ **VSCode extension + LSP** — completion, hover docs, "Run step" CodeLens, published в private/public marketplace (S15 K3 W1 + K5 W1).
- ✅ **Plugin compatibility matrix** — `make check-compat` блокирует install при конфликте (S14 K1 W1).
- ✅ **Plugin sandbox isolation** — RestrictedPython + resource limits (S14 K1 W2).

### V19 Метрики (target по Sprint 15)
- **Onboarding до working route**: ≤ 1 час (измерено через `tools/checks/onboarding_timer.py`).
- **Startup time dev_light**: ≤ 3 сек (от ~5 сек baseline S6, измерено через `startup-time-gate` CI).
- **p95 latency (cached route)**: ≤ 80 ms (от 200ms baseline S6).
- **RPS** (final perf bench): ≥ 1500.
- **mypy errors**: 0 (от ≤50 baseline S6/S8).
- **layer violations**: 0 (от 6 baseline).
- **Test coverage**: ≥ 83% (от 70% baseline S6).
- **Blueprint паттернов**: 25+ (от 5 baseline).
- **Tutorials**: 15+ / **Runbooks**: 20+ (от 9/10 в S9).
- **Chaos tests**: 33+ (S6 baseline сохранён).

---

## 8. Открытые ADR-вопросы

- **ADR R1.1** — точный синтаксис capability в `plugin.toml` (массив `["host", "*.glob"]` vs flat-keys).
- **ADR R1.5** — формат SLO-конфига (sloth YAML vs `route.toml::slo`).
- **ADR R1.7** — Single Entry policy наименование (resilience.yaml vs route.toml::policy vs plugin.toml::policy).
- ✅ **ADR R1.6** — закрыт: hybrid layout (shared/ + features/) для extensions/.
- **ADR R1.8** (V17 NEW) — EventBus backend выбор для production: NATS JetStream (простота, < 100K msg/s) vs Kafka (> 500K msg/s, log retention) vs RabbitMQ (сложная маршрутизация, AMQP).
- **ADR R1.9** (V17 NEW) — Granian ASGI vs Uvicorn: benchmark результат → решение о merge в production Dockerfile.
- **ADR R1.10** (V17 NEW) — DI container: `core/di/providers.py` 625 LOC remain vs migrate to `dependency-injector.DeclarativeContainer`.
- **ADR R1.11** (V19 NEW) — Page numbering convention для Streamlit (DSL 30-39 / AI 40-49 / Ops 50-59 / Admin 60-69 vs текущий хаос с 9 коллизиями). GAP-DSL-2 closure.
- **ADR R1.12** (V19 NEW) — Plugin sandbox строгость: RestrictedPython vs Docker isolation vs eBPF seccomp. Trade-off overhead vs security.
- **ADR R1.13** (V19 NEW) — Adaptive RAG dispatching policy: rule-based (low latency, конфиг) vs classification model (LLM-based, higher quality, +20-30ms overhead). S11 K4 W3.
- **ADR R1.14** (V19 NEW) — VSCode extension marketplace: private (внутри банка) vs public publish (OVSX/MS marketplace). S15 K5 W1.
- **ADR R1.15** (V19 NEW) — Path aliases registry для документации (`docs/source/path-aliases.toml`) — устранение docs-drift через single-source mapping.
- **ADR R1.16** (V19 NEW) — Bulk audit writer strategy: асинхронный in-memory buffer + flush (clickhouse-connect) vs ClickHouse async insert API (server-side buffer). Trade-off durability vs throughput. S9 K2.

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

# === V19 NEW (Sprint 9-15) ===
make doctor                                  # full env check + services healthcheck
make scaffold-route NAME=demo               # interactive wizard (Typer)
make simulate ROUTE=demo                    # CLI dry-run с waterfall
make check-compat                           # plugin compatibility matrix (S14)
make plugin-migrate-guide FROM=1.0 TO=2.0   # auto-generated migration guide
make new-adr TITLE="Adaptive RAG dispatch"  # ADR scaffolding (S15)
make plugin-dev NAME=demo                   # infra-only docker-compose + hot-reload + mocks
make publish-plugin PLUGIN=demo VERSION=1.0.0  # cosign sign + SBOM (S14)
make release-notes                          # changelog auto-gen (Conventional Commits)
make dsl-complexity-check                   # cyclomatic ≤50 / nesting ≤5 / steps ≤50 (S10)
manage.py dsl render ROUTE=demo --format mermaid|bpmn|svg  # flow diagram (S10)
manage.py diagnose                          # dep graph + cycles + layer-viol + dead code (S15)
manage.py plugin serve --name=demo          # local dev server with mocks (S14)
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

### V19 NEW (Sprint 9-15 web research 2026)
- **pysaml2 7.5+** — SAML SP-initiated SSO Python — github.com/IdentityPython/pysaml2
- **markitdown** — universal multimodal parser (PDF/DOCX/HTML → markdown) — github.com/microsoft/markitdown
- **CLIP / BLIP2** — multimodal embeddings (text+image cross-modal retrieval) — github.com/openai/CLIP, github.com/salesforce/LAVIS
- **vLLM 0.7+** — batch inference for LLM, PagedAttention — docs.vllm.ai
- **e2b 0.17+** — sandboxed code execution (cloud sandboxes for AI agents) — e2b.dev/docs
- **redis-cell** — distributed token bucket (Redis module CL.THROTTLE) — github.com/brandur/redis-cell
- **aioquic 1.2+** — HTTP/3 + QUIC + WebTransport Python implementation — github.com/aiortc/aioquic
- **RestrictedPython 8.0+** — sandboxing для плагинов (limit imports + builtins) — github.com/zopefoundation/RestrictedPython
- **Brotli 1.1+** — compression middleware (-60% JSON traffic) — github.com/google/brotli
- **D3.js 7+** — interactive graphs для Streamlit (dependency graphs + arch map) — d3js.org
- **VSCode extension API + LSP** — language server protocol для DSL completion — microsoft.github.io/language-server-protocol
- **DSPy 2.5+** — prompt optimization framework (BootstrapFewShot, MIPRO) — dspy.ai
- **mlflow 2.18+ / huggingface-hub 0.27+** — AI model registry adapters
- **patchright 1.0+** — anti-detection Playwright fork для RPA — github.com/Kaliiiiiiiiii-Vinyzu/patchright
- **pywinauto 0.6.8+** — Windows desktop UI automation (Win32/UIA backend) — pywinauto.readthedocs.io
- **PaddleOCR / EasyOCR** — OCR engines для RPA → text extraction
- **Lakera / Rebuff** — prompt injection guardrails (classification models)
- **docling 2.20+** — multimodal RAG parsing alternative — github.com/DS4SD/docling

---

## 11. Changelog V16 → V17 → V18 → V19

| Ревизия | Дата | Краткое описание | Источник |
|---|---|---|---|
| **V15** | 2026-04-XX | 4 команды × 14-15 нед; 21+12 ADR; полный аналитический GAP (3382 строки) | `~/.claude/projects/.../memory/project_gap_analysis_v15.md` |
| **V16** | 2026-05-04 | 3 команды × 10-11 нед; ADR R1.6 hybrid plugin layout закрыт; формат сжатый | `PLAN.md` (history) |
| **V16.1** | 2026-05-06 | Sprint 0 GAP refinement через 3 read-only Explore-агента; +3 unit; перенос P0 (TaskRegistry → S1, per-plugin RL → S2); формализация DSL .saga() + StreamingLLM (S4); DLQ HTTP unified (S5); backpressure (S6); 2 Streamlit Tenants+Capabilities (S7); Playwright RPA + DI evaluation (S8) | `PLAN.md` V16.1 (399 строк) |
| **V17.0** | 2026-05-08 | GAP V3 — 32 пункта + 28 фич (F1–F8, U1–U4); BPMN/Notification/Audit DSL, Schema Registry UI, Hot Reload, Dry-run, Workflow Step Log, GraphQL Subscriptions, кэш-декораторы, CB/RL на функции, OLE/COM sidecar, lazy import AI, EventBus, унифицированный .convert(), result-монада, rule engine, NATS JetStream builder, msgspec hotpath, asyncio.TaskGroup, Granian RSGI ADR, alembic-postgresql-enum, advanced-alchemy Oracle, schemathesis CI, AsyncAPI autodoc, st.fragment | `gap-analysis/PLAN_V17.md` (619 строк) + `gap-analysis/GAP-анализ gd_integration_tools — Production Readiness.md` |
| **V18.0** | 2026-05-08 | V17 контент + V16.1 проверенная скелетная структура + per-wave статус + 5-командная изоляция (К1 Security / К2 Resilience+Perf / К3 DSL+Workflow / К4 AI+RAG / К5 Frontend+Ext+Mig); §2.5 матрица wave × status × owner; §2.7 shared-файлы + Pre-flight protocol; inline статус-маркеры ✅/🟡/⛔/⏳/🚫; ссылки на коммиты K1/S1 + S4/K3-D + S5/K4-MVP; §11 changelog | этот файл |
| **V18.1** | 2026-05-12 | Закрытие 2 wave (5 параллельных сессий): (1) Sprint 1 К3 `builder.py` split Stage 2.4 control_flow (`300d573`) — 17 методов choice/do_try/retry/parallel/saga/dead_letter/idempotent/fallback/throttle/delay/circuit_breaker/loop/timeout/switch/on_error/expire/correlation_id перенесены в `builders/control_flow.py` (292 LOC); builder.py остаток 1401 LOC / 68 методов; (2) Sprint 2 К1 idempotency wire-up V5 (`b5527ec`) — RedisNxBackend через SET NX EX + _LazyRedisProxy + build_idempotency_backend() factory + MemoryBackend fallback при недоступном DI, 9 unit + 3 integration tests; (3) детализация Sprint 1 К3 split на 6 stage-строк со статусами + коммитами; (4) фиксация план Stage 2.5 integration (~28 методов) + Stage 2.6 operational (~27 методов, новый файл `builders/operational.py`); (5) AuthBackend wave переведён ⏳→🟡 (другая сессия работает над `core/auth/{jwt_backend,jwks_cache,jwt_blacklist}.py`); (6) ProcessorRegistry formal API закрыт (`8e734be` stage-3) | этот файл |
| **V18.2** | 2026-05-14 | Sprint 6 запуск 5-команд параллельно с S5/S7; backbone-commit `[wave:s6/backbone]` + 21 default-OFF feature-flag + ownership-список `.claude/team-ownership.toml::[team_s6.kN]`; stub/adapter паттерн для S5→S6 зависимостей; досрочные коммиты `3743c574` (msgspec-benchmark) + `6b818829` (layer-violations-facade) | этот файл (V18.1 → V18.2) |
| **V19** | 2026-05-15 | (1) **Compression S0-S7** — 235 строк wave-таблиц → 50 строк summary с ссылками на vault/коммиты; (2) **Sprint 8 live-matrix** — 6/49 closed (12.2%), 8A blocker+carryover / 8B native scope, audit findings AUDIT-1/2/3; (3) **Sprint 9 expansion** — GAP-closure (RouteLoader full-cycle, Streamlit page renumbering без коллизий, messaging Outbox/Inbox/DLQ finale, HITL panel, token budget per tenant, SAML SP-initiated, lazy processors, pool warm-up, ClickHouse bulk writer ≥10x); (4) **Sprint 10-15 NEW** — 85 фич из `gap-analysis/FEATRE-ROADMAP.md` распределены (DSL blueprint expansion 5→20+, DX wizards make doctor/scaffold/simulate, AI/RAG completion multimodal+Adaptive+Model Registry+DSPy, Workflow enhancement visual diff+cron+reactive+templates, Infra perf RSGI+CH columnar+parallelism+graceful, Plugin ecosystem compatibility+migration+marketplace+sandbox, DX tooling VSCode+LSP+ADR+CLI+Arch Map); (5) +6 новых ADR R1.11-R1.16; (6) +14 новых `[project.optional-dependencies]` (rag-multimodal, rpa-extra, http3, ai-registry/batch/sandbox/structured/memory/dspy, saml, plugin-sandbox, rate-limit-cluster, compression, docling); (7) Финальный DoD V19 с innovation criteria (AI route optimization, Adaptive timeout, Reactive workflows, Interactive Arch Map, AI PR review, VSCode LSP); (8) Метрики: coverage ≥83%, mypy 0, p95 ≤80ms, blueprints 25+, tutorials 15+/runbooks 20+ | `gap-analysis/GAP-анализ актуальный.md` + `gap-analysis/FEATRE-ROADMAP.md` + `.claude/CONTEXT.md` 2026-05-15 |
| **V19.1** | 2026-05-18 | Sprint 8 closure: 9 commits в master (BLOCKER #3 WAF Phase-2 → CLOSED `058705ed`, DLQ unified scaffold `ffd84769`, Inbox fail-closed `02587c14`, finale `79223758` + 5 carryover commits). Sprint 9 backbone landed: 7 default-OFF feature-flags + team ownership k1-k5 | `feedback_s8_closure` + `.claude/CONTEXT.md` 2026-05-18 |
| **V20.0** | 2026-05-20 | (1) **Compression Sprint 8/9/10** в архив §2.5 (~120 строк удалено из §4); (2) **Sprint 11 status update** (4/19 wave closed: `41e2fffc` db-read-replica, `159647cb` adaptive-timeout, `68192020` rag-ingest, `fc9b6ef8` rag-multi-query); (3) **Sprint 14 cleanup wave A/B/C/D ✅** (F-1/F-3/F-4 closed, T-1..T-4 closed, D-1 known-issues docs) + carryover F-2/F-5/F-6 → Sprint 15; (4) **NEW Sprint 16 GAP-Closure 2** — 7 P0 (asyncio.Lock deadlock fix, asyncssh SFTP/FTP pool, transactional Outbox, OTel metrics OTLP, pygls LSP server, adaptive RAG classifier) + 5 top P1 (JWT introspection RFC 7662, Vault rotation impl hvac, pybreaker CB replace, Redis graceful degrade TTLCache fallback, plugin topo-sort) + global ASGI rate limit + coverage 75% gate; (5) **min cleanup**: OE-3 LiteTemporalBackend simplify + DC-1 RouteBuilder.clone() removal + pyproject pruning 8 empty extras (iot/web3/legacy/banking/enterprise/datalake/temporal/beam); (6) **+2 NEW optional extras**: `lsp = ["pygls>=2.0.0"]`, `circuit-breaker = ["pybreaker>=1.2.0"]`; (7) Все BLOCKER'ы #1/#2/#3 закрыты; AUDIT-1/2/3 закрыты | `gap-analysis/GAP-анализ gd_integration_tools актуальный.md` 2026-05-20 + KNOWN_ISSUES.md 2026-05-20 + CONTEXT.md |
| **V21.0** | 2026-05-20 | (1) **Sync статусов S11/S12/S13/S14 с master git log**: Sprint 11 → 17/19 wave закрыто (PLAN.md V20 указывал 4/19 — расхождение: K1 W1/W2, K2 W1, K4 W1/W3/W4/W5/W6/W7/W8, K5 W1/W2/W3 + finale-closure `c9629383` + closure-summary `87156447`); Sprint 12 → 16/17 wave закрыто (PLAN.md V20 указывал 0/17 — расхождение: K1 W1/W2, K2 W1/W2, K3 W1/W2/W3/W5/W6/W7/W8, K4 W2, K5 W1/W2/W3 + backbone `15fef108`); Sprint 13 → **закрыт** (19/19 + cleanup `076a759d`/`264be7dc`/`1554cb8b`); Sprint 14 → **закрыт** (14/14 + 4 cleanup A/B/C/D + wrapup-manage-cli `11305fb1`); (2) **Перенос S13/S14 в архив §2.5** (wave-матрицы заменены на summary-строки + memory-ссылки `feedback_sprint13_closure` / `feedback_s14_cleanup`); (3) **Sprint 16 active, wave 1 in progress** — Wave 1 = **L3-P0-1 OTel OTLP metrics** (минимальный риск, изолированный additive, стартуем с него вместо алфавитного K1 W1); порядок остальных 5 waves: pygls LSP → adaptive RAG → asyncio.Lock → asyncssh pool → outbox-tx-atomic; (4) Carryover F-2/F-5/F-6 остаются в Sprint 15; (5) untracked файлы параллельных сессий (S11 K4 W2/W7, S12 K3 W4/W6/W8, S11 K4 W5 dspy) не трогаются в Wave 1 | `gap-analysis/GAP-анализ gd_integration_tools актуальный.md` 2026-05-20 + git log master 2026-05-20 + CONTEXT.md |

---

**Конец PLAN.md V21.0**. Полный GAP-анализ актуальный (обновлён 2026-05-20) — `gap-analysis/GAP-анализ gd_integration_tools актуальный.md`. История контракта V11→V15 (3382 строки) — `~/.claude/projects/-home-user-dev-gd-integration-tools/memory/project_gap_analysis_v15.md`. Архив wave Sprint 0-7 — `vault/session-*-summary.md`. Архив Sprint 8/9/10/13/14 — §2.5 + memory `feedback_s8_closure` / `project_sprint9_complete` / `project_sprint10_complete` / `feedback_sprint13_closure` / `feedback_s14_cleanup`.
