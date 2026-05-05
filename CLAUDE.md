# CLAUDE.md — gd_integration_tools

> **Версия документа**: V14 (синхронизирована с PLAN.md V14 от 2026-05-05).
> Ниже зафиксированы цель проекта, архитектура, обязательные правила и
> служебная память. Любая работа выполняется в соответствии с этим
> документом и `PLAN.md` (см. §Текущий план).

---

## Проект

`gd_integration_tools` — **универсальное domain-agnostic ядро**
интеграционной шины на Python 3.14+ (Apache-Camel- и Airflow-style).
Внутренний продукт банка для:
- декларативного построения интеграционных маршрутов (DSL: YAML + Python builder);
- workflow / orchestration (Temporal как default backend через protocol);
- multi-protocol auto-registration (один handler → REST + SOAP + XML + gRPC + GraphQL + MQ + WS + SSE + MCP + MQTT);
- multi-backend gateways (PG↔Oracle↔MSSQL↔MySQL↔DB2; Redis↔KeyDB; S3↔MinIO↔LocalFS; Kafka↔RabbitMQ↔Redis Streams↔NATS);
- RPA, CDC, file-watcher, webhook source/sink;
- AI/RAG/agents с MCP-сервером (FastMCP) и AI Safety (workspace isolation);
- multi-tenancy (TenantContext + per-tenant SLO/quotas);
- developer portal на Streamlit (36+ страниц).

**Бизнес-логика — только в `extensions/<name>/`**, ядро domain-agnostic.
Кредитный конвейер — внешний потребитель; его текущая логика мигрирует
в первый плагин.

**80% декларативно (YAML/TOML) / 20% Python** — через
`call_function('module:fn')` без обёрток в Action.

---

## Текущий план

**Главный документ**: `PLAN.md` (V14 FINAL, ~3000 строк, 42 раздела) и
`/root/.claude/plans/foamy-puzzling-dragonfly.md` (полный аналитический
GAP-анализ).

**Срок**: 14-15 недель ≈ 3.5 месяца при параллельной работе **4
разработчиков** (Dev1 Plugin/Platform · Dev2 DSL/Workflow · Dev3
Frontend/Ops · Dev4 AI/Data).

**21 зафиксированное архитектурное решение** (см. PLAN.md §1) — каждое
из них обязательно для соблюдения.

---

## Что читать сначала

Перед анализом архитектуры, кода, зависимостей и документации:
1. `PLAN.md` (V14 FINAL) — текущий roadmap и решения;
2. `graphify-out/GRAPH_REPORT.md` (если есть);
3. `graphify-out/wiki/index.md` (основной индекс при наличии);
4. `ARCHITECTURE.md`;
5. `.claude/CONTEXT.md` — краткая оперативная сводка;
6. Точечные документы и исходники по задаче.

Связи между сущностями — через `graphify query`, `graphify path`, `graphify explain`. **Не читать весь репозиторий целиком без необходимости.**

---

## Приоритет источников

При конфликте источников доверять в таком порядке:
1. **`PLAN.md` V14** (фиксирует курс развития);
2. исходный код;
3. Graphify (`graphify-out/...`);
4. `ARCHITECTURE.md`;
5. `.claude/rules/...`;
6. `.claude/DECISIONS.md`;
7. `.claude/KNOWN_ISSUES.md`;
8. `.claude/CONTEXT.md`.

---

## Служебная память Claude

Файлы в `.claude/` — служебный слой памяти и управления поведением Claude. Не пользовательская документация, не хранить в `docs/`.

Если существуют:
- `.claude/CONTEXT.md` — краткая оперативная сводка;
- `.claude/DECISIONS.md` — журнал устойчивых решений;
- `.claude/KNOWN_ISSUES.md` — список известных ограничений.

---

## Graphify как основной контекст

Graphify — основной источник структурного знания о проекте. Используй его:
- для поиска связей между модулями;
- для оценки последствий изменений;
- для поиска импортёров и зависимостей;
- перед любым многофайловым изменением;
- перед ревью и рефакторингом.

