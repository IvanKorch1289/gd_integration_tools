# PLAN.md — gd_integration_tools

> **Версия**: V19.1 (V19 + Sprint 8 closure + Sprint 9 backbone, 2026-05-18).
> **Дата**: 2026-05-18 (предыдущая V19 — 2026-05-15).
>
> **V19.1 правки (2026-05-18 coordinator-self closure)**:
> - **Sprint 8 status**: добавлены 9 commits закрытия (см. .claude/CONTEXT.md):
>   `[wave:s5/k5-w1-workflow-logs-ui]` cherry-pick (`0b626312`),
>   `[wave:s8/backbone-gitignore]` (`6cde09f8`), `[docs:gap-analysis-v19]` (`82f6cbf8`),
>   `[wave:s8/cleanup]` 98 файлов carryover (`6f850f6c`),
>   `[wave:s8/cleanup-fixup]` langmem (`59e3c291`),
>   `[wave:s8/k1-w1-waf-phase2-finale]` BLOCKER #3 (`058705ed`),
>   `[wave:s8/k2-w3-dlq-unified]` scaffold (`ffd84769`),
>   `[wave:s8/k2-w4-inbox-fail-closed]` (`02587c14`),
>   `[wave:s8/finale-dod-v19]` (`79223758`).
> - **BLOCKER #3 WAF Phase-2 → CLOSED** (3 callsites мигрированы, 0 violations).
> - **Sprint 8 carryover в Sprint 9** (см. KNOWN_ISSUES.md):
>   `AugmentResult`/`WebhookSignVerifyProcessor`/`PluginCodegen` отсутствующие
>   классы, `dsl/service` shadowing, DLQ full integration (4 транспорта),
>   WAF allowlist tightening ~13 callsites, AUDIT-2 docs-drift.
> - **Sprint 9 backbone**: 7 default-OFF feature flags + S9 team-ownership
>   k1-k5 + memory note `feedback_s8_closure.md`.
>
> **Sprint 8 итог**: 8B native scope + 8A wave-commits + S8-closure (9 commits) =
> ~25% wave-DoD; остальное → S9 carryover (10+ wave) с явными ссылками.
> **Sprint 9 status**: backbone landed; первые wave (route_loader_hot_reload,
> streamlit_page_renumber, docs-tutorials) — следующая session с usage probe ≥40%.

> **Версия V19 (архив)**: V18.2 + Sprint 8 live-matrix + Sprint 9 GAP-closure expansion + Sprint 10-15 from FEATRE-ROADMAP, 2026-05-15.
> **V19 правки** (2026-05-15): (1) **Compression S0-S7** — wave-таблицы (~235 строк) сжаты в summary-блоки с ссылками на коммиты/vault, удалены детальные wave × status × ref таблицы; (2) **Sprint 8 live wave-matrix** — 6/49 закрыто (12.2%), 8A blocker+carryover закрытие + 8B native scope, audit findings AUDIT-1/2/3; (3) **Sprint 9 expansion** — GAP-closure спринт (RouteLoader full-cycle, Streamlit page renumbering, messaging Outbox/Inbox/DLQ finale, HITL panel, token budget per tenant, SAML SP-initiated, lazy processors, pool warm-up, ClickHouse bulk writer); (4) **Sprint 10-15 NEW** — 85 фич из `gap-analysis/FEATRE-ROADMAP.md` распределены по 6 спринтам (DSL blueprint expansion + DX wizards, AI/RAG completion, workflow enhancement, infra perf, plugin ecosystem, DX tooling + innovation); (5) +6 новых ADR R1.11-R1.16; (6) +14 новых `[project.optional-dependencies]`; (7) Финальный DoD V19 с innovation criteria; (8) Метрики: coverage ≥83%, mypy 0, p95 ≤80ms, blueprints 25+, tutorials 15+/runbooks 20+.
> **Срок**: ~7-8 месяцев (Sprint 8 active → Sprint 15 финал) при **5 параллельных командах**.
> **Замещает**: V18.2 (Sprint 6 запуск note), V18.1, V18.0.
> **Синхронизирован с**: `CLAUDE.md` V15 (обновлён 2026-05-15), `gap-analysis/GAP-анализ gd_integration_tools актуальный.md` (55 GAP items P0-P3 + 13 docs-drift), `gap-analysis/FEATRE-ROADMAP.md` (85 фич + 8 спринтов S9-S16), `SPRINT_8_PLAN.md` (333 строки, 49 wave 8A/8B), `.claude/CONTEXT.md` (2026-05-15 10:13), 6 wave-commits Sprint 8 (`f36edd5e`, `87b96eaa`, `aa987472`, `c89e9d12`, `bfa33c63`, `30d24195`).

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

## 2.5. Статус волн (snapshot 2026-05-15)

Sprint 0-7 **полностью закрыты**. Подробные wave-матрицы перенесены в `vault/session-*-summary.md` (см. колонку «Ключевая сводка»). Live-матрица Sprint 8 — §4 Sprint 8 ниже.

| Sprint | Период | DoD итог | Wave-commits | Ключевая сводка |
|---|---|---|---|---|
| **S0 Hotfix** | 2026-05-04..05-07 | 80% (TaskIQ → S8, WAF → S8, OpenFeature → S8) | 20+ | `vault/session-2026-05-08-1911` |
| **S1 Resilience+Plugin** | 2026-05-08..05-11 | 90% (Single Entry, capability-gate, PydanticAI baseline, builder.py 2.4) | 18+ | `vault/session-2026-05-11` |
| **S2 ASGI+Repo+Auth** | 2026-05-12..05-13 | 92% (idempotency Redis NX, OTel asyncpg, perf-gate scaffold, ProcessorRegistry) | 14 | `feedback_s2_multi_agent_kickoff` |
| **S3 Plugin runtime+Sinks** | 2026-05-13..05-14 | 100% (25/25 wave, 41 commits, 310 unit-тестов, 45 feature-flags) | 25 | `feedback_s3_w3_orchestration_2026_05_13` |
| **S4 Workflow DSL+BPMN** | 2026-05-14 | 100% (Workflow DSL финал, BPMN-import, YAML round-trip, LLM-activity) | 14 | `feedback_sprint4_workflow_finale` |
| **S5 R2 Blocks+AI+Async** | 2026-05-13..05-14 | ~43% (17/40, остаток → S8 carryover) | 17 | `session-2026-05-15-0917-sprint5` |
| **S6 Perf+Chaos+Security** | 2026-05-14 | 92.9% (13/14, COM-sidecar → S8) | 24 | `session-2026-05-14-2025-sprint6` |
| **S7 Migration+Blue/Green** | 2026-05-15 | 100% (14/14, 5 carryover → S8) | 18 | `project_sprint7_status` |

