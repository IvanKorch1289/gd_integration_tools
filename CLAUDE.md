# CLAUDE.md — gd_integration_tools

> **Версия документа**: V15 (синхронизирована с PLAN.md V15 от 2026-05-05).
> Любая работа выполняется в соответствии с этим документом и `PLAN.md`.

---

## Проект

`gd_integration_tools` — **универсальное domain-agnostic ядро** интеграционной шины на Python 3.14+ (Apache-Camel- и Airflow-style). Внутренний продукт банка для:
- декларативного построения интеграционных маршрутов (DSL: YAML + Python builder, Camel-style fluent);
- workflow / orchestration (Temporal как default backend через protocol; LiteTemporalBackend для dev_light);
- multi-protocol auto-registration (один handler → REST + SOAP + XML + gRPC + GraphQL + MQ + WS + SSE + MCP + MQTT);
- multi-backend gateways (PG↔Oracle↔MSSQL↔MySQL↔DB2; Redis↔KeyDB; S3↔MinIO↔LocalFS; Kafka↔RabbitMQ↔Redis Streams↔NATS);
- RPA, CDC, file-watcher, webhook source/sink;
- AI/RAG/agents с MCP-сервером (FastMCP) и AI Safety (workspace isolation);
- multi-tenancy (TenantContext + per-tenant SLO/quotas);
- developer portal на Streamlit (36+ страниц).

**Бизнес-логика — только в `extensions/<name>/`**, ядро domain-agnostic. Кредитный конвейер — внешний потребитель; его текущая логика мигрирует в первый плагин (Sprint 7-9).

**80% декларативно (YAML/TOML) / 20% Python** — через `call_function('module:fn')` без обёрток в Action.

---

## Текущий план

**Главный документ**: `PLAN.md` (V15 FINAL) и `/root/.claude/plans/foamy-puzzling-dragonfly.md` (полный аналитический GAP-анализ).

**Срок**: 14-15 недель ≈ 3.5 месяца при параллельной работе **4 разработчиков**:
- **Dev1 — Plugin/Platform** (capability-gate, ASGI middleware, Auth, WAF, supply-chain, leak prevention)
- **Dev2 — DSL/Workflow** (RouteBuilder split Wave G, Sinks, Workflow DSL, Temporal, конвертеры, perf)
- **Dev3 — Frontend/Ops** (Frontend split, tools/Makefile/manage.py, docs Sphinx + Diátaxis, dashboards, chaos, auto-scaler)
- **Dev4 — AI/Data** (PydanticAI, LiteLLM, RAG cache 3 уровня, LangMem + RLM-toolkit, FastMCP, Multimodal RAG, AI Safety, AI cost dashboard)

**21 базовое + 12 V15 GAP архитектурных решения** — обязательны.

---

## Что читать сначала

1. `PLAN.md` (V15 FINAL) — текущий roadmap и решения;
2. `graphify-out/GRAPH_REPORT.md` (если есть);
3. `graphify-out/wiki/index.md` (основной индекс при наличии);
4. `ARCHITECTURE.md`;
5. `.claude/CONTEXT.md` — краткая оперативная сводка;
6. Точечные документы и исходники по задаче.

Связи через `graphify query/path/explain`. **Не читать весь репозиторий целиком без необходимости.**

---

## Приоритет источников

1. **`PLAN.md` V15** (фиксирует курс развития);
2. исходный код;
3. Graphify (`graphify-out/...`);
4. `ARCHITECTURE.md`;
5. `.claude/rules/...`;
6. `.claude/DECISIONS.md`;
7. `.claude/KNOWN_ISSUES.md`;
8. `.claude/CONTEXT.md`.

---

## Архитектура (V15 FINAL)