После commit граф должен автоматически обновляться (`graphify update .`).

---

## Архитектура (V14)

### Высокоуровневая схема

```text
┌─────────────────────────────────────────────────────────────────────┐
│  frontend/streamlit_app/  (36+ pages: Logs, Healthcheck, Workflows, │
│      DSL Editor, RAG, Wiki, Plugin Marketplace, Resilience, …)      │
│                          │                                          │
│                          ▼  REST/gRPC/WS                            │
├─────────────────────────────────────────────────────────────────────┤
│  src/entrypoints/   (REST, SOAP, gRPC, GraphQL, WebSocket, SSE,     │
│                      MQTT, MCP[FastMCP], CDC, FileWatcher, Email,   │
│                      Scheduler, Stream, Webhook)                    │
│      │  middlewares (pure ASGI: idempotency, rate-limit,            │
│      │   correlation-id, error-envelope, tenant-context, audit)     │
│      ▼                                                              │
│  src/services/      (core, ai, integrations, ops, io, plugins,      │
│                      execution, notebooks)                          │
│      │  ActionHandlerRegistry, ServiceDSLRegistry, RouteRegistry    │
│      ▼                                                              │
│  src/core/          (config, interfaces[11 доменов], di, tenancy,   │
│                      plugin_runtime, workflow protocols, actions,   │
│                      auth, ai[AIWorkspaceManager], utils)           │
│      ▲                                                              │
│      │ (контракты/Protocols)                                        │
│  src/infrastructure/ (db, cache, storage, messaging, search, audit, │
│                       logging, sources, sinks, repositories,        │
│                       resilience, observability, secrets[Vault],    │
│                       workflow[Temporal], execution[Dask], scheduler│
│                       [APScheduler], clients)                       │
│                                                                     │
│  src/dsl/           (route/[Camel-style RouteBuilder + YAML loader],│
│                      workflow/[Workflow DSL + Temporal compiler],   │
│                      contracts/primitives.py,                       │
│                      engine/processors/{ai,rpa,eip,streaming,…},    │
│                      blueprints/[10 паттернов R2], cli/)            │
└─────────────────────────────────────────────────────────────────────┘
                           ▲
                           │ только public API + capability-checked фасады
                           │
┌─────────────────────────────────────────────────────────────────────┐
│  extensions/<name>/  (БИЗНЕС-ЛОГИКА — domain plugins)               │
│    ├── plugin.toml   (capabilities, requires_core, semver, …)       │
│    ├── domain/       (Pydantic / SQLAlchemy сущности)               │
│    ├── repositories/ (наследники AsyncRepository[T])                │
│    ├── services/clients/  (внешние интеграции через WAF)            │
│    ├── functions/    (custom Python для call_function)              │
│    ├── routes/<route>/{route.toml, *.dsl.yaml}                      │
│    ├── workflows/<wf>.workflow.yaml  (Temporal через DSL)           │
│    ├── actions/, processors/, settings/, migrations/, tests/        │
│    └── frontend/pages/<NN>_<name>.py                                │
└─────────────────────────────────────────────────────────────────────┘
                           ▲
                           │
┌─────────────────────────────────────────────────────────────────────┐
│  routes/<name>/      (DSL-routes как «лёгкие плагины»)              │
│    ├── route.toml    (manifest + capabilities + schedule + slo)     │
│    └── *.dsl.yaml    (steps[] любых типов)                          │
└─────────────────────────────────────────────────────────────────────┘
```

### Ограничения слоёв (enforce через `tools/checks/check_layers.py`)

- `entrypoints` импортирует только `services`, `schemas`, `core` (Protocols)
- `services` импортирует только `core`, `schemas`
- `infrastructure` реализует контракты из `core` (Protocols)
- `core` не импортирует код из `src/` (только stdlib + Protocols)
- `dsl` импортирует `core` (контракты) + `infrastructure` через registries
- `extensions/<name>/` импортирует только `gd_integration_tools.core.*` + `gd_integration_tools.testkit.*` + capability-checked фасады. Прямой импорт из `infrastructure/`/`services/` **запрещён**.
- `frontend/streamlit_app/` импортирует только публичный API + REST через `api_client.py`.