**Активные BLOCKERs** (на 2026-05-15):
- ✅ **BLOCKER #1 TaskIQ removal** — CLOSED в S8 K2 W1 (`f36edd5e`).
- 🔴 **BLOCKER #3 WAF Phase-2** — OPEN, S8 K1 W1 (38 callsites выявлены, не мигрированы).
- ⏳ **BLOCKER #2 Workflow legacy purge** — закрыт de-facto (S4 confirmed via Explore: legacy state*.py файлы отсутствуют).
- 🔴 **AUDIT-1**: 5 quotas tests fail (S7 K1 regression) → S8 K1 W0.
- 🟢 **AUDIT-2**: Plugin hot-swap docs-drift (real impl `core/plugin_runtime/hot_swap.py`).
- ✅ **AUDIT-3**: windows-sidecar → windows_worker rename CLOSED (`aa987472`).

### Sprint 8 live wave-matrix (active 2026-05-15)

49 wave (после in-flight 5-close adjustment). Закрыто **6/49 = 12.2%** в master:

| Команда | Closed | In-Progress | Pending |
|---|---|---|---|
| **K1 Security** (8) | W8 `bfa33c63` pre-receive-docstring | W5 cosign-all (stash-loss recovery) | W0 quotas-fix, W1 WAF-phase2 (BLOCKER #3), W2 DLQ-replay-RBAC, W3 Inbox-audit-PII, W4 PII-DSL-step, W6 OpenFeature-Flagsmith, W7 prompt-injection-guardrails |
| **K2 Resilience+Perf** (12) | W1 `f36edd5e` TaskIQ-removal (BLOCKER #1) | W8 httpx-unify (ECONNRESET) | W2 outbox-dispatcher, W3 DLQ-unified, W4 Inbox-fail-closed, W5 alerts+chains, W6 Bulkhead-defaults, W7 tenant-RL-namespace, W9 Grafana+SLO, W10 mypy≤50, W11 deptry/vulture, W12 layer-viol=0 |
| **K3 DSL+Workflow** (12) | W1 `aa987472` windows-worker, W5 `87b96eaa` rule-engine-protocol | W8 dsl/blueprints/ subdir | W2 patchright-pool, W3 RPA-OCR, W4 RPA-Windows-desktop, W6 HTTP/3+WebTransport, W7 legacy-DSL-Python→YAML, W9 workflow-versioning, W10 workflow-TaskGroup, W11 invoke_workflow-reply, W12 MCP-via-FastMCP, W13 plugin-hotswap-impl |
| **K4 AI+RAG** (11) | W11 `c89e9d12` llm-structured-scaffold | — | W1 multimodal-RAG, W2 RLM-hierarchical, W3 RAG-cache-invalidation, W4 BGE-M3-reranker, W5 7 RAG-Streamlit-pages, W6 mem0+`.rag_*/.memory_*` DSL, W7 saga-blueprint, W8 LiteLLM-final, W9 AI-model-registry, W10 batch-inference, W11.5 code-interpreter |
| **K5 Frontend+Ext+Mig** (5) | merged `30d24195` doc-generation-DSL (S5+S8 dual-tag) | — | W1 5 credit-clients migration, W2 70_Tenants, W3 71_Capabilities, W4 30_Files_S3, W5 @st.fragment-live |

**Sprint 8A (1 неделя ~28 wave)** = BLOCKER + carryover closure: K1 W0/W1/W2/W3/W4/W5/W6, K2 W2-W7, K3 W8/W9/W10/W11/W13, K4 W1/W2/W3/W4/W6/W7/W8, K5 W2/W3/W4.

**Sprint 8B (1 неделя ~21 wave)** = native scope: K1 W7/W8, K2 W8-W12, K3 W2-W7/W12, K4 W5/W9/W10/W11.5, K5 W1/W5 + backbone/finale (`pyproject.toml` flags flip default-ON post-smoke).

Подробности — `SPRINT_8_PLAN.md` (333 строки, wave-by-wave детализация).

### Sprint 9-15 (планируемые)

| Sprint | Период | Focus | Команды |
|---|---|---|---|
| **S9 GAP Closure** | 2 нед | RouteLoader hot-reload, page renumbering, messaging Outbox/Inbox/DLQ finale, HITL panel, token budget, SAML SP-initiated, lazy processors, pool warm-up, CH bulk writer | K1-K5 |
| **S10 DSL Blueprint+DX** | 2 нед | Blueprint lib 5→20+, DSL dry-run UI, complexity budget, A/B test, semantic search, doctor/scaffold/simulate/plugin-dev, cassette recorder | K1-K5 |
| **S11 AI/RAG Completion** | 2 нед | Multimodal RAG full, Adaptive RAG strategy, Model Registry UI, AI feedback→DSPy, distributed RL Redis Cluster, DB read replica | K1-K5 |
| **S12 Workflow Enhancement** | 2 нед | Visual diff, Cron builder UI, cost estimation, reactive workflows, template library, saga compensation viewer, cancel-workflow DSL | K1-K5 |
| **S13 Infra & Perf** | 2 нед | RSGI streaming 1GB, CH columnar builder, parallelism analyzer, graceful degradation, retry profile store, WebDAV source, batch primitive | K1-K5 |
| **S14 Plugin Ecosystem** | 2 нед | Compatibility matrix, migration guide gen, marketplace versioning, dependency graph UI, plugin dev-server, sandbox isolation, publish workflow | K1-K5 |
| **S15 DX Tooling + Innovation** | 2 нед | VSCode extension+LSP, ADR scaffolding, CLI completions, changelog autogen, AI PR review, Interactive Arch Map | K1-K5 |

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

### Sprint 8 — BLOCKER closure + Carryover + RPA stage 1 + HTTP/3 + Rule Engine (active 2026-05-15)

**Текущий прогресс**: 6/49 wave closed (12.2%). Цель — закрыть до 2026-05-22 (2 недели). 8A/8B разбивка по `SPRINT_8_PLAN.md`.

#### Sprint 8A (1 неделя): BLOCKER + Carryover closure (~28 wave)

| Команда | Closed | In-Progress | Pending |
|---|---|---|---|
| **K1** (7) | W8 `bfa33c63` pre-receive-docstring | W5 cosign-all (stash-loss recovery) | W0 quotas-fix (AUDIT-1), W1 WAF-phase2 (BLOCKER #3, 38 callsites), W2 DLQ-replay RBAC, W3 Inbox-audit-PII, W4 PII-DSL-step, W6 OpenFeature-Flagsmith |
| **K2** (7) | W1 `f36edd5e` TaskIQ-removal (BLOCKER #1) | W8 httpx-unify (worktree ECONNRESET) | W2 outbox-dispatcher, W3 DLQ-unified, W4 Inbox-fail-closed, W5 alerts+fallback-chains, W6 Bulkhead-defaults, W7 tenant-RL-namespace |
| **K3** (5) | W1 `aa987472` windows-worker-rename (AUDIT-3), W5 `87b96eaa` rule-engine-protocol | W8 dsl/blueprints/ subdir | W9 workflow-versioning, W10 workflow-TaskGroup, W11 invoke_workflow-reply, W13 plugin-hotswap-impl |
| **K4** (7) | W11 `c89e9d12` llm-structured-scaffold | — | W1 multimodal-RAG, W2 RLM-hierarchical, W3 RAG-cache-invalidate, W4 BGE-M3-reranker, W6 mem0+`.rag_*/.memory_*` DSL, W7 saga-blueprint, W8 LiteLLM-final |
| **K5** (3) | merged `30d24195` doc-generation-DSL | — | W2 70_Tenants finalize, W3 71_Capabilities finalize, W4 30_Files_S3 |

**DoD 8A** (8 критериев): ✅ BLOCKER #1 TaskIQ closed; ⏳ BLOCKER #3 WAF Phase-2 closed; ⏳ 5 quotas-tests green; ⏳ plugin hot-swap enhanced; ⏳ cosign все artifacts; ⏳ Multimodal RAG ingest PDF/image; ⏳ DLQ unified для 4 transport-types; ⏳ RBAC+audit для DLQ-replay.

#### Sprint 8B (1 неделя): Native scope (~21 wave)

| Команда | Pending |
|---|---|
| **K1** | W7 prompt-injection-guardrails (Lakera+Rebuff) |
| **K2** | W8 httpx-unify finale, W9 Grafana+SLO alerts, W10 mypy≤50, W11 deptry/vulture-clean, W12 layer-violations-zero |
| **K3** | W2 patchright-pool RPA, W3 RPA-OCR (PaddleOCR/EasyOCR), W4 RPA-Windows-desktop (pywinauto), W6 HTTP/3+WebTransport (aioquic), W7 legacy-DSL-Python→YAML, W12 MCP-via-FastMCP |
| **K4** | W5 7 RAG-Streamlit-pages, W9 AI-model-registry (MLflow+HF), W10 batch-inference (vLLM/TGI), W11.5 code-interpreter (e2b/pyodide) |
| **K5** | W1 5 credit-clients (DaData/БКИ/СМЭВ/ЦБ/1С) migration, W5 @st.fragment-live, W6 Wiki-Whoosh-Diátaxis-Vale, W7 Sphinx-multiversion |
| **backbone/finale** | `pyproject.toml` + 54 feature-flag default-OFF; flip critical default-ON post-smoke |

**DoD 8B** (7 критериев): ⏳ 5 credit clients live; ⏳ RPA stage 1 (patchright + pywinauto + OCR); ⏳ `.evaluate_rules()` + `.llm_structured()`; ⏳ HTTP/3 opt-in smoke; ⏳ mypy ≤ 50; ⏳ layer violations = 0; ⏳ Streamlit Wiki Whoosh; ⏳ Multi-version Sphinx published.

**Branch isolation**: 5 team-веток (`team/s8-k1-security`, etc.). Coordinator cherry-pick в master после intermediate commits каждой wave. Worktree cleanup перед стартом 8A через `vault/triage-worktrees-2026-05-15.md`.

**Audit findings 2026-05-15**:
- AUDIT-1: 5 quotas tests fail → S8 K1 W0 (LOW severity, regress fix).
- AUDIT-2: Plugin hot-swap path docs-drift only (real impl `core/plugin_runtime/hot_swap.py`).
- AUDIT-3: windows-sidecar→windows_worker rename ✅ CLOSED (`aa987472`).

---

### Sprint 9 — GAP Closure + Documentation + Pre-prod Gate (2 нед)

Sprint 9 закрывает **критические GAP-проблемы из аудита 2026-05-15** (`gap-analysis/GAP-анализ актуальный.md`) + готовит pre-production gate. Все P0+P1 пробелы (RouteLoader, Streamlit page dedup, messaging completion, HITL panel, token budget, plugin compatibility) — закрываются здесь.

#### K1 Security (GAP P0-P1)
- ⏳ **GAP-1.5 SAML/mTLS backend полный** — `infrastructure/security/saml_backend.py` (pysaml2): SP-initiated SSO, атрибуты → TenantContext, assertion cache, metadata auto-refresh. ADR-0054 → Implementation.
- ⏳ **GAP-3.2 Token budget per tenant** — `services/ai/gateway/token_budget.py`: daily_limit, hourly_burst, Redis counter с TTL 24h, при превышении `raise TenantQuotaExceeded` → 429.
- ⏳ Disaster recovery runbook + backup verification.
- ⏳ Feature flags Flagsmith default-ON в staging compose (carryover S8 K1 W6).
- ⏳ Pre-production gate checklist (`make pre-prod-check` → 20 критериев: coverage ≥75%, chaos green, mypy ≤30, no layer violations, SBOM актуален, ZAP gate, всё на Temporal, все endpoints авторизованы, docstring gate, codeclone clean, и др.).

#### K2 Resilience+Perf (GAP P0-P1)
- ⏳ **GAP-INF-1/2/3 Messaging carryover finale** — `outbox_dispatcher.py` + `inbox_dedup.py` + `dlq.py` финальная реализация (если осталось из S8 K2 W2-W4).
- ⏳ **GAP-PERF-6.3 Lazy processor loading** — `LazyProcessorRegistry` через importlib + lru_cache → startup time < 3s; CI-gate на startup time.
- ⏳ **GAP-INF-2.4 Connection Pool Warm-up** — `PoolWarmup` в lifespan: 3 conn min (PG+Redis+CH) → p95 < 50ms на холодном старте.
- ⏳ **GAP-INF-2.3 ClickHouse Async Bulk Writer** — `infrastructure/clients/clickhouse_bulk_writer.py`: buffer_size=1000, flush_interval=1s, audit events ≥10x throughput.
- ⏳ Snapshot/restore профили (БД/cache в SQLite) для dev_light.
- ⏳ Free-threading PEP 703 benchmark.

#### K3 DSL+Workflow (GAP P0-P1)
- ⏳ **GAP-DSL-1 RouteLoader full-cycle** — `dsl/route/loader.py`: load_directory + tomllib + watchfiles hot-reload < 3s + feature_flag `hot_reload_routes`. Закрытие S2 carryover.
- ⏳ **GAP-WF-4.5 HITL Streamlit panel** — `pages/72_HITL_Panel.py`: список приостановленных workflow (Temporal signal-wait), форма approve/reject, real-time через `st.fragment`.
- ⏳ **GAP-WF-4.4 Workflow SLA Alerting** — `.sla` в workflow.yaml: max_duration + escalation_email/slack + business_hours_only.
- ⏳ **GAP-DSL-1.5 DSL Dry-run UI** — `30_DSL_Playground.py` вкладка "Dry-run": YAML → sample JSON → execute → waterfall.
- ⏳ **GAP-WF-4.1 Temporal Client Factory** — `infrastructure/workflow/temporal_client.py`: TemporalClientFactory + WorkerPool + ActivityHeartbeatMonitor.
- ⏳ Tutorials ≥9 по Diátaxis (getting-started, build-first-action, build-rest-connector, build-grpc-service, write-dsl-route, plugin-development, RAG-setup, RPA-script, multi-tenant-setup).
- ⏳ ≥10 runbooks (deploy/rollback/scale-out/incident/db-migration/cache-flush/audit-export/key-rotation/plugin-install/cdc-restart).
- ⏳ Legacy workflow Python → YAML миграция финал.

#### K4 AI+RAG (GAP P1)
- ⏳ **GAP-AI-3.3 RAG Freshness Indicator** — Qdrant payload (ingested_at + ttl_hours), DSL `.rag_query(max_staleness_hours=72)`, UI freshness badge.
- ⏳ **GAP-AI-3.2 Prompt Version Control UI** — `48_Prompt_Lab.py`: LangFuse 3.x prompts, A/B versions, metrics (cost/latency/quality), rollback.
- ⏳ **GAP-AI-3.8 Guardrails Dashboard per-tenant** — `47_AI_Safety.py`: блокированные запросы, false-positive rate, sensitivity tuning per tenant.
- ⏳ mem0/Zep persistent personalisation для credit_pipeline (opt-in).
- ⏳ `60_AI_Agent_Monitor.py` (multi-agent trace viewer, OTel GenAI semantics).

#### K5 Frontend+Ext+Mig (GAP P0)
- ⏳ **GAP-DSL-2 Streamlit page renumbering** — устранить 9 коллизий (`00_/14_/15_/30_/50_/55_/60_/65_/67_`); схема DSL 30-39 / AI 40-49 / Ops 50-59 / Admin 60-69. Удалить 2 дубликата (`55_s3_files.py`, `67_Plugin_Marketplace.py`).
- ⏳ **GAP-15.1 Execution middleware dedup** — консолидация `entrypoints/middlewares/` vs `services/execution/middlewares/` (Single Entry §1.1).
- ⏳ **GAP-15.2 DLQ Replay admin REST endpoint** — `entrypoints/api/v1/endpoints/admin_dlq.py` для функционирования `14_DLQ_Replay.py` UI.
- ⏳ **GAP-15.4 Business logic migration** — `src/backend/workflows/orders_dsl.py/orders_saga.py/payments_saga.py` → `extensions/core_entities/orders/workflows/` + `extensions/credit_pipeline/workflows/`.
- ⏳ DSL Visual Editor расширение (drag-drop) на стороне Streamlit.

**DoD Sprint 9** (12 критериев): ⏳ RouteLoader hot-reload < 3 сек; ⏳ Streamlit pages renumbered без коллизий; ⏳ messaging Outbox/Inbox/DLQ полная реализация; ⏳ HITL panel functional; ⏳ Token budget per tenant работает; ⏳ SAML SP-initiated SSO; ⏳ Lazy processor loading + startup < 3s; ⏳ Pool warm-up; ⏳ ClickHouse bulk writer ≥10x throughput; ⏳ `make pre-prod-check` → 20/20; ⏳ ≥9 tutorials + ≥10 runbooks; ⏳ coverage ≥75%; ⏳ mypy ≤30.

---

### Sprint 10 — DSL Blueprint Expansion + DX Wizards (2 нед)

Расширение DSL: blueprint library 5 → 20+, dry-run UI, complexity budget, scaffold wizards, plugin dev-server, testkit cassette recorder. Все фичи K3 + K5 по `FEATRE-ROADMAP.md` §1 (DSL) и §8 (DX).

| Команда | Wave | Wave-tag | Scope |
|---|---|---|---|
| **K1** | W1 | `[wave:s10/k1-w1-cassette-secrets-mask]` | Маскирование secret-полей в testkit cassettes (recorder hook: redact `*token*`/`*secret*`/`*key*`). |
| **K1** | W2 | `[wave:s10/k1-w2-extension-testkit-template]` | EXT-5.7: шаблонный `conftest.py` для extensions (pre-wired plugin loader + DB snapshot + S3 mock). |
| **K2** | W1 | `[wave:s10/k2-w1-msgspec-hotpath-expand]` | PERF-6.5: msgspec hotpath на Exchange + Audit + Cache key + WebSocket serialization. Benchmark до/после. |
| **K2** | W2 | `[wave:s10/k2-w2-brotli-compression]` | PERF-6.6: `BrotliCompressionMiddleware` (-60% JSON traffic). Feature-flag `compression_brotli`. |
| **K2** | W3 | `[wave:s10/k2-w3-startup-time-gate]` | CI-gate на startup time dev_light (< 3 сек) — fail-on-regression. |
| **K3** | W1 | `[wave:s10/k3-w1-blueprint-library-15]` | DSL-1.2: 15 новых blueprints (fan_out_fan_in, request_reply_async, file_to_db_pipeline, cdc_to_search_index, rpa_web_scrape, hitl_approval, credit_scoring, multimodal_ingest, scheduled_report, webhook_to_kafka, saml_user_sync, api_to_api_bridge, dlq_replay, rate_limit_burst, hybrid_rag). |
| **K3** | W2 | `[wave:s10/k3-w2-dsl-complexity-budget]` | DSL-1.3: `tools/dsl_lint.py check-complexity` (cyclomatic ≤50 / nesting ≤5 / steps ≤50). CI-шаг `make dsl-complexity-check`. Streamlit visualization. |
| **K3** | W3 | `[wave:s10/k3-w3-ab-test-processor]` | DSL-1.4: `.ab_test(experiment_id, variant_a, variant_b, split=0.7/0.3, track_metric)` step + Streamlit A/B dashboard. |
| **K3** | W4 | `[wave:s10/k3-w4-dsl-dryrun-ui]` | DSL-1.5: `30_DSL_Playground.py` вкладка "Dry-run" — YAML → sample JSON → execute → waterfall с latency. |
| **K3** | W5 | `[wave:s10/k3-w5-semantic-processor-search]` | DSL-1.6: vector-поиск по `ProcessorRegistry.describe()` в DSL Builder. embeddings BGE-M3. |
| **K3** | W6 | `[wave:s10/k3-w6-dsl-diff-streamlit]` | DSL-1.7: `tools/dsl_diff.py` → `31_DSL_Visual_Editor.py` вкладка History (diff между версиями route). |
| **K3** | W7 | `[wave:s10/k3-w7-dsl-jinja-macros]` | DSL-1.8: Jinja2-over-YAML макросы с параметрами `{% macro %}`/`{% include %}`. |
| **K3** | W8 | `[wave:s10/k3-w8-dsl-step-tracing]` | DSL-1.9: `StepTrace` в `Exchange` (input_snapshot + duration_ms + error_context). OTel span attributes. |
| **K3** | W9 | `[wave:s10/k3-w9-route-flow-render]` | DOC-7.3: `manage.py dsl render ROUTE=name --format mermaid|bpmn|svg` → `docs/generated/`. |
| **K4** | W1 | `[wave:s10/k4-w1-mock-llm-provider]` | Mock-LLM provider для dry-run AI workflow тестов (deterministic responses + cost=0). |
| **K4** | W2 | `[wave:s10/k4-w2-feedback-step-dsl]` | DSL `.record_feedback(rating, comment, route_run_id)` step (вход в `feedback_service`). |
| **K5** | W1 | `[wave:s10/k5-w1-make-doctor]` | DX-8.1: `tools/checks/doctor.py` — Python version, services healthcheck (PG/Redis/CH/Temporal/Vault/Kafka ping), env-validation, TaskIQ imports=0, WAF=0, layer-violations=0, mypy ≤ 50. |
| **K5** | W2 | `[wave:s10/k5-w2-make-scaffold-route]` | DX-8.2: interactive wizard (Typer prompt): source → sink → AI? → retry? → codegen `routes/<name>/route.toml + *.dsl.yaml`. |
| **K5** | W3 | `[wave:s10/k5-w3-make-simulate]` | DX-8.3: `make simulate ROUTE=name` — CLI dry-run с output waterfall (повтор Streamlit UI в CLI). |
| **K5** | W4 | `[wave:s10/k5-w4-plugin-dev-mode]` | DX-8.6: `make plugin-dev NAME=x` — infra-only docker-compose subset + hot-reload + mocks + livereload + `pytest --watch`. |
| **K5** | W5 | `[wave:s10/k5-w5-onboarding-checklist]` | DX-8.5: developer onboarding (7 шагов: clone → doctor → dev → Streamlit → first route → test → first plugin → ~1 час). Streamlit page. |
| **K5** | W6 | `[wave:s10/k5-w6-cassette-recorder]` | EXT-5.5: VCR.py-style cassette recorder для testkit. `@cassette("tests/cassettes/bki_query.yaml")` decorator. Запись/replay HTTP/SOAP/gRPC. |

**DoD Sprint 10** (10 критериев):
1. ✅ 20+ blueprints в `dsl/blueprints/` с тестами.
2. ✅ `make dsl-complexity-check` blocking в CI.
3. ✅ `.ab_test()` step + Streamlit dashboard.
4. ✅ Dry-run UI с waterfall.
5. ✅ Semantic search в DSL Builder (latency < 200ms).
6. ✅ `manage.py dsl render` для всех routes.
7. ✅ `make doctor` + `make scaffold-route` + `make simulate` + `make plugin-dev` работают.
8. ✅ Cassette recorder в testkit с docs.
9. ✅ Onboarding ≤ 1 час (измерено).
10. ✅ coverage ≥77%; startup time CI-gate активен.

---

### Sprint 11 — AI/RAG Completion (2 нед)

Завершение AI/RAG стека: Multimodal полный, Adaptive RAG, AI Model Registry UI, feedback loop с DSPy fine-tuning, batch inference production, distributed rate limiter Redis Cluster.

| Команда | Wave | Wave-tag | Scope |
|---|---|---|---|
| **K1** | W1 | `[wave:s11/k1-w1-rag-pii-redaction]` | PII redaction в RAG retrieval (mask чувствительных полей в chunks перед LLM context). |
| **K1** | W2 | `[wave:s11/k1-w2-guardrails-per-tenant]` | Lakera/Rebuff config per-tenant (банк vs SaaS разные thresholds). Config в `core/auth/tenant_settings`. |
| **K2** | W1 | `[wave:s11/k2-w1-distributed-rl-redis-cluster]` | INF-2.9: `redis-cell` CL.THROTTLE или Lua-скрипт для Redis Cluster, token-bucket per-tenant. |
| **K2** | W2 | `[wave:s11/k2-w2-db-read-replica-routing]` | PERF-6.7: `SmartSessionManager` — SELECT → replica, INSERT/UPDATE → primary. SQLAlchemy + asyncpg. |
| **K3** | W1 | `[wave:s11/k3-w1-adaptive-timeout-policy]` | INF-2.10: `.policy.adaptive_timeout(percentile=99, safety_factor=1.5)` — p99 за N запросов × safety_factor. |
| **K3** | W2 | `[wave:s11/k3-w2-rag-ingest-step]` | DSL `.rag_ingest(source, modal="text"|"image"|"audio"|"video", collection)` step. |
| **K3** | W3 | `[wave:s11/k3-w3-rag-multi-query]` | DSL `.rag_query(strategy="dense"|"hybrid"|"hyde"|"multi_query", max_staleness_hours)` step. |
| **K4** | W1 | `[wave:s11/k4-w1-multimodal-rag-full]` | AI-3.1: markitdown (PDF/DOCX/HTML) + CLIP (images) + BLIP2 (image captions) + Whisper (audio). Cross-modal retrieval (text query → image+audio chunks). |
| **K4** | W2 | `[wave:s11/k4-w2-multimodal-rag-pipeline]` | Pipeline: ingest → chunking → embedding → Qdrant (с modal payload) → retrieval → rerank → LLM context. |
| **K4** | W3 | `[wave:s11/k4-w3-adaptive-rag-strategy]` | AI-3.9: query classifier (LLM-based) → select strategy (dense/hybrid/hyde/multi_query). Bench accuracy +15%. |
| **K4** | W4 | `[wave:s11/k4-w4-langgraph-checkpoint-ui]` | AI-3.5: `60_AI_Agent_Monitor.py` вкладка Checkpoints: active sessions → inspect state → time-travel restore. |
| **K4** | W5 | `[wave:s11/k4-w5-ai-feedback-dspy]` | AI-3.6: user feedback → dataset → DSPy BootstrapFewShot → optimized prompt → re-deploy. CRON nightly. |
| **K4** | W6 | `[wave:s11/k4-w6-ai-model-registry-ui]` | AI-3.7: `49_Model_Registry.py` — статус, бенчмарки (latency/cost/quality), "Use in route" CTA. MLflow + HF Hub adapter. |
| **K4** | W7 | `[wave:s11/k4-w7-ai-route-optimization]` | AI-3.10: анализ логов outbound→inbound→processing → рекомендации (parallelization, caching, retry tuning). Generated PR с предложениями. |
| **K4** | W8 | `[wave:s11/k4-w8-embedding-ab-migration]` | A/B migration между embedding моделями (BGE-M3 → BGE-M3-v2): индексация двух коллекций → A/B retrieval → switch без переиндексации. |
| **K5** | W1 | `[wave:s11/k5-w1-adaptive-rag-dashboard]` | Streamlit dashboard для Adaptive RAG: strategy selection rate, accuracy per strategy. |
| **K5** | W2 | `[wave:s11/k5-w2-ai-feedback-page]` | Streamlit `48_AI_Feedback.py` — collect feedback, view DSPy training runs. |
| **K5** | W3 | `[wave:s11/k5-w3-replica-dashboard]` | Grafana dashboard для read replica routing (SELECT replica vs primary ratio, lag). |

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

### Sprint 12 — Workflow Enhancement (2 нед)

Visual diff, Cron UI, Cost estimation, Reactive workflows, Workflow template library, Saga compensation viewer, AI workflow examples library.

| Команда | Wave | Wave-tag | Scope |
|---|---|---|---|
| **K1** | W1 | `[wave:s12/k1-w1-workflow-audit-log]` | Workflow execution audit log в ClickHouse (start/finish/cancel/signal events) с tenant-id + actor + duration. |
| **K1** | W2 | `[wave:s12/k1-w2-temporal-mtls-finale]` | mTLS для Temporal worker → server cluster (production-ready security). |
| **K2** | W1 | `[wave:s12/k2-w1-workflow-sla-grafana]` | Grafana dashboard «Workflow SLA compliance rate» (% workflow завершены в срок). |
| **K2** | W2 | `[wave:s12/k2-w2-temporal-worker-autoscale]` | Auto-scale Temporal workers по queue depth (K8s HPA через PrometheusAdapter). |
| **K3** | W1 | `[wave:s12/k3-w1-visual-workflow-diff]` | WF-4.2: `31_DSL_Visual_Editor.py` вкладка Workflow Diff — side-by-side Graphviz, color-coded (added=green/removed=red/modified=yellow). |
| **K3** | W2 | `[wave:s12/k3-w2-cron-builder-ui]` | WF-4.6: visual cron builder + preview Next 5 executions + timezone-aware (Москва) + dry-run simulation. Croniter library. |
| **K3** | W3 | `[wave:s12/k3-w3-workflow-cost-estimation]` | WF-4.7: до запуска оценивает estimate (llm_tokens, cost_usd, compute_seconds, storage_bytes) на основе historical p50/p95. |
| **K3** | W4 | `[wave:s12/k3-w4-reactive-workflows]` | WF-4.8: event-driven triggers (EventBus → workflow start) без polling. Debounce (5sec), deduplication (idempotency key). |
| **K3** | W5 | `[wave:s12/k3-w5-workflow-template-library]` | WF-4.3: `33_DSL_Templates.py` с живыми шаблонами (10 templates), semantic search (BGE-M3), one-click deploy. |
| **K3** | W6 | `[wave:s12/k3-w6-saga-compensation-viewer]` | UI просмотра статуса compensation steps при rollback (Streamlit page `17_Workflow_Replay.py` вкладка Saga). |
| **K3** | W7 | `[wave:s12/k3-w7-cancel-workflow-dsl]` | DSL `.cancel_workflow(workflow_id, reason)` explicit cancel step + Temporal API integration. |
| **K3** | W8 | `[wave:s12/k3-w8-workflow-versioning-ui]` | UI для VersionRegistry (`workflow.versioning_strategy = "patched"`) — pin version per route, rollback. |
| **K4** | W1 | `[wave:s12/k4-w1-ai-workflow-examples-lib]` | 3 production-ready examples: RAG-augmented saga (credit risk), multi-agent supervisor (loan approval), Code-Interpreter loop (data analysis). |
| **K4** | W2 | `[wave:s12/k4-w2-llm-workflow-cost-est]` | Cost estimation для AI workflow (LLM tokens × model price + embedding cost + storage). |
| **K5** | W1 | `[wave:s12/k5-w1-workflow-template-streamlit]` | `33_DSL_Templates.py` Streamlit page (живые preview YAML + Mermaid рендер). |
| **K5** | W2 | `[wave:s12/k5-w2-hitl-history-viewer]` | UI history view для HITL approvals (кто/когда/решение/время) — продолжение S9 K3 HITL panel. |
| **K5** | W3 | `[wave:s12/k5-w3-cron-dashboard]` | Streamlit cron schedule dashboard — все scheduled workflows, last run, next run, success rate. |

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

### Sprint 13 — Infrastructure & Performance (2 нед)

RSGI streaming, ClickHouse columnar builder, parallelism analyzer, graceful degradation, WebDAV source, DSL batch primitive, EventBus schema validation.

| Команда | Wave | Wave-tag | Scope |
|---|---|---|---|
| **K1** | W1 | `[wave:s13/k1-w1-pii-streaming]` | PII redaction в streaming endpoints (chunk-level redaction для больших payloads). |
| **K1** | W2 | `[wave:s13/k1-w2-degradation-rbac]` | RBAC для graceful degradation switches (только admin может переключить FULL → READ_ONLY). |
| **K2** | W1 | `[wave:s13/k2-w1-rsgi-streaming-large-files]` | PERF-6.2: `entrypoints/api/v1/endpoints/files.py` — async stream chunks → S3 multipart, RAM < 50MB для 1GB файлов. Granian RSGI. |
| **K2** | W2 | `[wave:s13/k2-w2-clickhouse-columnar-builder]` | PERF-6.4: типизированный `ClickHouseQueryBuilder` (где raw SQL запрещён). Columnar query optimization. |
| **K2** | W3 | `[wave:s13/k2-w3-parallelism-analyzer]` | PERF-6.8: статический анализ DSL DAG → параллелизуемые шаги. Streamlit visualization (последовательные vs параллельные шаги). |
| **K2** | W4 | `[wave:s13/k2-w4-graceful-degradation]` | INF-2.7: `GracefulDegradationRegistry` — уровни FULL/READ_ONLY/CACHE_ONLY/ESSENTIAL_ONLY/MAINTENANCE. API + Streamlit panel. |
| **K2** | W5 | `[wave:s13/k2-w5-unified-retry-store]` | `ResilienceProfile` store с per-tenant override + UI editor. SQLAlchemy persistence. |
| **K2** | W6 | `[wave:s13/k2-w6-redis-cluster-pipelining]` | S0 carryover: `redis.asyncio.cluster.RedisCluster` + batch ops + pipelining (+30..50% throughput). |
| **K2** | W7 | `[wave:s13/k2-w7-pool-warmup-finale]` | Pool warmup для всех клиентов (S9 K4 follow-up): warm-up на startup + reconnect detection. |
| **K3** | W1 | `[wave:s13/k3-w1-batch-processor]` | DSL `.batch(size=100, timeout_ms=500)` aggregator — flush by N OR timeout (whichever first). |
| **K3** | W2 | `[wave:s13/k3-w2-webdav-source]` | INF-2.8: `infrastructure/sources/webdav.py` + `.from_webdav(url, poll_interval)` step. |
| **K3** | W3 | `[wave:s13/k3-w3-eventbus-schema-validation]` | EventBus schema-registry hook на `bus.publish()` — validate payload против registered schema. |
| **K3** | W4 | `[wave:s13/k3-w4-dlq-ttl-policies]` | DLQ TTL policies per message-type (analytics short / financial long). Retention в `DLQPolicy`. |
| **K3** | W5 | `[wave:s13/k3-w5-nats-consumer-lag-ui]` | NATS JetStream consumer lag UI (Streamlit panel + Grafana). |
| **K4** | W1 | `[wave:s13/k4-w1-rag-cache-prewarm]` | RAG cache pre-warm для популярных запросов (top-100 queries в L2 semantic). |
| **K4** | W2 | `[wave:s13/k4-w2-ai-batch-inference-prod]` | Batch inference production-ready (vLLM или TGI client) — для NN embeddings + classification jobs. |
| **K5** | W1 | `[wave:s13/k5-w1-degradation-panel]` | Streamlit page «Graceful Degradation» — текущий уровень, switch, history. |
| **K5** | W2 | `[wave:s13/k5-w2-resilience-profile-editor]` | Streamlit page «Resilience Profile Editor» — per-tenant tune CB/RL/retry/cache parameters. |
| **K5** | W3 | `[wave:s13/k5-w3-pipeline-parallelism-viewer]` | Streamlit page «Pipeline Parallelism Analysis» — визуализация DAG с подсветкой параллелизуемых шагов. |

**DoD Sprint 13** (10 критериев):
1. ✅ RSGI streaming для файлов 1GB (RAM ≤ 50MB).
2. ✅ ClickHouse columnar builder используется для всех new DSL audit-шагов.
3. ✅ Parallelism analyzer обнаруживает ≥3 паттерна параллелизма.
4. ✅ Graceful degradation switch работает (5 уровней).
5. ✅ Unified retry policy store + per-tenant override UI.
6. ✅ DSL `.batch(size, timeout)` с production тестом.
7. ✅ WebDAV source + integration test (Nextcloud testcontainer).
8. ✅ EventBus schema validation rejects invalid payload.
9. ✅ Redis cluster pipelining (+30% throughput на bench).
10. ✅ p95 latency ≤ 100ms (от 200ms baseline S6); coverage ≥80%.

---

### Sprint 14 — Plugin Ecosystem (2 нед)

Compatibility matrix, migration guide generator, marketplace versioning, dependency graph UI, plugin local dev server, sandbox isolation, plugin publish workflow.

| Команда | Wave | Wave-tag | Scope |
|---|---|---|---|
| **K1** | W1 | `[wave:s14/k1-w1-plugin-compatibility-matrix]` | EXT-5.1: `plugin.toml::[plugin.compatibility]` — `incompatible_with`, `requires_plugins`, `incompatible_core_versions`. Validate при загрузке: `raise PluginConflictError`. `make check-compat`. |
| **K1** | W2 | `[wave:s14/k1-w2-plugin-sandbox-isolation]` | EXT-5.8: RestrictedPython + resource limits (`max_memory_mb`, `max_cpu_seconds`, whitelist imports). Plugin sandbox profile в `plugin.toml`. |
| **K1** | W3 | `[wave:s14/k1-w3-plugin-publish-cosign]` | `make publish-plugin PLUGIN=x VERSION=1.0.0` + cosign signing + SBOM-attestation. Marketplace upload via REST. |
| **K1** | W4 | `[wave:s14/k1-w4-plugin-permission-audit]` | Plugin capability audit log в ClickHouse (granted/denied with reason). Dashboard. |
| **K2** | W1 | `[wave:s14/k2-w1-plugin-resource-monitor]` | Plugin resource monitor (per-plugin CPU/RAM/RPS) → Prometheus metrics. |
| **K2** | W2 | `[wave:s14/k2-w2-plugin-isolation-bench]` | Benchmark sandbox isolation overhead (target < 5% throughput penalty). |
| **K3** | W1 | `[wave:s14/k3-w1-processor-catalog-search]` | Семантический поиск по ProcessorRegistry в Streamlit (BGE-M3 embeddings + Qdrant). |
| **K3** | W2 | `[wave:s14/k3-w2-routebuilder-stubs-pyi]` | IDE-friendly `.pyi` stub-generation для RouteBuilder + WorkflowBuilder методов → autocomplete в PyCharm/VSCode. |
| **K4** | W1 | `[wave:s14/k4-w1-plugin-ai-services]` | AI-plugins API (extension'ы могут регистрировать AI services через `@ai_service` decorator). |
| **K5** | W1 | `[wave:s14/k5-w1-plugin-migration-generator]` | EXT-5.2: `make plugin-migrate-guide FROM:1.0.0 TO:2.0.0` → markdown migration guide (breaking changes, auto/manual steps, rollback). API diff. |
| **K5** | W2 | `[wave:s14/k5-w2-marketplace-versioning]` | EXT-5.3: semver changelog в plugin.toml + diff plugin.toml versions + rollback + health-check post-install. |
| **K5** | W3 | `[wave:s14/k5-w3-dependency-graph-ui]` | EXT-5.4: D3.js graph в `60_Plugin_Marketplace.py` — plugin dependencies, фильтры по слоям. |
| **K5** | W4 | `[wave:s14/k5-w4-plugin-local-dev-server]` | EXT-5.6: `manage.py plugin serve --name=x` — mock инфраструктуры, Swagger only для плагина, livereload. |
| **K5** | W5 | `[wave:s14/k5-w5-capability-graph-ui]` | Capability dependency graph UI в `71_Capabilities.py` (D3.js, requires/provides). |
| **K5** | W6 | `[wave:s14/k5-w6-plugin-onboarding-pages]` | Streamlit pages для plugin onboarding (create plugin → publish → marketplace). |

**DoD Sprint 14** (10 критериев):
1. ✅ Compatibility matrix blocks incompatible plugins at install time.
2. ✅ Migration guide auto-gen для major-bump (sample BKI 1.0 → 2.0).
3. ✅ Marketplace versioning + rollback работает.
4. ✅ Dependency graph rendered в Marketplace UI.
5. ✅ Plugin sandbox isolation overhead < 5%.
6. ✅ `make publish-plugin` с cosign signing + SBOM.
7. ✅ Plugin local dev server с mocks.
8. ✅ Processor catalog semantic search latency < 200ms.
9. ✅ RouteBuilder `.pyi` stubs покрывают 100% public methods.
10. ✅ coverage ≥82%.

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

**DoD Sprint 15** (10 критериев):
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

**Итого**: 15 спринтов (закрыты S0-S7, active S8, planned S9-S15). Из них первые 8 — за 2 недели, последние 7 — 2 недели каждый. Срок ~7-8 месяцев от 2026-05-15 до production-ready.

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

---

**Конец PLAN.md V19 FINAL**. Полный GAP-анализ актуальный (55 P0-P3 + 13 docs-drift) — `gap-analysis/GAP-анализ gd_integration_tools актуальный.md`. Feature Roadmap (85 фич × S9-S16) — `gap-analysis/FEATRE-ROADMAP.md`. Live wave-by-wave детализация Sprint 8 — `SPRINT_8_PLAN.md`. История контракта V11→V15 (3382 строки) — `~/.claude/projects/-home-user-dev-gd-integration-tools/memory/project_gap_analysis_v15.md`.