```text
┌─────────────────────────────────────────────────────────────────────┐
│  frontend/streamlit_app/  (36+ pages)                               │
│                          │                                          │
│                          ▼  REST/gRPC/WS                            │
├─────────────────────────────────────────────────────────────────────┤
│  src/entrypoints/   (REST, SOAP, gRPC, GraphQL, WebSocket, SSE,     │
│                      MQTT, MCP[FastMCP], CDC, FileWatcher, Email,   │
│                      Scheduler, Stream, Webhook)                    │
│      │  middlewares (pure ASGI: idempotency, rate-limit,            │
│      │   correlation-id, error-envelope, tenant-context, audit, waf)│
│      ▼                                                              │
│  src/services/      (core[5-7 universal], ai, integrations, ops,    │
│                      execution, plugins, schema_registry, notebooks)│
│      │  ActionHandlerRegistry, ServiceDSLRegistry, RouteRegistry    │
│      ▼                                                              │
│  src/core/          (config, interfaces[11 доменов], di, tenancy,   │
│                      plugin_runtime, workflow protocols, actions,   │
│                      auth, ai[AIWorkspaceManager], net[WAF],        │
│                      messaging[outbox], scaling, utils)             │
│      ▲                                                              │
│      │ (контракты/Protocols)                                        │
│  src/infrastructure/ (db, cache, storage, messaging, search, audit, │
│                       logging[Graylog pool], sources, sinks,        │
│                       repositories, resilience, observability       │
│                       [Watchdog], secrets[Vault], workflow          │
│                       [Temporal+Lite], execution[Dask], scheduler,  │
│                       clients[ClickHouse pool])                     │
│                                                                     │
│  src/dsl/           (route/, workflow/, service/, contracts/,       │
│                      engine/processors/{ai,rpa,eip,streaming,…},    │
│                      blueprints/[10 паттернов R2], cli/)            │
└─────────────────────────────────────────────────────────────────────┘
                           ▲
                           │ только public API + capability-checked фасады
                           │
┌─────────────────────────────────────────────────────────────────────┐
│  extensions/<name>/  (БИЗНЕС-ЛОГИКА — domain plugins)               │
│    ├── plugin.toml   (capabilities, requires_core, semver, …)       │
│    ├── domain/, repositories/, services/clients/, functions/        │
│    ├── services/<name>.service.toml  (декларативный @service_dsl)   │
│    ├── routes/<route>/{route.toml, *.dsl.yaml}                      │
│    ├── workflows/<wf>.workflow.yaml  (Temporal через DSL)           │
│    ├── actions/, processors/, settings/, migrations/, tests/        │
│    └── frontend/pages/<NN>_<name>.py                                │
└─────────────────────────────────────────────────────────────────────┘
                           ▲
                           │
┌─────────────────────────────────────────────────────────────────────┐
│  routes/<name>/      (DSL-routes как «лёгкие плагины» V11.1a)       │
│    ├── route.toml    (manifest + capabilities + schedule + slo)     │
│    └── *.dsl.yaml    (steps[] любых типов)                          │
└─────────────────────────────────────────────────────────────────────┘

Ограничения слоёв (enforce через tools/checks/check_layers.py)

    entrypoints импортирует только services, schemas, core (Protocols)
    services импортирует только core, schemas
    infrastructure реализует контракты из core (Protocols)
    core не импортирует код из src/ (только stdlib + Protocols)
    dsl импортирует core (контракты) + infrastructure через registries
    extensions/<name>/ импортирует только gd_integration_tools.core.* + gd_integration_tools.testkit.* + capability-checked фасады. Прямой импорт из infrastructure//services/ запрещён.
    frontend/streamlit_app/ импортирует только публичный API + REST через api_client.py.

Капитальные структурные элементы V15
Элемент	Где	Назначение
BasePlugin + PluginLoader	core/plugin_runtime/	Discovery + lifecycle + capability-gate
RouteLoader	dsl/route/	Сканирует routes/<name>/route.toml
ServiceDSLRegistry	dsl/service/registry.py	@service_dsl(crud=True) + service.toml
RouteBuilder (Camel-style)	dsl/route/builder/	Python fluent API; .crud_*, .proxy(), .call_function(), .invoke_workflow(), .get_setting(), .validate_response(), .db_call_procedure()
WorkflowBuilder + Workflow DSL	dsl/workflow/	Temporal-шаги декларативно
ActionDispatcher + ActionHandlerRegistry	core/actions/	Service Activator + 6 invoke modes
ProcessorRegistry (formal API, R1)	dsl/registry/	@processor декоратор для плагинов
Schema-registry (RAM, R1)	services/schema_registry/	JSON-Schema каталог для LSP/docs/AsyncAPI
ResilienceCoordinator + Breaker (purgatory)	infrastructure/resilience/	11 fallback chains, Bulkhead, RateLimiter
AIWorkspaceManager + AIFsFacade	core/ai/	AI Safety: workspace isolation
OutboundHttpClient + WAF-фасад	core/net/	Все :external через WAF
TaskRegistry + Watchdog	infrastructure/observability/	Leak prevention, deadline-эскалация
LiteTemporalBackend	infrastructure/workflow/	In-process Temporal для dev_light
MCP server (FastMCP)	entrypoints/mcp/fastmcp_server.py	Auto-export Tier 1+2 actions как MCP tools
BaseExternalAPIClient (расширенный)	services/core/	Per-service timeouts/pool/retry-policy
ConnectionReuseManager	infrastructure/clients/	Idle ping + reuse-on-demand
ResponseValidatorProcessor	dsl/engine/processors/validation/	Pydantic-validation response_body + DLQ
Обязательный режим работы

Любое изменение файлов выполняется только после точного плана.

Порядок:

    Определить цель задачи (привязать к Wave/Sprint из PLAN.md).
    Определить потенциально затронутые модули, импортёры и зависимости (Graphify).
    Если задача требует актуальных внешних данных — выполнить web research.
    Проверить проект через бибилотеку codeclone.
    Составить точный план (plan-execute skill / planmode + Opus). После составления — отправить на согласование. После одобрения — переключиться на Sonnet.
    Выполнять шаги строго по плану.
    После каждого шага — самопроверка (verify-change skill).
    При необходимости отклонения от плана — остановиться и согласовать.
    После крупной завершённой задачи — /compact.

Даже при изменении одного файла учитывать: импортёров, публичные интерфейсы, схемы, DSL и DI-регистрации.
Согласование с пользователем

Для новых фич, DSL-расширений, workflow-изменений, новых коннекторов и любых многофайловых задач:

    сначала согласование через AskUserQuestion;
    затем план;
    реализация после явного подтверждения.

Безопасность
Запрещено без явного подтверждения

    менять публичные API и сигнатуры;
    удалять или переименовывать файлы, классы, модули;
    добавлять зависимости (см. dependency-decision.md);
    делать push или release;
    читать .env, secrets/, *.pem, *.key, файлы с secret/token в имени.

Commit разрешён только если пользователь явно попросил.
V15 Security Constraints

    Capability-runtime-gate (V11.1): плагин получает БД/секреты/HTTP/FS/MQ только через capability-checked фасады по plugin.toml::capabilities. Доступ вне декларации → CapabilityDeniedError + audit-event.
    WAF strict policy: все net.outbound.<host>:external через WAF-прокси (включая RPA browser-automation + cloud LLM). Исключения :internal требуют ADR + audit. CI gate make check-waf-coverage обязательный.
    AI Safety (V22): AI читает проект, но изменяет ТОЛЬКО новые файлы в ${AI_WORKSPACE}/<tenant>/<session>/<artifact>. Запрещено: write существующих файлов, удаление, прямой subprocess.run. Code-execution только sandboxed (e2b/pyodide). Capability fs.write.* запрещена для AI-плагинов.
    Plugin code injection (V21): call_function('module:fn') валидирует module через whitelist в plugin.toml::call_function_modules.
    FTP TLS (V1, hotfix Sprint 0): запрещено ssl.CERT_NONE / check_hostname=False. Только ssl.create_default_context() + verify_mode=CERT_REQUIRED.
    Auth-стек (V7): R1 = JWT + API-key + mTLS; R2 = SAML+AD. Все non-public endpoints должны иметь explicit auth-guard.
    Idempotency (V5): snok/asgi-idempotency-header middleware обязательно для всех POST/PATCH endpoints.
    Webhook signature (V9): входящие webhooks верифицируются HMAC-SHA256/JWS (Stripe-style).
    Supply-chain (V4): SBOM (cyclonedx) + pip-audit + cosign sign — обязательные CI gates (R3).
    OWASP API Top 10 (V19): OWASP ZAP gate в CI (R3).

DSL Dual-Mode Principle

DSL поддерживается двумя способами одновременно и равноправно.
Python (Camel-style fluent)

RouteBuilder("credit_check_v2") \
    .from_("http:POST /api/v1/credit/check") \
    .policy.idempotency(key="header.X-Idempotency-Key") \
    .get_setting("skb.api_url", to="body.api_url") \
    .proxy(src="/legacy", dst="http://legacy:8080") \
    .call_function("extensions.credit.normalizer:apply_rules") \
    .crud_create("orders", body=Ref("body.order")) \
    .validate_response(schema="CreditDecision", on_error="dlq") \
    .dispatch_action("credit.score.calculate", mode="sync") \
    .invoke_workflow("credit_assessment_ai", mode="async-api") \
    .to("response", code=202, body=Ref("body.invocation_id"))

YAML (route.toml + *.dsl.yaml)

from: { http: { method: POST, path: /api/v1/credit/check } }
steps:
  - get_setting: { path: "skb.api_url", to: body.api_url }
  - proxy: { src: /legacy, dst: http://legacy:8080 }
  - call_function: { ref: extensions.credit.normalizer:apply_rules }
  - crud_create: { entity: orders, body: ${body.order} }
  - validate_response: { schema: CreditDecision, on_error: dlq }
  - dispatch_action: { name: credit.score.calculate, mode: sync }
  - invoke_workflow: { name: credit_assessment_ai, mode: async-api }
to: { response: { code: 202, body: { invocation_id: ${body.invocation_id} } } }

Принципы:

    Один JSON-Schema каталог (R1) экспортирует обе спецификации (Route + Workflow + Service + Plugin).
    В route разрешены несколько однотипных операций подряд (proxy/proxy/proxy, call_function × N, crud_create × N).
    Кастомная логика — в extensions/<name>/functions/*.py через call_function('module:fn') без обёрток в Action.
    Auto-registration: один handler автоматически в REST + SOAP + XML + gRPC + GraphQL + MQ + WS + SSE + MCP + MQTT.

V15-специфичные правила
R-V15-1: Plugin contract V11.1

Любой плагин в extensions/<name>/ должен:

    иметь plugin.toml с name, version, requires_core, capabilities[], tenant_aware, provides[];
    проходить make plugin-schema валидацию;
    декларировать все используемые ресурсы через capabilities[] (вне декларации → CapabilityDeniedError).

R-V15-2: Routes как «лёгкие плагины»

DSL-routes живут в routes/<name>/ с route.toml + *.dsl.yaml (не в dsl_routes/ — legacy). Поддерживаются: semver, requires_core, requires_plugins[], capability-gate, hot-reload, tenant_aware, feature_flag, slo, schedule.
R-V15-3: Auto-registration во всех протоколах

Один раз зарегистрировать handler через @service_dsl(protocols=["all"]) или service.toml → автоматически REST + SOAP + XML + gRPC + GraphQL + MQ + WS + SSE + MCP + MQTT (3-tier model).
R-V15-4: AI Safety (workspace isolation)

AI имеет capability fs.read.<path> (чтение проекта) и fs.create_new.<workspace> (только новые файлы в ${AI_WORKSPACE}/<tenant>/<session>/<artifact>). Запрещено: fs.write.*, удаление, прямой subprocess.run. Code-execution только sandboxed (e2b/pyodide).
R-V15-5: WAF strict для external

Все net.outbound.<host>:external capabilities проходят через WAF-прокси (включая RPA browser-automation + cloud LLM). :internal исключения требуют ADR + audit-event. CI gate make check-waf-coverage.
R-V15-6: 80% YAML / 20% Python

Бизнес-логика плагина — в extensions/<name>/functions/<file>.py как обычные Python-функции. Все routes/services/workflows — декларативно (YAML). Кастомная Python-логика подключается через call_function('module:fn').
R-V15-7: TaskIQ не подключаем

Temporal полностью покрывает функциональность TaskIQ (background/deferred/cron + saga/replay/versioning). Стек: FastStream (MQ) + APScheduler (простой scheduling) + Temporal (durable execution через Workflow DSL).
R-V15-8: Tenacity unification (Sprint 6)

Tenacity 9.0+ уже в стеке (✅ подключён). Custom retry-логика в core/orchestration/retry.py и infrastructure/resilience/retry.py консолидируется через единый API поверх tenacity.
R-V15-9: AI-функции через Workflow DSL

LLM-вызовы в Workflow декларируются как activity (в YAML или Python WorkflowBuilder). Поддерживается structured_output (Pydantic через Instructor), cost_budget_usd, retry, tools.
R-V15-10: Auto-scaling 3 уровня

    Process-level: Granian dynamic workers (SIGUSR1 → fork);
    Task-level: asyncio Bulkhead (HighWatermark/LowWatermark);
    Container-level: k8s HPA exporter (Prometheus metrics).

R-V15-11: Leak prevention обязательно

    TaskRegistry для всех asyncio.create_task (auto-cancel в shutdown).
    Watchdog с deadline_seconds для long-running tasks.
    Connection pool health-check + idle-timeout + max-lifetime.
    AI workspace TTL cleanup (7 дней) + size quota per tenant.
    Все temp-files через tempfile.TemporaryDirectory.

R-V15-12: Универсальная формула роута

Каждый route = route.toml (manifest) + один или несколько *.dsl.yaml с массивом steps[]. Каждый step произвольного типа (proxy/redirect/call_function/dispatch_action/transform/choice/parallel/try_catch/saga/invoke_workflow/policy/db_query_external/db_call_procedure/get_setting/validate_response/crud_*/publish_event/notify_cascade/audit). Несколько однотипных операций подряд разрешены.
R-V15-13: Per-service timeouts

Каждый business-сервис в extensions/<name>/services/clients/*.py объявляет свои connect_timeout/read_timeout/write_timeout/pool_timeout/total_timeout через конструктор BaseExternalAPIClient или декларативно в service.toml::[timeouts]. Глобальные httpx-settings — только дефолты.
R-V15-14: Connection pools обязательно

Все backend-clients используют explicit connection pools:

    DB (SQLAlchemy): pool_size, max_overflow, pool_recycle, pool_pre_ping;
    Redis: max_connections, socket_keepalive, health_check_interval;
    HTTP (httpx): Limits(max_connections, max_keepalive_connections, keepalive_expiry);
    ClickHouse: pool_size, pool_overflow, recycle_seconds (через clickhouse-connect[asyncio] или asynch);
    Graylog: persistent TCP/HTTPS pool через pygelf/graypy + circuit breaker;
    ConnectionReuseManager для idle ping + reuse-on-demand.

R-V15-15: Health-check без DSL-процессоров

Health-checks реализуются как обычные методы в TechService + регистрация через ActionSpec. Не создавать .from_health_check() или HealthCheckProcessor — текущий паттерн (tech.py 13 методов) достаточен.
R-V15-16: Миграция CRUD из ядра в extensions/

Существующие 4 CRUD-ресурса (users, orders, orderkinds, files) мигрируют из ядра в extensions/core_entities/ (Sprint 7 Dev2). После миграции ядро содержит только universal endpoints (admin, tech, system, health, schemas, scheduler).
R-V15-17: Settings access из DSL

Builder .get_setting("path.to.value", default=...) + YAML-step get_setting: { path: "...", to: body.x }. Capability-checked: settings.read.<scope>. Глобальная инъекция settings.section остаётся для Python-кода.
R-V15-18: Response validation для внешних API

ResponseValidatorProcessor (dsl/engine/processors/validation/response.py) — Pydantic-validation на входящий response_body. Builder: .validate_response(schema=PydanticModel, on_error="dlq"|"fail"|"warn").
Запрещённые паттерны (V15)

    God Object (>300 строк, >10 публичных методов).
    God-modules (>500 LOC) — split на семейные модули.
    Прямой импорт infrastructure/ в services//core/.
    Хардкод конфигурации и секретов.
    time.sleep() в async-контексте.
    Прямой SomeClass() в обход DI.
    except Exception: pass.
    Логирование через print или logging.basicConfig.
    Кастомные функции при наличии библиотечных аналогов (см. dependency-decision.md).
    aiohttp / prefect / taskiq в DSL.
    Прямой subprocess.run в плагинах (только sandboxed).
    ssl.CERT_NONE / check_hostname=False (V1).
    pickle / marshal для untrusted данных.
    yaml.load без safe_load.
    eval / exec без явного sandboxing.
    AI-агент изменяет существующие файлы проекта (V22).
    Capability-обращение вне plugin.toml::capabilities (V11.1).
    Push в main без явного запроса.
    Skip pre-commit/pre-push hooks без обоснования.
    .from_health_check() / HealthCheckProcessor (V15: использовать TechService + ActionSpec).
    Глобальные httpx-settings вместо per-service timeouts в business-сервисах.

Внешнее исследование

Сначала использовать внутренний контекст: PLAN.md, Graphify, ARCHITECTURE.md, .claude/DECISIONS.md, релевантные исходники. Только если задача требует актуальных внешних данных — MCP web search (DuckDuckGo / Perplexity) + Fetch MCP / WebSearch / WebFetch.
Когда внешний поиск обязателен

Сравнение библиотек/SDK; новая библиотека; совместимость с Python 3.14+; changelog/breaking changes; статус поддержки; best practices; производительность; вопросы вида «что лучше», «совместимо ли», «не устарела ли».
Правила

    2-5 коротких целевых запросов.
    Официальная документация → GitHub releases/changelog → PyPI → migration guides.
    Fetch MCP для углублённого чтения 1-2 страниц.
    Разделять: внешние факты (со ссылкой и датой) vs вывод применительно к проекту.
    Если web search недоступен — явно сообщить.

Верификация
Базовый набор

    make format / make format-check
    make lint / make lint-strict
    make type-check / make type-check-strict
    make deps-check / make deps-check-strict
    make secrets-check

По области изменений

    Public contracts / DI / DSL: make routes + make actions + make plugin-schema + make route-schema + make service-schema.
    Документация: make docs.
    Зависимости/секреты/релиз: make deps-check + make secrets-check + make readiness-check.
    Performance-критичные: make perf (после Wave 7).
    Resilience-критичные: make chaos (после Wave 13).
    Security-критичные: make security + make check-waf-coverage (после R3).

V15-специфичные gates

    make check-waf-coverage — все :external capabilities идут через OutboundHttpClient (R3).
    make custom-code-audit — поиск кастомного кода с библиотечными аналогами (Sprint 6).
    make ci = lint + type + test + coverage + security (composite).
    make pr = ci + docs (composite перед PR).

Документация и docstring policy
Pre-push docstring gate (Sprint 0)

    tools/checks/check_docstrings.py --strict через .pre-commit-config.yaml (stages: pre-push).
    GitHub Action docs-required.yml блокирует merge без docstring на новых def/class.
    GitLab CI mirror.
    Amnesty-baseline tools/checks/check_docstrings_allowlist.txt.

Sphinx auto-gen API reference (Sprint 9)

Auto-gen из docstrings; multi-version + ReadTheDocs/GitLab Pages; Diátaxis структура; Vale prose linter + ru-language proofreader.
Docstring правила

    Все docstrings и комментарии — на русском языке.
    Google-style.
    Полные docstrings обязательны для public API всех слоёв core/, dsl/engine/, core/interfaces/, core/protocols.py.
    Запрет пустых/TODO docstrings.

Память сессий

После крупной задачи: обновлять .claude/CONTEXT.md; сохранять подробную сводку в vault/session-YYYY-MM-DD-HHMM-summary.md; создавать feedback_*.md или project_*.md в .claude/projects/.../memory/.

make wave-memory NAME=<slug> [TYPE=feedback|project] — создаёт скелет.
Команда (4 разработчика, V15)
Dev	Зона ответственности
Dev1 — Plugin/Platform	Plugin contract, capability-gate, ASGI middleware, Auth, WAF, supply-chain, leak prevention, ConnectionReuseManager
Dev2 — DSL/Workflow	RouteBuilder split (Wave G), .crud_*, .get_setting(), .validate_response(), .db_call_procedure(), Sinks, Workflow DSL, Temporal, конвертеры, perf
Dev3 — Frontend/Ops	Frontend split, tools/Makefile/manage.py reorganization, docs (Sphinx + Diátaxis + pre-push gate), 3-tier auto-reg, dashboards, chaos-tests, auto-scaler, Graylog pool
Dev4 — AI/Data	PydanticAI, LiteLLM, RAG cache (3 уровня), LangMem + RLM-toolkit, FastMCP, Multimodal RAG, AI Safety, AI cost dashboard, ClickHouse pool

См. PLAN.md §6 (Wave-расписание Sprint 0–9).
Основные агенты (.claude/agents/)
Агент	Назначение	Запуск
feature-coordinator	Главный координатор фич; AskUserQuestion → план → делегирование subagents → контроль	proactive / /plan
code-reviewer	Проверка соответствия архитектуре, типизации, operational-правилам	/review
dsl-analyst	Анализ покрытия DSL, предложения расширений	/dsl-review
runtime-debugger	Диагностика runtime/БД/Redis/RabbitMQ/health/profiling	/trace
docs-navigator	Минимальный маршрут чтения по graphify/wiki/docs/vault	/docs-scan
verification-runner	Запуск минимально достаточных проверок Makefile	/verify
integration-contract-reviewer	Проверка контрактов коннекторов, схем, совместимости DSL/runtime	/contract-review
dead-code-hunter	Поиск мёртвого кода, лишних импортов, неиспользуемых зависимостей	/dead-code
system-analyst	Анализ внешних технологий (web research обязателен)	/research, /upgrade-check
Основные команды (.claude/commands/)

/plan, /map, /trace, /verify, /review, /contract-review, /dsl-review, /dead-code, /docs-scan, /research, /upgrade-check, /commit-work, /compact.
Основные skills (.claude/skills/)

plan-execute, codebase-map, verify-change, commit-work, compact-session, feature-development, connector-building, refactoring, research-current-tech, workflow-engineering.
Pre-step initialization ritual

graphify update . && \
cat .claude/DECISIONS.md .claude/KNOWN_ISSUES.md && \
python tools/checks/check_layers.py

Файлы правил (@include)

@include .claude/rules/refactoring.md
@include .claude/rules/runtime-debug.md
@include .claude/rules/operating-mode.md
@include .claude/rules/verification-policy.md
@include .claude/rules/commit-policy.md
@include .claude/rules/skill-policy.md
@include .claude/rules/subagent-policy.md
@include .claude/rules/online-research.md
@include .claude/rules/dependency-decision.md
@include .claude/rules/path-policy.md
Ссылки

    PLAN.md — главный roadmap (V15 FINAL)
    /root/.claude/plans/foamy-puzzling-dragonfly.md — полный аналитический GAP-анализ
    ARCHITECTURE.md — карта архитектуры (требует обновления после Wave 12)
    .claude/CONTEXT.md — оперативная сводка
    .claude/DECISIONS.md — устойчивые решения
    .claude/KNOWN_ISSUES.md — открытый техдолг
    vault/session-*-summary.md — архив сессий

Версия CLAUDE.md синхронизирована с PLAN.md V15 (2026-05-05). При обновлении PLAN.md обновлять синхронно.