### Капитальные структурные элементы V14

| Элемент | Где | Назначение |
|---|---|---|
| `BasePlugin` + `PluginLoader` | `core/plugin_runtime/` | Discovery + lifecycle + capability-gate |
| `RouteLoader` | `dsl/route/` | Сканирует `routes/<name>/route.toml` |
| `ServiceDSLRegistry` | `dsl/service_dsl.py` | `@service_dsl(crud=True)` + `service.toml` |
| `RouteBuilder` (Camel-style) | `dsl/route/builder/` | Python fluent API (после Wave G split) |
| `WorkflowBuilder` + Workflow DSL | `dsl/workflow/` | Temporal-шаги декларативно |
| `ActionDispatcher` + `ActionHandlerRegistry` | `core/actions/` | Service Activator + 6 invoke modes |
| `ProcessorRegistry` (formal API, R1) | `dsl/registry/` | `@processor` декоратор для плагинов |
| `Schema-registry` (RAM, R1) | `services/schema_registry/` | JSON-Schema каталог для LSP/docs/AsyncAPI |
| `ResilienceCoordinator` + `Breaker` (purgatory) | `infrastructure/resilience/` | 11 fallback chains, Bulkhead, RateLimiter |
| `AIWorkspaceManager` + `AIFsFacade` | `core/ai/` | AI Safety: workspace isolation |
| `OutboundHttpClient` + WAF-фасад | `core/net/` | Все `:external` через WAF |
| `TaskRegistry` + `Watchdog` | `infrastructure/observability/` | Leak prevention, deadline-эскалация |
| `LiteTemporalBackend` | `infrastructure/workflow/` | In-process Temporal для `dev_light` |
| `MCP server (FastMCP)` | `entrypoints/mcp/fastmcp_server.py` | Auto-export Tier 1+2 actions как MCP tools |

---

## Обязательный режим работы

**Любое изменение файлов выполняется только после точного плана.**

Порядок:
1. Определить цель задачи (привязать к Wave/Sprint из `PLAN.md`).
2. Определить потенциально затронутые модули, импортёры и зависимости (Graphify).
3. Если задача требует актуальных внешних данных — выполнить web research.
4. Составить точный план (`plan-execute` skill / planmode + Opus). После составления — отправить на согласование. После одобрения — переключиться на Sonnet.
5. Выполнять шаги строго по плану.
6. После каждого шага — самопроверка (`verify-change` skill).
7. При необходимости отклонения от плана — остановиться и согласовать.
8. После крупной завершённой задачи — `/compact`.

**Даже при изменении одного файла** учитывать:
- кто его импортирует;
- какие публичные интерфейсы он даёт;
- какие схемы, DSL или DI-регистрации с ним связаны.

---

## Согласование с пользователем

Для новых фич, DSL-расширений, workflow-изменений, новых коннекторов и любых многофайловых задач:
1. сначала согласование через `AskUserQuestion`;
2. затем план;
3. реализация после явного подтверждения.

---

## Безопасность

### Запрещено без явного подтверждения

- менять публичные API и сигнатуры;
- удалять или переименовывать файлы, классы, модули;
- добавлять зависимости (см. правило `dependency-decision.md`);
- делать push или release;
- читать `.env`, `secrets/`, `*.pem`, `*.key`, файлы с `secret`/`token` в имени.

Commit разрешён только если пользователь явно попросил.

### V14 Security Constraints (зафиксированы в PLAN.md)

1. **Capability-runtime-gate (V11.1)**: плагин получает БД/секреты/HTTP/FS/MQ только через capability-checked фасады по `plugin.toml::capabilities`. Доступ вне декларации → `CapabilityDeniedError` + audit-event.
2. **WAF strict policy**: все `net.outbound.<host>:external` через WAF-прокси (включая RPA browser-automation + cloud LLM). Исключения `:internal` требуют ADR + audit. CI gate `make check-waf-coverage` обязательный.
3. **AI Safety (V22)**: AI читает проект, но изменяет ТОЛЬКО новые файлы в `${AI_WORKSPACE}/<tenant>/<session>/<artifact>`. Запрещено: write существующих файлов, удаление, прямой `subprocess.run`. Code-execution только sandboxed (e2b/pyodide). Capability `fs.write.*` запрещена для AI-плагинов.
4. **Plugin code injection (V21)**: `call_function('module:fn')` валидирует module через whitelist в `plugin.toml::call_function_modules`.
5. **FTP TLS (V1, hotfix Sprint 0)**: запрещено использовать `ssl.CERT_NONE` / `check_hostname=False`. Только `ssl.create_default_context()` + `verify_mode=CERT_REQUIRED`.
6. **Auth-стек (V7)**: R1 = JWT + API-key + mTLS; R2 = SAML+AD. Все non-public endpoints должны иметь explicit auth-guard.
7. **Idempotency (V5)**: `snok/asgi-idempotency-header` middleware обязательно для всех POST/PATCH endpoints.
8. **Webhook signature (V9)**: входящие webhooks верифицируются HMAC-SHA256/JWS (Stripe-style).
9. **Supply-chain (V4)**: SBOM (cyclonedx) + pip-audit + cosign sign — обязательные CI gates (R3).
10. **OWASP API Top 10 (V19)**: OWASP ZAP gate в CI (R3).

---

## DSL Dual-Mode Principle

DSL поддерживается **двумя способами одновременно** и равноправно:

### Python (Camel-style fluent)
```python
RouteBuilder("credit_check_v2") \
    .from_("http:POST /api/v1/credit/check") \
    .policy.idempotency(key="header.X-Idempotency-Key") \
    .proxy(src="/legacy", dst="http://legacy:8080") \
    .call_function("extensions.credit.normalizer:apply_rules") \
    .dispatch_action("credit.score.calculate", mode="sync") \
    .invoke_workflow("credit_assessment_ai", mode="async-api") \
    .to("response", code=202, body=Ref("body.invocation_id"))
```

### YAML (`route.toml + *.dsl.yaml`)
```yaml
# routes/<name>/main.dsl.yaml
from: { http: { method: POST, path: /api/v1/credit/check } }
steps:
  - proxy: { src: /legacy, dst: http://legacy:8080 }
  - call_function: { ref: extensions.credit.normalizer:apply_rules }
  - dispatch_action: { name: credit.score.calculate, mode: sync }
  - invoke_workflow: { name: credit_assessment_ai, mode: async-api }
to: { response: { code: 202, body: { invocation_id: ${body.invocation_id} } } }
```

**Принципы**:
- Один JSON-Schema каталог (R1) экспортирует обе спецификации (Route + Workflow + Service + Plugin).
- В route разрешены **несколько однотипных операций подряд** (proxy/proxy/proxy, call_function × N).
- Кастомная логика — в `extensions/<name>/functions/*.py` через `call_function('module:fn')` без обёрток в Action.
- Auto-registration: один handler автоматически в REST + SOAP + XML + gRPC + GraphQL + MQ + WS + SSE + MCP + MQTT.

---

## Внешнее исследование

Сначала использовать внутренний контекст:
- `PLAN.md`;
- Graphify;
- `ARCHITECTURE.md`;
- `.claude/DECISIONS.md`;
- релевантные исходники.

Только если задача требует актуальных внешних данных — MCP web search (DuckDuckGo / Perplexity) + Fetch MCP / WebSearch / WebFetch.

### Когда внешний поиск обязателен

Перед ответом ОБЯЗАТЕЛЬНО использовать web search, если вопрос относится к одному из классов:

- сравнение библиотек, фреймворков, SDK, ORM, брокеров, workflow-движков, HTTP-клиентов, DI-контейнеров, validation/parsing-библиотек;
- поиск новой библиотеки или современной альтернативы;
- совместимость с Python 3.14+;
- поддержка конкретной версии FastAPI / Pydantic / SQLAlchemy / Redis / Kafka / RabbitMQ SDK;
- changelog, breaking changes, deprecated API, release notes;
- статус поддержки проекта;
- best practices, новые паттерны;
- производительность, ограничения, известные баги;
- вопросы вида: "что лучше использовать", "какую библиотеку выбрать", "есть ли более современная альтернатива", "совместимо ли с Python 3.14", "не устарела ли библиотека", "какие breaking changes".

### Правила

1. Сначала 2-5 коротких целевых запросов.
2. Проверять: официальную документацию → GitHub releases/changelog → PyPI → migration guides.
3. Fetch MCP для углублённого чтения 1-2 наиболее релевантных страниц.
4. В итоговом ответе разделять: внешние подтверждённые факты (со ссылкой и датой) vs вывод применительно к архитектуре проекта.
5. Если web search недоступен — явно сообщить.

Предпочитать: официальную документацию, GitHub releases/changelog, engineering-блоги вендоров. Избегать: SEO-статей, устаревших gist'ов, анонимных источников.

---

## Верификация

В проекте не навязывать тесты по умолчанию. Использовать минимально достаточный набор проверок из Makefile.

### Базовый набор
- `make format` / `make format-check`
- `make lint` / `make lint-strict`
- `make type-check` / `make type-check-strict`
- `make deps-check` / `make deps-check-strict`
- `make secrets-check`

### По области изменений
- Public contracts / DI / DSL: `make routes` + `make actions` + `make plugin-schema` + `make route-schema`.
- Документация: `make docs`.
- Зависимости/секреты/релиз: `make deps-check` + `make secrets-check` + `make readiness-check`.
- Performance-критичные: `make perf` (после Wave 7).
- Resilience-критичные: `make chaos` (после Wave 13).
- Security-критичные: `make security` + `make check-waf-coverage` (после R3).

### V14-специфичные gates (новые)
- `make check-waf-coverage` — все `:external` capabilities идут через `OutboundHttpClient` (R3).
- `make custom-code-audit` — поиск кастомного кода с библиотечными аналогами (Sprint 6).
- `make ci` = lint + type + test + coverage + security (composite).
- `make pr` = ci + docs (composite перед PR).

**Запрещено** запускать всё подряд без необходимости.

---

## Документация и docstring policy

### Pre-push docstring gate (V14, Sprint 0)
- `tools/checks/check_docstrings.py --strict` через `.pre-commit-config.yaml` (stages: pre-push).
- GitHub Action `docs-required.yml` — блокирует merge без docstring на новых `def`/`class`.
- GitLab CI mirror.
- Amnesty-baseline `tools/checks/check_docstrings_allowlist.txt` (legacy, поэтапно сводить к 0).

### Sphinx auto-gen API reference (Sprint 9 Dev3)
- Auto-gen из docstrings (для `core/`, `dsl/engine/`, `core/interfaces/`).
- Multi-version + ReadTheDocs/GitLab Pages.
- Diátaxis структура: `getting-started/`, `how-to/`, `reference/`, `explanation/`.
- Vale prose linter + ru-language proofreader (Sprint 5 Dev3).

### Docstring правила
- Все docstrings и комментарии — **на русском языке**.
- Google-style.
- Полные docstrings обязательны для public API всех слоёв `core/`, `dsl/engine/`, `core/interfaces/`, `core/protocols.py`.
- Запрет пустых/TODO docstrings.

---

## Память сессий

После крупной завершённой задачи:
- обновлять `.claude/CONTEXT.md`;
- сохранять подробную сводку в `vault/session-YYYY-MM-DD-HHMM-summary.md`;
- создавать `feedback_*.md` или `project_*.md` в `.claude/projects/.../memory/` (post-wave memory note).

`vault/` — архив истории. `.claude/` — служебная память Claude.

`make wave-memory NAME=<slug> [TYPE=feedback|project]` — создаёт скелет записи + добавляет строку в `MEMORY.md`.

---

## Подход к токенам и скорости

- Не читать весь репозиторий.
- Начинать с `PLAN.md` → Graphify → `ARCHITECTURE.md`.
- Узкие запросы с конкретными путями.
- Делегировать узкие исследования subagents (см. правило `subagent-policy.md`).
- Хранить повторяемые процедуры в skills и rules.
- После завершения крупного этапа — `/compact`.

---

## Оркестрация

**Главный координатор** (`feature-coordinator`):
- согласует требования;
- планирует;
- делегирует side-task'и subagents;
- собирает результаты;
- запускает самопроверку;
- обновляет оперативный контекст после крупных задач.

---

## Основные агенты (`.claude/agents/`)

| Агент | Назначение | Запуск |
|---|---|---|
| `feature-coordinator` | Главный координатор фич; AskUserQuestion → план → делегирование subagents → контроль | proactive / `/plan` |
| `code-reviewer` | Проверка соответствия архитектуре, типизации, operational-правилам | `/review` |
| `dsl-analyst` | Анализ покрытия DSL, предложения расширений | `/dsl-review` |
| `runtime-debugger` | Диагностика runtime/БД/Redis/RabbitMQ/health/profiling | `/trace` |
| `docs-navigator` | Минимальный маршрут чтения по graphify/wiki/docs/vault | `/docs-scan` |
| `verification-runner` | Запуск минимально достаточных проверок Makefile | `/verify` |
| `integration-contract-reviewer` | Проверка контрактов коннекторов, схем, совместимости DSL/runtime | `/contract-review` |
| `dead-code-hunter` | Поиск мёртвого кода, лишних импортов, неиспользуемых зависимостей | `/dead-code` |
| `system-analyst` | Анализ внешних технологий, библиотек, Python 3.14+ совместимости (web research обязателен) | `/research`, `/upgrade-check` |

---

## Основные команды (`.claude/commands/`)

| Команда | Назначение |
|---|---|
| `/plan <задача>` | Составить план через `plan-execute` skill |
| `/map <область>` | Построить карту незнакомого модуля |
| `/trace <симптом>` | Диагностика бага без немедленного исправления |
| `/verify` | Самопроверка текущих изменений |
| `/review` | Ревью изменённых файлов сессии |
| `/contract-review <цель>` | Проверка интеграционного контракта |
| `/dsl-review` | Анализ DSL и предложения расширений |
| `/dead-code` | Поиск мёртвого кода |
| `/docs-scan <тема>` | Найти маршрут чтения по теме |
| `/research <тема>` | Поиск актуальных внешних данных |
| `/upgrade-check <библиотека>` | Проверить актуальность подхода/версии |
| `/commit-work <описание>` | Подготовить и выполнить commit (только по явной команде) |
| `/compact` | Сжать контекст после крупной задачи |

---

## Основные skills (`.claude/skills/`)

| Skill | Назначение |
|---|---|
| `plan-execute` | Обязательный режим для любых изменений (план → шаги → самопроверка) |
| `codebase-map` | Карта кода и зависимостей для незнакомой области |
| `verify-change` | Минимально достаточные проверки Makefile |
| `commit-work` | Подготовка и выполнение commit |
| `compact-session` | Сжатие контекста сессии |
| `feature-development` | Воркфлоу новой фичи |
| `connector-building` | Создание нового коннектора (REST/SOAP/gRPC/GraphQL/Queue) |
| `refactoring` | Безопасный рефакторинг с smoke-тестами |
| `research-current-tech` | Актуальные внешние данные по библиотекам |
| `workflow-engineering` | Создание/расширение workflow-движка |

---

## Команда (4 разработчика, V14)

| Dev | Зона ответственности |
|---|---|
| **Dev1 — Plugin/Platform** | Plugin contract, capability-gate, ASGI middleware, Auth, WAF, supply-chain, leak prevention |
| **Dev2 — DSL/Workflow** | RouteBuilder split (Wave G), Sinks, Workflow DSL, Temporal, новые конвертеры/процессоры, perf-tuning |
| **Dev3 — Frontend/Ops** | Frontend split, tools/Makefile/manage.py reorganization, docs (Sphinx + Diátaxis + pre-push gate), 3-tier auto-reg, dashboards, chaos-tests, auto-scaler |
| **Dev4 — AI/Data** | PydanticAI, LiteLLM, RAG cache (3 уровня), LangMem + RLM-toolkit, FastMCP, Multimodal RAG, AI Safety, AI cost dashboard |

См. `PLAN.md §6` (Wave-расписание Sprint 0–9).

---

## Запрещённые паттерны (V14)

- **God Object** (класс >300 строк или >10 публичных методов).
- **God-modules** (>500 LOC) — split на семейные модули.
- Прямой импорт `infrastructure/` в `services/`/`core/`.
- Хардкод конфигурации и секретов.
- `import time; time.sleep()` в async-контексте.
- Прямой `SomeClass()` в обход DI-контейнера.
- `except Exception: pass` (глотание ошибок).
- Логирование через `print` или `logging.basicConfig`.
- Кастомные функции, если есть библиотечные аналоги (см. `dependency-decision.md`).
- `aiohttp` / `prefect` в DSL.
- Прямой `subprocess.run` в плагинах (только sandboxed).
- `ssl.CERT_NONE` / `check_hostname=False` (V1).
- `pickle` / `marshal` для untrusted данных.
- `yaml.load` без `safe_load`.
- `eval` / `exec` без явного sandboxing.
- AI-агент изменяет существующие файлы проекта (V22).
- Capability-обращение вне `plugin.toml::capabilities` (V11.1).
- Push в main без явного запроса.
- Skip pre-commit/pre-push hooks без обоснования.

---

## V14-специфичные правила (новые)

### R-V14-1: Plugin contract V11.1
Любой плагин в `extensions/<name>/` должен:
- иметь `plugin.toml` с `name`, `version`, `requires_core`, `capabilities[]`, `tenant_aware`, `provides[]`;
- проходить `make plugin-schema` валидацию;
- декларировать все используемые ресурсы через `capabilities[]` (вне декларации → `CapabilityDeniedError`).

### R-V14-2: Routes как «лёгкие плагины»
DSL-routes живут в `routes/<name>/` с `route.toml + *.dsl.yaml` (не в `dsl_routes/` — legacy). Поддерживаются:
- semver на route + `requires_core` + `requires_plugins[]`;
- capability-gate (тот же что у плагинов);
- hot-reload через единый watchfiles-cycle;
- `tenant_aware`, `feature_flag`, `slo`, `schedule` как поля manifest.

### R-V14-3: Auto-registration во всех протоколах
Один раз зарегистрировать handler через `@service_dsl(protocols=["all"])` или `service.toml` → автоматически появляется endpoint в REST + SOAP + XML + gRPC + GraphQL + MQ + WS + SSE + MCP + MQTT (3-tier model).

### R-V14-4: AI Safety (workspace isolation)
AI имеет capability:
- `fs.read.<path>` — чтение проекта;
- `fs.create_new.<workspace>` — только новые файлы в `${AI_WORKSPACE}/<tenant>/<session>/<artifact>`.

Запрещено: `fs.write.*` (для AI-плагинов), удаление, прямой `subprocess.run`. Code-execution только sandboxed (e2b/pyodide).

### R-V14-5: WAF strict для external
Все `net.outbound.<host>:external` capabilities проходят через WAF-прокси (включая RPA browser-automation + cloud LLM). `:internal` исключения требуют ADR + audit-event. CI gate `make check-waf-coverage`.

### R-V14-6: 80% YAML / 20% Python
Бизнес-логика плагина — в `extensions/<name>/functions/<file>.py` как обычные Python-функции. Все routes/services/workflows — декларативно (YAML). Кастомная Python-логика подключается через `call_function('module:fn')`.

### R-V14-7: TaskIQ не подключаем
Temporal полностью покрывает функциональность TaskIQ (background/deferred/cron + saga/replay/versioning). Стек: FastStream (MQ) + APScheduler (простой scheduling) + Temporal (durable execution через Workflow DSL).

### R-V14-8: Tenacity unification (Sprint 6)
Tenacity 9.0+ уже в стеке. Custom retry-логика в `core/orchestration/retry.py` и `infrastructure/resilience/retry.py` консолидируется через единый API поверх tenacity.

### R-V14-9: AI-функции через Workflow DSL
LLM-вызовы в Workflow декларируются как `activity` (в YAML или Python `WorkflowBuilder`). Поддерживается structured_output (Pydantic через Instructor), cost_budget_usd, retry, tools.

### R-V14-10: Auto-scaling 3 уровня
- Process-level: Granian dynamic workers (SIGUSR1 → fork);
- Task-level: asyncio Bulkhead (HighWatermark/LowWatermark);
- Container-level: k8s HPA exporter (Prometheus metrics).

### R-V14-11: Leak prevention обязательно
- `TaskRegistry` для всех `asyncio.create_task` (auto-cancel в shutdown).
- `Watchdog` с `deadline_seconds` для long-running tasks.
- Connection pool health-check + idle-timeout + max-lifetime.
- AI workspace TTL cleanup (7 дней) + size quota per tenant.
- Все temp-files через `tempfile.TemporaryDirectory`.

### R-V14-12: Универсальная формула роута
Каждый route = `route.toml` (manifest) + один или несколько `*.dsl.yaml` с массивом `steps[]`. Каждый step произвольного типа (proxy/redirect/call_function/dispatch_action/transform/choice/parallel/try_catch/saga/invoke_workflow/policy/db_query_external/publish_event/notify_cascade/audit). **Несколько однотипных операций подряд разрешены.**

---

## Memory rules (V10 #13)

После каждой Wave (Sprint) — обязательная memory note:

1. `make wave-memory NAME=<slug> [TYPE=feedback|project]` — создаёт скелет.
2. Заполнить три секции: рулу/факт, **Why** (incident / measurement / стейкхолдер), **How to apply** (когда применять).
3. Добавить запись в коммит Wave (или отдельный `[wave:X.Y/memory]`).

Что записывать:
- неожиданные взаимозависимости;
- архитектурные ходы, сэкономившие миграционный объём;
- решения, расходящиеся с интуитивным первым ответом, и почему.

Что НЕ записывать:
- описание кода (находится grep'ом / git blame);
- эфемерное состояние таска;
- факты, которые верны "сегодня" и устареют через спринт.

---

## Pre-step initialization ritual

Перед началом любого шага плана:

```bash
graphify update . && \
cat .claude/DECISIONS.md .claude/KNOWN_ISSUES.md && \
python tools/checks/check_layers.py
```

---

## Файлы правил (`@include`)

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

---

## Ссылки

- **`PLAN.md`** — главный roadmap (V14 FINAL, ~3000 строк, 42 раздела)
- **`/root/.claude/plans/foamy-puzzling-dragonfly.md`** — полный аналитический GAP-анализ
- **`ARCHITECTURE.md`** — карта архитектуры (требует обновления после Wave 12)
- **`.claude/CONTEXT.md`** — оперативная сводка
- **`.claude/DECISIONS.md`** — устойчивые решения
- **`.claude/KNOWN_ISSUES.md`** — открытый техдолг
- **`vault/session-*-summary.md`** — архив сессий

---

*Версия CLAUDE.md синхронизирована с PLAN.md V14 (2026-05-05). При обновлении PLAN.md обновлять этот документ синхронно.*