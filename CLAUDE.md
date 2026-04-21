# CLAUDE.md — Knowledge Graph `gd_integration_tools`

<!--
============================================================
META-ИНСТРУКЦИЯ ДЛЯ CLAUDE (чтобы помнить при каждой сессии)
============================================================
Назначение этого файла:
  * Единый граф знаний о проекте — первый источник правды при каждом обращении.
  * Claude Code загружает CLAUDE.md автоматически в контекст сессии.
  * Целевая аудитория: junior-разработчики, которым передают проект
    на сопровождение и доработку.

Правила поддержки файла:
  1. ПРИ КАЖДОМ ОБРАЩЕНИИ к проекту — сперва прочитать этот файл целиком.
  2. ПРИ ЗНАЧИМОМ ИЗМЕНЕНИИ структуры (новый модуль, архитектурная правка,
     замена библиотеки, удаление/добавление процессора) — перезаписать
     соответствующую секцию, чтобы файл оставался актуальным.
  3. Не разрастаться: при добавлении новой секции подумать, не стоит ли
     устаревшую удалить. Максимум ~800 строк.
  4. Все упоминания файлов — с относительными путями от корня репо
     (`src/dsl/builder.py`, а не `/home/user/.../src/...`).
  5. При обновлении — сохранять структуру секций (нумерация + заголовки).

История версий в хвосте файла (секция "## История изменений").
============================================================
-->

## 0. Обзор

`gd_integration_tools` — банковская интеграционная платформа на Python 3.14 / FastAPI
с декларативным Camel-подобным DSL. Обеспечивает унифицированную маршрутизацию
бизнес-операций (заказы, пользователи, внешние API, AI-пайплайны) через конвейер
процессоров.

**Стек:** Python 3.14 (+3.14 free-threading compat) · FastAPI · SQLAlchemy 2.0 async
· asyncpg · Alembic · Pydantic v2 · svcs (DI) · tenacity · aiocircuitbreaker ·
httpx (HTTP/2) · FastStream (Kafka/RabbitMQ) · aiomqtt · aioimaplib · Granian (prod
ASGI) / uvicorn (dev) · uvloop · msgspec · Qdrant + fastembed (RAG) · OPA + Casbin
(policy) · OpenTelemetry · Prometheus · Sentry · structlog · argon2-cffi · Vault
(hvac) · Strawberry GraphQL · gRPC · aio-pika · aiokafka · Prefect · APScheduler
· polars (+ legacy pandas) · Streamlit.

**Язык документации:** русский.

**Принципы:** см. `docs/adr/ADR-001` (DSL central abstraction), `ADR-002` (svcs
единый DI), `ADR-005` (tenacity-only retry), `ADR-009` (httpx заменяет aiohttp),
`ADR-014` (qdrant+fastembed RAG stack). Всего 21 ADR.

## 1. Текущий статус

- **40/40 фаз** (A1..O1) закрыты в `docs/adr/PHASE_STATUS.yml` и `docs/PROGRESS.md`.
- **Текущая ветка:** `claude/production-readiness-review-N3J2h` (HEAD `67a011f`).
- Проект в состоянии **«исходная точка для дальнейшей production-доводки»** —
  не «всё готово». Предстоит постепенная доводка под реальные нужды заказчика.

**Известные gap-ы (не закрыты по DoD):**

1. **B1 phase-2** — `src/dsl/builder.py` = 1313 LOC (god-object). По DoD требовалась
   декомпозиция на 11 файлов ≤300 LOC. Физический разнос отложен (требует smoke-
   окружения заказчика; без тестов риск регрессии высокий). Mixin-маркеры в
   `src/dsl/builders/__init__.py` работают через re-export `_BuilderImpl`.
2. **H1 docs gap** — из 8 обязательных русскоязычных документов создано 2:
   `docs/DSL_COOKBOOK.md`, `docs/DEPRECATIONS.md`. Отсутствуют: `RUNBOOK.md`,
   `SECURITY.md`, `SCALING.md`, `ROLLOUT.md`, `TROUBLESHOOTING.md`, `CONTRIBUTING.md`.
3. **H3_PLUS (deferred до 2026-07-01)** — физическое удаление legacy зависимостей:
   `aiohttp` (1 вхождение в `http.py`), `pandas` (~10 вхождений), `zeep` (2+2 в
   `soap.py` и `soap_adapter.py`). Cooldown-коммит `[phase:H3+] remove deprecated`
   запланирован на follow-up.

## 2. Политика тестирования

**Тесты отсутствуют по явному требованию заказчика.** Пишутся только production-
код + статический анализ (ruff/mypy/bandit/creosote).

Hard-block на тесты:
- Pre-commit hook `tools/check_no_tests.py` — блокирует `tests/`, `test_*.py`,
  `conftest.py`, импорты `pytest|hypothesis|mutmut|testcontainers|pact|pytest_asyncio`.
- CI job `no-tests-gate` (внутри stage `regression-grep`) дублирует проверку.

Валидация — только статикой + ручные smoke на стороне заказчика в stage-окружении.

## 3. Архитектура — 5 слоёв

```
┌──────────────────────────────────────────────────────────────────┐
│ ENTRYPOINTS           (src/entrypoints/)                         │
│   REST · GraphQL · gRPC · WebSocket · SSE · SOAP · MQTT ·        │
│   Email(IMAP) · Webhook · CDC · FileWatcher · MCP · Streamlit ·  │
│   IoT · Web3 · Legacy · Enterprise                               │
└────────────────────────────┬─────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────┐
│ DSL (integration layer)   (src/dsl/)                             │
│   RouteBuilder → Pipeline → Exchange → ExecutionEngine           │
│   + 158 processors в 23 файлах (EIP, AI, RPA, Streaming, ...)    │
└────────────────────────────┬─────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────┐
│ SERVICES (business logic) (src/services/)                        │
│   core/ (orders/users/admin/tech) · ai/ · io/ · ops/ ·           │
│   integrations/                                                  │
└────────────────────────────┬─────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────┐
│ INFRASTRUCTURE (cross-cutting) (src/infrastructure/)             │
│   database · clients · eventing · resilience · observability ·   │
│   policy · ai · api_management · scheduler · datalake            │
└────────────────────────────┬─────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────┐
│ CORE (foundations)        (src/core/)                            │
│   config · svcs_registry (DI) · errors · security · tenancy ·    │
│   providers_registry · plugin_loader                             │
└──────────────────────────────────────────────────────────────────┘
```

Импортные зависимости — только сверху вниз (entrypoints могут импортировать всё
ниже себя; core никого сверху не импортирует). Нарушения ловит `pydeps` (dev-dep).

## 4. Верхнеуровневая карта `src/`

| Каталог | Роль |
|---|---|
| `core/` | Config (`Settings`), DI (`svcs_registry`), errors, security, tenancy |
| `dsl/` | RouteBuilder, Exchange, Pipeline, 158 процессоров, engine, adapters, codec, transform, helpers, commands |
| `entrypoints/` | Все точки входа (REST/GraphQL/gRPC/WS/SSE/SOAP/MQTT/Email/Webhook/CDC/FileWatcher/MCP/Streamlit) |
| `infrastructure/` | БД, клиенты, eventing, resilience, observability, policy, AI, api_management, secrets |
| `services/` | Бизнес-сервисы: core (orders/users/admin/tech/system) + ai + io + ops + integrations |
| `schemas/` | Pydantic request/response модели (route_schemas, filter_schemas) |
| `utilities/` | Утилиты общего назначения |
| `tools/` | Не путать с `/tools/` в корне: внутренние CLI (scaffold и т.п.) |
| `workflows/` | Prefect workflows (если используется) |
| `static/` | Статические ресурсы фронтенда |

## 5. Data flow — от HTTP-запроса до ответа

```
HTTP-запрос
  ↓
[Middleware stack, 4 слоя — см. секцию 16]
  ↓
FastAPI router  →  dependency injection (TenantContext, auth)
  ↓
Endpoint handler (src/entrypoints/api/v1/endpoints/<resource>.py)
  ↓
ActionHandlerRegistry.dispatch(command)   ← единый диспатчер для
  │                                         REST/gRPC/GraphQL/WS/SOAP/MCP
  ├─→ Pydantic validation (payload_model)
  ├─→ service_getter() → call service.method(...)
  │     └─→ Repository → AsyncSession → SQLAlchemy → PostgreSQL
  │     └─→ External client (httpx/grpc/kafka/…) через svcs DI
  │     └─→ (опционально) DSL Pipeline execution:
  │           RouteRegistry.get(route_id) → ExecutionEngine.execute()
  │             → Processor 1 → Processor 2 → … → Processor N
  │             (каждый процессор мутирует Exchange)
  ↓
Response (Pydantic → JSON/Protobuf/GraphQL result)
  ↓
SLO tracker (p99 latency, error rate) + Prometheus metrics
  ↓
OTEL span completion + structlog
```

## 6. Top-10 heavy importers (по частоте импорта из других модулей)

1. `app.infrastructure.clients.storage.redis` (46) — кэш, очереди, lock.
2. `app.core.config.settings` (46) — глобальный Settings.
3. `app.dsl.engine.processors.base` (40) — `BaseProcessor`.
4. `app.dsl.engine.exchange` (40) — `Exchange`, `Message`.
5. `app.dsl.engine.context` (34) — `ExecutionContext`.
6. `app.dsl.commands.registry` (32) — `ActionHandlerRegistry`.
7. `app.infrastructure.external_apis.logging_service` (27) — `app_logger`.
8. `app.core.errors` (21) — domain exceptions.
9. `app.schemas.invocation` (19) — request/response модели.
10. `app.dsl.builder` (11) — `RouteBuilder`.

**Вывод:** ядро проекта опирается на Redis + DSL engine + Settings +
ActionRegistry. Любое изменение этих пяти узлов затрагивает всё.

## 7. Ключевые концепции DSL

### 7.1 `Exchange` · `src/dsl/engine/exchange.py`

Контейнер данных, движущийся по DSL-маршруту. Generic `Exchange[T]`.

Поля:
- `in_message: Message[T]` — входное сообщение (`body` + `headers`).
- `out_message: Message[Any] | None` — выход (если процессор задал).
- `properties: dict[str, Any]` — runtime-контекст между процессорами.
- `meta: ExchangeMeta` — `exchange_id`, `route_id`, `correlation_id`, `source`.
- `status: ExchangeStatus` — `pending | processing | completed | failed | stopped`.

Методы: `complete()`, `fail(exc)`, `stop()`, `clone()` (для параллельного fan-out).

### 7.2 `Message` · там же

Generic `Message[T]` с полями `body: T`, `headers: dict[str, Any]`.

### 7.3 `RouteBuilder` · `src/dsl/builder.py` (1313 LOC, 170 методов)

Fluent-builder для описания маршрутов:

```python
from app.dsl.builder import RouteBuilder

route = (
    RouteBuilder.from_("orders.create", source="internal:orders")
    .validate(OrderCreateSchema)
    .dispatch_action("orders.create")
    .log()
    .build()
)
```

Точка входа: `.from_(route_id, source, description)`. Завершение: `.build()` →
`Pipeline`. Mixin-маркеры (phase-1): `src/dsl/builders/__init__.py` экспортирует
`CoreMixin / EIPMixin / TransportMixin / StreamingMixin / AIMixin / RPAMixin /
BankingMixin / BankingAIMixin / StorageMixin / SecurityMixin / ObservabilityMixin`
через re-export `_BuilderImpl`. Физическая декомпозиция (≤300 LOC/файл) отложена
в B1 phase-2.

### 7.4 `Pipeline` · `src/dsl/engine/pipeline.py`

Скомпилированный маршрут: `route_id`, `source`, `processors: list[BaseProcessor]`,
`protocol`, `transport_config`, `feature_flag` (можно выключать без рестарта).

### 7.5 `BaseProcessor` · `src/dsl/engine/processors/base.py`

Интерфейс всех 158 процессоров:

```python
class BaseProcessor:
    async def process(
        self,
        exchange: Exchange[Any],
        context: ExecutionContext,
    ) -> None: ...
```

Адаптеры: `CallableProcessor` (обычные функции), `SubPipelineExecutor` (вложенные
маршруты), `run_sub_processors()` (цикл с проверкой stopped/failed).

### 7.6 `ExecutionContext` · `src/dsl/engine/context.py`

Runtime-контекст маршрута: `route_id`, `state: dict`, `action_registry`,
`request_id`, OTEL `span`, `logger`. Shared между всеми процессорами одного
Pipeline-запуска.

### 7.7 `ActionHandlerRegistry` · `src/dsl/commands/registry.py`

Единый диспатчер бизнес-действий (используется всеми протоколами: REST, gRPC,
GraphQL, WebSocket, SOAP, MCP). Обеспечивает консистентность логики.

```python
@dataclass
class ActionHandlerSpec:
    action: str                                   # "orders.create"
    service_getter: Callable[[], Any]             # фабрика сервиса
    service_method: str                           # имя метода
    payload_model: type[BaseModel] | None         # Pydantic-валидация
```

Методы: `register / register_many / dispatch(command) / is_registered /
list_actions / clear`.

### 7.8 `RouteRegistry` · `src/dsl/registry.py`

Хранилище `route_id → Pipeline`. Методы: `register / get / is_registered /
list_routes / list_enabled_routes / toggle_feature_flag`.

### 7.9 `ExecutionEngine` · `src/dsl/engine/execution_engine.py`

Синхронный runner Pipeline. Итерирует `processors`, применяет middleware
(Timeout/ErrorNormalizer/Metrics), управляет `ExchangeStatus`. Для streaming —
отдельный runner в `src/dsl/engine/processors/streaming/`.

## 8. Каталог процессоров (158 классов, 23 файла)

Все файлы внутри `src/dsl/engine/processors/`. Ниже — категории и самые важные
классы с однострочным пояснением. Полный перечень — в `docs/PROCESSORS.md` (если
есть) и в коде.

### 8.1 Control Flow · `control_flow.py`

- `ChoiceProcessor` — `when/otherwise` ветвление по предикатам.
- `TryCatchProcessor` — `try/catch/finally` с восстановлением Exchange.
- `RetryProcessor` — ретраи через `tenacity.AsyncRetrying` (exponential/fixed).
- `PipelineRefProcessor` — вызов другого DSL-маршрута по `route_id`.
- `ParallelProcessor` — параллельные ветки (`strategy: all | first`).
- `SagaProcessor` + `SagaStep` — Saga с компенсациями при откате.

### 8.2 Core · `core.py`

- `SetHeaderProcessor`, `SetPropertyProcessor` — мутации `headers`/`properties`.
- `DispatchActionProcessor` — Camel Service Activator, вызов action из
  `ActionHandlerRegistry`.
- `TransformProcessor` — JMESPath трансформация `body`.
- `FilterProcessor` — Message Filter (пропуск при predicate=False).
- `EnrichProcessor` — Content Enricher (добавление данных без изменения body).
- `LogProcessor` — логирование состояния Exchange.
- `ValidateProcessor` — Pydantic-валидация с остановкой на ошибке.

### 8.3 Patterns (n8n / Benthos / Zapier) · `patterns.py`

- `SwitchProcessor` — n8n Switch: маршрутизация по значению поля.
- `MergeProcessor` — объединение properties (`append | merge | zip`).
- `BatchWindowProcessor` — Benthos time-window (`max_size | window_seconds`).
- `DeduplicateProcessor` — дедуп в скользящем окне.
- `FormatterProcessor` — Zapier-style подстановка из `body + properties`.
- `DebounceProcessor` — группировка повторов, пропуск старых.

### 8.4 EIP · `eip/` (6 файлов)

**`flow_control.py`** (6): `WireTapProcessor`, `ThrottlerProcessor` (token bucket),
`DelayProcessor`, `AggregatorProcessor` (по `correlation_id`), `LoopProcessor`,
`OnCompletionProcessor`.

**`routing.py`** (5): `DynamicRouterProcessor` (runtime-вычисление route_id),
`ScatterGatherProcessor`, `RecipientListProcessor`, `LoadBalancerProcessor`
(`round_robin | random | weighted | sticky`), `MulticastProcessor`.

**`resilience.py`** (4): `DeadLetterProcessor` (DLQ в Redis stream),
`FallbackChainProcessor`, `CircuitBreakerProcessor` (CLOSED/OPEN/HALF_OPEN),
`TimeoutProcessor`.

**`sequencing.py`** (2): `ResequencerProcessor`, `SortProcessor`.

**`transformation.py`** (3): `SplitterProcessor` (array → Exchange per item),
`MessageTranslatorProcessor`, `ClaimCheckProcessor` (store/retrieve через Redis).

**`idempotency.py`** (1): `IdempotentConsumerProcessor` (Redis SET NX EX).

### 8.5 AI / ML · `ai.py` (12 классов)

- `PromptComposerProcessor` — построение промпта из template + контекста.
- `LLMCallProcessor` — chat-completion с retry/rate-limit/cost tracking.
- `LLMParserProcessor` — парсинг ответа в JSON/Pydantic.
- `TokenBudgetProcessor` — обрезка по tiktoken.
- `VectorSearchProcessor` — RAG top-K из `QdrantVectorStore`.
- `SanitizePIIProcessor` / `RestorePIIProcessor` — маскировка/восстановление PII
  через Presidio (перед/после LLM).
- `LLMFallbackProcessor` — цепочка провайдеров (Claude → OpenAI → Ollama).
- `CacheProcessor` / `CacheWriteProcessor` — semantic cache через Redis.
- `GuardrailsProcessor` — safety checks (длина, blocklist, required fields).
- `SemanticRouterProcessor` — RAG-based intent detection → выбор маршрута.

### 8.6 RPA · `rpa.py` (16 классов)

PDF: `PdfReadProcessor`, `PdfMergeProcessor`. Word: `WordReadProcessor`,
`WordWriteProcessor`. Excel: `ExcelReadProcessor`. Files: `FileMoveProcessor`,
`ArchiveProcessor` (ZIP/TAR). OCR: `ImageOcrProcessor` (Tesseract). Images:
`ImageResizeProcessor`. Text: `RegexProcessor`, `TemplateRenderProcessor` (Jinja2),
`HashProcessor` (MD5/SHA256), `EncryptProcessor`/`DecryptProcessor` (AES-256).
System: `ShellExecProcessor` (sandbox). Email: `EmailComposeProcessor`.

### 8.7 Web Automation · `web.py` (6)

`NavigateProcessor`, `ClickProcessor`, `FillFormProcessor`, `ExtractProcessor`,
`ScreenshotProcessor`, `RunScenarioProcessor` (multi-step) — поверх Playwright.

### 8.8 Streaming / Windowing · `streaming.py` (12)

- `MessageExpirationProcessor` — TTL на сообщение (drop/skip/log).
- `CorrelationIdProcessor` — пропагация correlation-id.
- `TumblingWindowProcessor`, `SlidingWindowProcessor`, `SessionWindowProcessor`.
- `GroupByKeyProcessor` — агрегация по ключу в окне.
- `SchemaRegistryValidator` — Avro / JSON Schema валидация.
- `ReplyToProcessor` — request-reply поверх очередей.
- `ExactlyOnceProcessor` — dedup через storage + outbox.
- `DurableSubscriberProcessor` — persistent fan-out.
- `ChannelPurgerProcessor` — очистка DLQ/стримов.
- `SamplingProcessor` — вероятностный сэмплинг (A/B, canary).

### 8.9 Data Quality · `dq_check.py`

`DQCheckProcessor` — правила not_null / range / regex / unique.

### 8.10 Integration · `integration.py`

- `EventPublishProcessor` — публикация через `EventBus`.
- `MemoryLoadProcessor` / `MemorySaveProcessor` — Agent conversation memory.

### 8.11 Business Domain · `business.py` + `ai_banking.py` + `banking.py` + `rpa_banking.py`

~19 процессоров: KYC/AML верификация, anti-fraud scoring, credit scoring (RAG),
bank statement OCR, TX categorization, customer chatbot, appeal AI agent, shadow
mode, keystroke replay, Backfill, DryRun.

### 8.12 Components (HTTP / DB / Files / S3 / Timers) · `components.py`

- `HttpCallProcessor` — GET/POST/PUT/DELETE через httpx.
- `DatabaseQueryProcessor` — SQL с валидацией.
- `FileReadProcessor` / `FileWriteProcessor` — локальные файлы.
- `S3ReadProcessor` / `S3WriteProcessor` — AWS S3 / MinIO.
- `TimerProcessor` — scheduled events (`interval | cron`).
- `PollingConsumerProcessor` — периодический вызов action.

### 8.13 Converters · `converters.py`

`ConvertProcessor` — JSON ↔ YAML / XML / CSV / msgpack / parquet / BSON.

### 8.14 Scraping · `scraping.py`

`ScrapeProcessor` (CSS selectors + SSRF-защита), `PaginateProcessor` (multi-page),
`ApiProxyProcessor` (прозрачный proxy).

### 8.15 Export & Notify · `export.py`

`ExportProcessor` — CSV/Excel/PDF/JSON/Parquet из `list[dict]`.

### 8.16 Прочее

- `CDCProcessor` — Change Data Capture (polling / listen_notify / logminer).
- `MCPToolProcessor` — Model Context Protocol tool integration.
- `AgentGraphProcessor` — LangGraph agents.
- `NormalizerProcessor` — auto-detection формата.
- `External`, `Storage`, `ML Inference` — специализированные домены.

### 8.17 Top-25 методов `RouteBuilder`

**Инициализация:**
`.from_(route_id, source, description)` — точка входа.

**Core:**
`.dispatch_action(action, payload_factory, result_property)` · `.process(p)` ·
`.to(p)` · `.log(level)` · `.transform(expr)` · `.filter(predicate)` ·
`.validate(model)`.

**Control flow:**
`.choice(when, otherwise)` · `.do_try(try, catch, finally)` ·
`.retry(processors, max_attempts, delay, backoff)` · `.saga(steps)` ·
`.parallel(branches, strategy)`.

**EIP:**
`.dynamic_route(expr)` · `.scatter_gather(route_ids, agg, timeout)` ·
`.circuit_breaker(processors, threshold, recovery)` ·
`.dead_letter(processors, dlq_stream)`.

**AI pipeline:**
`.call_llm(provider, model)` · `.rag_search(query_field, top_k, namespace)` ·
`.parse_llm_output(schema)`.

**Infrastructure:**
`.http_call(url, method, headers, auth, timeout)` · `.db_query(sql, prop)` ·
`.read_s3(bucket, key)` / `.write_s3(bucket, key)`.

**Build / config:**
`.build(validate_actions)` · `.feature_flag(name)` · `.protocol(proto)`.

## 9. DI-контейнер (`svcs`) · `src/core/svcs_registry.py`

ADR-002: единственный источник DI в проекте. `service_registry.py` — deprecation
shim (`DeprecationWarning`, удаление после 2026-07-01), `_FallbackRegistry` убран.

Архитектура:
- Глобальный `registry: svcs.Registry()`.
- Кэш синглтонов: `_singletons: dict[Hashable, Any]`.

API:
```python
from app.core.svcs_registry import register_factory, get_service

register_factory("orders", get_order_service)        # по имени
register_factory(OrderService, get_order_service)     # по типу (тот же singleton)

svc = get_service("orders")       # str lookup
svc = get_service(OrderService)   # type lookup
```

Где регистрируются сервисы: `src/infrastructure/application/lifecycle.py ::
register_all_services()` (вызывается в FastAPI startup). Типичные ключи:
`orders`, `users`, `orderkinds`, Redis, Postgres, Kafka, SMTP, SFTP, PromptRegistry,
SemanticCache, VectorStore, RateLimit, CircuitBreaker.

## 10. Конфигурация · `src/core/config/`

`Settings` (pydantic-settings) — глобальный объект конфига, импортируется как
`from app.core.config.settings import settings`.

Секции:
- `app: AppBaseSettings` — host, port, debug, environment, version, telemetry_enabled.
- `secure: SecureSettings` — API keys, `cors_origins` (validator запрещает `"*"` в
  prod — ADR-003), allowed_hosts, 2FA.
- `database: DatabaseConnectionSettings` — PostgreSQL DSN + pool.
- `mongo: MongoConnectionSettings`.
- `redis: RedisSettings` — cache, queue, session.
- `queue: QueueSettings` — RabbitMQ/Kafka broker_url.
- `tasks: TasksSettings` — Celery/FastStream timeout, retry.
- `mail: MailSettings` — SMTP.
- `clickhouse`, `elasticsearch` — OLAP.
- `scheduler: SchedulerSettings` — APScheduler.
- `grpc: GRPCSettings`.
- `storage: FileStorageSettings` — S3/GCS.
- `antivirus`, `skb_api`, `dadata_api` — внешние интеграции.

Источники:
- `.env` файлы (pydantic-settings авто).
- `config.yml` (если загружен вручную).
- **Vault** через `VaultSecretRefresher` — watcher-refresh секретов в runtime.
- `runtime_state.py` — feature-flags (`disabled_feature_flags`).

## 11. База данных · `src/infrastructure/database/`

### 11.1 Модели · `models/`

Базовый класс `BaseModel` (`base.py`) — AsyncAttrs + SQLAlchemy Base +
SQLAlchemy-Continuum (ActivityPlugin) для аудита всех изменений. Автополя: `id`,
`created_at`, `updated_at`. Именование таблиц: `{ClassName.lower()}s`.

| Модель | Таблица | Ключевые поля |
|---|---|---|
| `User` (`users.py`) | `users` | `username` (UNIQUE), `email` (UNIQUE), `password` (argon2), `is_active`, `is_superuser` |
| `Order` (`orders.py`) | `orders` | `order_kind_id` (FK), `pledge_gd_id`, `object_uuid`, `response_data` (JSON), флаги `is_send_to_gd`/`is_send_request_to_skb` |
| `OrderKind` (`orderkinds.py`) | `orderkinds` | `name`, `description`, `skb_uuid` (UNIQUE) |
| `File` (`files.py`) | `files` | `name`, `object_uuid` |
| `OrderFile` (`files.py`) | `orderfiles` | композитный PK `(order_id, file_id)` |
| `OutboxMessage` (`outbox.py`) | `outbox_messages` | `topic`, `payload`, `status`, `retry_count`, `next_attempt_at` (exclude versioning) |

`User.set_password()` / `verify_password()` используют argon2-cffi
(`PasswordHasher`, OWASP-параметры) — ADR-003. Замена `passlib` по фазе A2.

### 11.2 Миграции Alembic · `migrations/versions/`

Последняя: `2026_04_20_1200-a1b2c3d4e5f6_add_outbox_messages.py`.
Команда применения: `make migrate` → `python manage.py migrate`.

### 11.3 Session manager · `session_manager.py`

`DatabaseSessionManager`:
- `create_session()` — context manager `AsyncSession`.
- `transaction()` — commit/rollback wrapper.
- `get_session()` / `get_transaction_session()` — FastAPI-совместимые
  dependency-генераторы.
- `connection(isolation_level=None, commit=True)` — декоратор для сервисов:
  прокидывает `session=...` аргументом, авто-commit/rollback.

Доступ:
```python
# Через Depends:
async def handler(session: AsyncSession = Depends(main_session_manager.get_session)): ...

# Через декоратор:
@main_session_manager.connection(commit=True)
async def service_method(self, session: AsyncSession): ...
```

Внешние БД — `get_external_session_manager(profile_name)` поверх
`external_db_registry`.

### 11.4 Tenant filter · `tenant_filter.py`

`TenantMixin` добавляет колонку `tenant_id: Mapped[str]` (STRING 64, indexed,
default="default"). `apply_tenant_filter(session_factory)` регистрирует два
SQLAlchemy event listener'а:
1. `do_orm_execute` (before SELECT) — автоматически добавляет
   `WHERE entity.tenant_id = :current_tenant` (из contextvar).
2. `before_flush` — проставляет `tenant_id` новым объектам из контекста.

Результат: прозрачное row-level isolation без явных фильтров.

### 11.5 Репозитории · `src/infrastructure/repositories/`

`AbstractRepository[T]` (`base.py`) — интерфейс CRUD + версионирование.
`SQLAlchemyRepository[T]` — базовая реализация поверх AsyncSession с поддержкой
fastapi-filter и fastapi-pagination. Специализации: `users.py`, `orders.py`,
`orderkinds.py`, `files.py`, `outbox.py`. Принцип: **Сервис → Repo → AsyncSession
→ SQLAlchemy → БД**.

## 12. Бизнес-сервисы · `src/services/`

### 12.1 Core (`services/core/`)

Базовый класс `BaseService[Repo, ResponseSchema, RequestSchema, VersionSchema]`
(`base.py`). CRUD-методы: `add`, `add_many`, `get` (с filter/pagination),
`update`, `delete`, `get_or_add`, `get_all_object_versions`,
`get_latest_object_version`, `restore_object_to_version`. Все методы поддерживают
response-cache через `@response_cache` с инвалидацией при mutation.

| Файл | Сервис | Роль |
|---|---|---|
| `orders.py` | `OrderService` | orders + file_repo + request_service (SKB) + s3_service; `create_skb_order`, `_get_order_data`, `_invalidate_cache` |
| `users.py` | `UserService` | `add` (anti-dup), `login` (password verify) |
| `orderkinds.py` | `OrderKindService` | стандартный CRUD |
| `admin.py` | `AdminService` | `get_config`, `toggle_route`, feature-flags, cache management |
| `tech.py` | `TechService` | healthchecks (DB/Redis/S3/RabbitMQ), mass-upload из Excel |
| `system.py` | `SystemService` | unified фасад (Tech + Admin), lazy-loading |

### 12.2 AI (`services/ai/`)

`ai_agent.py` (reasoning), `ai_providers.py` (Claude/OpenAI/Ollama адаптеры),
`ai_graph.py` (LangGraph workflows), `rag_service.py`, `hybrid_rag.py`
(lexical+semantic), `agent_memory.py`, `prompt_registry.py`, `ai_moderation.py`,
`llm_judge.py`, `semantic_cache.py`.

### 12.3 IO (`services/io/`)

`export_service.py` — unified `export(data, format)` для CSV (RFC 4180), XLSX
(openpyxl), PDF, JSON, Parquet. `dataframe.py`, `files.py`, `search.py`,
`external_database.py` (Oracle/Postgres/MySQL), `web_automation.py`.

### 12.4 Ops (`services/ops/`)

`analytics.py`, `notification_hub.py` + `notification_adapters.py` (email / Slack
/ webhook), `data_quality.py`, `message_replay.py`, `webhook_scheduler.py`,
`anomaly_detector.py`, `scheduled_reports.py`.

### 12.5 Integrations (`services/integrations/`)

Адаптеры для внешних сервисов (dadata, SKB, Yandex, Sber API и пр.).

## 13. Schemas · `src/schemas/`

Соглашение об именах:
- `{Model}SchemaIn` — входная (validation на create/update).
- `{Model}SchemaOut` — выходная (serialization).
- `{Model}VersionSchemaOut` — для audit-trail (с `operation_type`, `transaction_id`).
- `{Model}Filter` — query-параметры через fastapi-filter.

Базовая `BaseSchema` (`base.py`): `model_config = ConfigDict(from_attributes=True)`.

Пример: `route_schemas/orders.py` — `OrderSchemaIn`, `OrderSchemaOut` (+ relation
`order_kind`, `files`), `OrderVersionSchemaOut`. `filter_schemas/orders.py` —
фильтры для `GET /order`.

## 14. Резильенс-примитивы · `src/infrastructure/resilience/`

Пакет добавлен в A4 (ADR-005). Все примитивы доступны как DSL-методы
`RouteBuilder` и как standalone-classes для прямого использования в сервисах.

- `bulkhead.py` — `Bulkhead(name, max_concurrent, wait_timeout)` на anyio
  semaphore. Исключение: `BulkheadExhausted`. DSL: `.bulkhead(name, limit, processors)`.
- `time_limiter.py` — адаптивный timeout по EWMA p95/p99.
- `retry_budget.py` — не более N% ретраев от общего трафика (anti-amplification).
  DSL: `.retry(processors, max_attempts, delay, backoff)`.
- `rate_limiter.py` — `ResourceRateLimiter` (token bucket) per resource
  (http/grpc/kafka/mqtt/ws). DSL: `.throttle(rate, burst)`.
- `circuit_breaker.py` — CLOSED/OPEN/HALF_OPEN state machine. DSL:
  `.circuit_breaker(processors, threshold, recovery, fallback_processors)`.

`RetryProcessor` (`src/dsl/engine/processors/control_flow.py:163`) — обёртка над
`tenacity.AsyncRetrying` (ADR-005). Кастомного retry-цикла больше нет.

## 15. Eventing · `src/infrastructure/eventing/`

### 15.1 CloudEvents · `cloudevents.py` (ADR-010)

Стандартный envelope CloudEvents 1.0: `specversion`, `type`, `source`, `id`,
`time`, `subject`, `datacontenttype`, `data`. Все Kafka/RabbitMQ события
оборачиваются.

### 15.2 Schema Registry · `schema_registry.py`

JSON Schema + Avro (fastavro). Валидация на produce/consume. Dev-fallback —
локальный кэш схем.

### 15.3 Outbox · `outbox.py` (ADR-011)

Transactional Outbox для exactly-once:
1. В одной транзакции SQL-commit + insert в `outbox_messages`.
2. Background worker (polling или LISTEN/NOTIFY) читает unpublished.
3. Публикует в Kafka/Rabbit через FastStream.
4. Помечает `published_at`.

Dataclass `OutboxEvent` — `id, aggregate_type, aggregate_id, event_type, payload,
headers, created_at, published_at, attempts`.

### 15.4 Inbox · `inbox.py`

Deduplication processed event IDs в Redis (SETNX+TTL). API: `seen_or_mark(id) →
bool` (True если уже обработано).

### 15.5 FastStream broker · `src/infrastructure/clients/messaging/` (ADR-013)

Унификация Kafka + RabbitMQ через FastStream. AsyncAPI автогенерация из
route-метаданных. `event_bus.py` — мультиплексор pub/sub для внутренних каналов.

## 16. Observability

### 16.1 OpenTelemetry

`src/infrastructure/observability/tracing.py` + `src/infrastructure/application/
telemetry.py`. В startup: `if settings.app.telemetry_enabled: setup_tracing(app)`.
`TracingMiddleware` создаёт span `dsl.processor.{name}` c атрибутами:
`dsl.route_id`, `dsl.processor`, `correlation_id`, `exchange_id`, `tenant_id`
(через OTEL Baggage).

### 16.2 Prometheus

`src/infrastructure/observability/metrics.py`. `MetricsMiddleware` в pipeline-
execution (latency/status). `PrometheusMiddleware` в FastAPI stack (HTTP
metrics). `prometheus-fastapi-instrumentator` — базовые HTTP-метрики.
`starlette-exporter` помечен deprecated (H3_PLUS).

### 16.3 Sentry

`src/infrastructure/observability/sentry_init.py` — `sentry_sdk.init(dsn=...)` в
startup. Теги per tenant.

### 16.4 structlog

`src/infrastructure/logging/factory.py`. Бэкенды: stdlib + JSON-формат. Контекст:
`correlation_id`, `request_id`, `tenant_id` — через contextvars.

### 16.5 PII filter

`src/infrastructure/observability/pii_filter.py` — маскирует email / phone /
СНИЛС / карточные номера в логах (добавлен в G3).

## 17. Multi-tenancy · `src/core/tenancy/`

`TenantContext(tenant_id, plan, region, rate_limit)` пропагируется через:
1. **Middleware** — читает `X-Tenant-ID`, создаёт `TenantContext`.
2. **ContextVar** `_current: ContextVar[TenantContext]`.
3. **DB** — автоматический `WHERE tenant_id = :current_tenant` через
   `tenant_filter.py` event listeners.
4. **Redis** — ключ-префикс `t:{tenant_id}:`.
5. **Logs** — добавляется в structlog context.
6. **Prometheus** — label `tenant_id` (cardinality bounded).
7. **OTEL Baggage** — распространяется в trace.

Использование:
```python
from app.core.tenancy import current_tenant, set_tenant, tenant_scope

ctx = TenantContext(tenant_id="acme-corp")
with tenant_scope(ctx):
    ...  # нижележащие слои видят текущий tenant
```

## 18. Policy · `src/infrastructure/policy/` (ADR-012)

- `opa.py` — OPA REST client. Fail-closed: при любой ошибке возвращает
  `PolicyDecision(allow=False)`. DSL: `.with_opa_policy("routes/orders/read")`.
- `casbin_adapter.py` — RBAC/ABAC поверх Casbin. Model: `policies/casbin_model.conf`.
  DSL: `.with_casbin_role("orders_reader")`.
- Policy-middleware в FastAPI stack.

## 19. AI subsystem · `src/infrastructure/ai/`

### 19.1 PromptRegistry · `prompt_registry.py`

```python
@dataclass
class PromptVersion:
    key: str
    version: str
    template: str
    weight: float = 1.0     # A/B traffic share
    enabled: bool = True
```

`registry.register(...)` · `registry.get(key)` — weighted random selection.

### 19.2 SemanticCache · `semantic_cache.py`

Redis-backed. Сейчас exact-match по hash; future — cosine similarity через
Qdrant. API: `SemanticCache(prefix, threshold, ttl_seconds)` с `.get()/.set()`.

### 19.3 VectorStore (Qdrant) · `vector_store.py` (ADR-014)

`QdrantVectorStore(url, collection)` — `upsert(points)` / `search(vector, limit)`.
Embeddings: `fastembed` (quantized ONNX, ~10x быстрее sentence-transformers).

### 19.4 DSL-интеграция AI

```python
route = (
    RouteBuilder.from_("support.chat", source="http:/...")
    .sanitize_pii()
    .rag_search(query_field="question", top_k=5)
    .compose_prompt(template="Answer: {vector_results}")
    .call_llm(provider="claude", model="opus")
    .parse_llm_output(schema=ResponseSchema)
    .restore_pii()
    .build()
)
```

## 20. API Management · `src/infrastructure/api_management/` (ADR-015)

- `api_key_auth.py` — `hash_key(raw) = sha256(raw).hexdigest()`. Хранится
  **только hash**, raw-key выдаётся пользователю один раз.
- `quotas.py` — per-consumer quotas, real-time decrement.
- `versioning.py` — `@deprecated(in_version="v2", sunset="2027-06-01")` → Sunset
  + Deprecation headers (RFC 8594).
- Developer Portal: `src/entrypoints/developer_portal/` — self-service регистрация
  apps, rotation/revocation keys, quota dashboard.
- Kill-switch через feature-flag (unleash-client).
- Usage analytics — middleware, event в Kafka/Postgres per consumer.

## 21. Точки входа (entrypoints)

Единый диспатчер для всех протоколов — `ActionHandlerRegistry.dispatch()` — это
обеспечивает, что бизнес-логика одна и та же независимо от транспорта.

### 21.1 REST API v1 · `src/entrypoints/api/v1/endpoints/`

| Файл | Префикс / Назначение |
|---|---|
| `orders.py` | `/order/*` CRUD + `POST /create-skb-order`, `POST /fetch-result` |
| `users.py` | `/user/*` |
| `health.py` | `/readiness`, `/liveness`, `/startup`, `/components` (4 K8s probes) |
| `admin.py` | `/admin/actions`, `/admin/routes`, `/admin/feature-flags`, `/admin/slo-report` |
| `orderkinds.py` | `/kind/*` (справочник видов запросов) |
| `files.py` | `/file/*` (БД), `/storage/*` (S3) |
| `dsl_console.py` | DSL-консоль: routes list, editor, debug |
| `dsl_catalog.py` | `/api/v1/dsl/*` — каталог процессоров |
| `imports.py` | `/import/*` — импорт OpenAPI/Postman |
| `dadata.py`, `skb.py`, `tech.py` | внешние интеграции |

**API Generator** · `src/entrypoints/api/generator/` — автоматическая генерация
endpoints из `ActionHandlerRegistry`:
- `actions.py` — `ActionRouterBuilder`, `CrudSpec`, `ActionSpec`.
- `registry.py` — единый dispatcher.
- `setup.py` — регистрация в startup.

Версионирование: v1/v2 с Deprecation headers (RFC 8594).

### 21.2 GraphQL · `src/entrypoints/graphql/schema.py`

Strawberry GraphQL. Корневые типы: `OrderType`, `UserType`, `FileType`,
`OrderKindType`, `DslResult`. Query + Mutation (доменные + `executeDsl`
fallback). Резолверы используют `ActionHandlerRegistry.dispatch()`.

### 21.3 gRPC · `src/entrypoints/grpc/grpc_server.py`

- `OrderGRPCServicer` — `CreateOrder`, `GetOrderResult`, `DeleteOrder`.
- Proto: `src/entrypoints/grpc/protobuf/orders_pb2.proto`.
- `_dispatch()` → `ActionHandlerRegistry`.
- Порт 50051 (по умолчанию). TLS обязателен — `_load_tls_credentials()` +
  `AuthInterceptor` (ADR-004). `add_secure_port`, НЕ `add_insecure_port`.

### 21.4 WebSocket · `src/entrypoints/websocket/`

- `ws_handler.py` — основной handler. Протокол: `{"action": route_id,
  "payload": {...}}`.
- `ws_manager.py` — управление клиентами + broadcast.
- `ws_auth.py` — аутентификация.
- `ws_broadcast.py` — рассылка сообщений по группам.
- Подписки: `{"action": "subscribe", "groups": ["topic1"]}`.

### 21.5 SSE · `src/entrypoints/sse/handler.py`

`GET /events/stream` — Server-Sent Events. Внутри `EventBus` (async queue) для
публикации из сервисов → стриминга клиентам.

### 21.6 SOAP · `src/entrypoints/soap/soap_handler.py`

`POST /soap/call` — XML SOAP envelope parsing, WSDL auto-generation, маршрутизация
через DSL или ActionRegistry. SOAP через `aiohttp-soap` (ADR-миграция из zeep —
zeep помечен deprecated, удаление в H3_PLUS).

### 21.7 MQTT · `src/entrypoints/mqtt/mqtt_handler.py`

- Client: `aiomqtt` (не paho). Подписка на топики → маршрутизация через DSL.
- Конфиг: `MqttSettings` (host, port=1883, topics, QoS).
- **mTLS обязателен** — `_build_tls_context()` настраивает SSL с client cert.
- Примеры топиков: `["gd/orders/#", "gd/events/#"]`.

### 21.8 Email (IMAP) · `src/entrypoints/email/imap_monitor.py`

- Client: `aioimaplib` (async). Монитор подписывается на папку, poll-интервал.
- Пароль — из Vault (`VaultSecretRefresher`), прямой password — только dev.
- STARTTLS enforce.
- Письма → DSL-маршрут.

### 21.9 Webhook · `src/entrypoints/webhook/`

- `POST /webhooks/subscriptions` — создать подписку (auth required).
- `DELETE /webhooks/subscriptions/{id}` — удалить.
- `POST /webhooks/inbound/{event_type}` — inbound от внешних систем.
- HMAC-SHA256 signature (`signatures.py`), rate-limit, Vault для секретов.
- `registry.py` — хранилище подписок (Redis), `handler.py` — маршрутизация.

### 21.10 CDC · `src/entrypoints/cdc/cdc_routes.py`

`POST /api/v1/cdc/subscriptions` + DELETE + GET — подписка на изменения внешней
БД (polling / listen_notify / logminer). Триггер DSL при изменениях.

### 21.11 FileWatcher · `src/entrypoints/filewatcher/`

`POST /api/v1/watchers/` + DELETE + GET. Параметры: `path`, glob-pattern,
`route_id`, `poll_interval`. Компоненты: `WatcherManager`, `WatcherSpec`.

### 21.12 MCP (Model Context Protocol) · `src/entrypoints/mcp/mcp_server.py`

FastMCP. Экспортирует 50+ actions как MCP tools. Категории:
- Action tools — автоген из ActionRegistry.
- Route tools — list / execute DSL-маршруты.
- Template tools — Pipeline-шаблоны.
- Convert tools — JSON↔XML/YAML/CSV/MsgPack.
- System tools — health, metrics, feature flags.

### 21.13 Streamlit UI · `src/entrypoints/streamlit_app/`

25 страниц в `pages/`:
- `1_Orders.py` — управление заказами.
- `2_Routes.py` — список DSL-маршрутов.
- `8_DSL_Playground.py`, `9_DSL_Visual_Editor.py` — редакторы.
- `12_DSL_Debugger.py` — дебаг маршрутов.
- `16_Processes_Dashboard.py`, `17_Realtime_Logs.py` — мониторинг.
- `19_Audit_Log.py`, `23_SQL_Admin.py` — администрирование.
- Прочее: dev-panel, analytics, dsl_graph (Mermaid).

### 21.14 Opt-in коннекторы (extras)

- `iot/` — OPC-UA, Modbus, CoAP, LoRaWAN. Extra: `gdi[iot]`.
- `web3/` — EVM JSON-RPC. Extra: `gdi[web3]`.
- `legacy/` — TN3270, TN5250, ISO8583. Extra: `gdi[legacy]`.
- `enterprise/` — AS2, EDI X12, SAP, IBM MQ, JMS, NATS, SFTP. Extra: `gdi[enterprise]`.
- `banking/` — FIX, MT/MX, EDIFACT, ISO8583, HL7. Extra: `gdi[banking]`.

Импорт без соответствующего extras → ясная ошибка `optional_feature('iot')`.

## 22. Middleware stack · `src/entrypoints/middlewares/setup_middlewares.py`

Порядок КРИТИЧЕН (FastAPI применяет в обратном — последний добавленный выполняется
первым во входящем направлении):

**Слой 1 — Early exit:**
`ExceptionHandler` → `CORSMiddleware` (origins из `settings.secure.cors_origins`,
запрет `"*"` в prod) → `TrustedHostMiddleware` → `BlockedRoutesMiddleware` →
`IPRestrictionMiddleware` → `APIKeyMiddleware`.

**Слой 2 — Request management:**
`RequestIDMiddleware` → `TimeoutMiddleware`.

**Слой 3 — Business logic:**
`ResponseCacheMiddleware` → `GZipMiddleware` → `DataMaskingMiddleware`.

**Слой 4 — Observability:**
`AuditLogMiddleware` → `AuditReplayMiddleware` → `RequestLoggingMiddleware` →
`PrometheusMiddleware`.

**Удалено:** `CircuitBreakerMiddleware` (A2, ADR-005) — global-state баг,
per-route circuit breaker теперь на клиенте.

### 22.1 Ключевые публичные endpoints

- `GET /` — стартовая страница с документацией.
- `GET /docs` — Swagger UI.
- `GET /redoc` — ReDoc.
- `GET /health` — быстрый liveness probe.
- `GET /api/v1/health/readiness` — полный readiness probe.
- `GET /api/v1/health/startup` — ждёт инициализации DSL.
- `GET /api/v1/health/components` — детальное здоровье компонентов.
- `GET /api/v1/admin/actions` — список всех actions.
- `GET /api/v1/admin/routes` — список DSL-маршрутов.
- `GET /metrics` — Prometheus метрики.

## 23. Runtime · точки входа и lifecycle

### 23.1 Сервер

```bash
make run                              # → python manage.py run
# или
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000
```

**Prod:** Granian (`granian.run()`) вместо uvicorn (ADR-006). uvicorn остаётся в
dev-extras. Runtime-flag переключает.

### 23.2 Entry point · `src/main.py`

32 строки. `create_app()` из `src/infrastructure/application/app_factory.py`
инициализирует: middleware, routers, tracing, monitoring, admin.

### 23.3 Lifecycle · `src/infrastructure/application/lifecycle.py`

**startup:**
1. `register_all_services()` — svcs_registry.
2. `register_action_handlers()` — ActionHandlerRegistry.
3. `register_dsl_routes()` — RouteRegistry.
4. `_register_protocol_providers()` — LLM, Exporter, Memory провайдеры.
5. OTEL init (если `settings.app.telemetry_enabled`).

**shutdown:**
Graceful drain (`SHUTDOWN_GRACE_SECONDS`, default 30s). Закрывает: Redis, DB
pools, HTTP clients, Kafka producers.

### 23.4 manage.py (CLI)

Typer CLI. Команды:
- `run` / `run-frontend` / `run-all`.
- `migrate` — Alembic upgrade head.
- `routes` — список DSL-маршрутов.
- `actions` — список зарегистрированных actions.
- `scaffold <type> <name>` — новый service / processor / route (boilerplate).
- `health` — ручная проверка компонентов.
- `validate` — прогон DSL-линтера.
- `breakers` — состояние circuit-breaker-ов.

## 24. Сборка и конфиги

### 24.1 `pyproject.toml`

- Poetry, Python ≥3.14,<3.15.
- **81 main deps** + **30 dev deps**.
- Extras: `ai`, `security`, `mcp`, `rpa`, `iot`, `web3`, `legacy`, `banking`,
  `enterprise`, `datalake`, `temporal`, `beam`.
- Ruff: `select = ["E", "F", "W", "I", "S"]` (S = bandit-lite). Line 88.
  target py314.
- Mypy: `sqlalchemy.ext.mypy.plugin`. Ignore: `app/entrypoints/grpc/protobuf/*`.
- Semantic-release настроен.

### 24.2 `Dockerfile` (multi-stage)

- Stage `builder` — poetry install (no dev).
- Stage `runtime` — slim + tini + appuser + health-checks.
- Expose: 8000 (HTTP), 4200 (Prefect), 50051 (gRPC).

### 24.3 `docker-compose.yml`

Сервисы: `postgres:16`, `redis:7` (+ healthchecks, volumes). Env из `.env.example`
(DB_NAME, DB_USER, API_KEY, S3 creds, Graylog endpoint). Для heavy-фаз
(Kafka/Qdrant/Vault/OPA/MinIO/Consul/Temporal) — stub-сервисы добавляются
заказчиком в stage-окружении.

### 24.4 `.gitlab-ci.yml` — 9 stages

1. `lint` — `ruff check` + `ruff format --check`.
2. `type-check` — `mypy -p app` (non-blocking baseline).
3. `security` — `bandit`, `detect-secrets`, `creosote` (allow_failure).
4. `build` — docker multi-stage + `trivy image` scan.
5. `docs` — `sphinx-build` (deploy на Pages).
6. `progress-gate` — парсит `PROGRESS.md`, падает если незакрытые фазы в MR.
7. `phase-gate` — валидирует commit-msg `[phase:<ID>]` + ADR наличие.
8. `regression-grep` + `no-tests-gate` — grep запрещённых импортов и тест-инфры.
9. `release` — `python-semantic-release` + `cyclonedx-py` (SBOM).

### 24.5 `.pre-commit-config.yaml` — 11 hooks

`ruff` (check + format) · `mypy` (fast-mode) · `detect-secrets` · `bandit` ·
стандартные (trailing-whitespace, end-of-file-fixer, check-yaml, check-toml) +
6 локальных guard-ов (см. §25).

### 24.6 `Makefile` — топ-15 targets

```
make init              # Poetry + .venv
make run               # backend на :8000
make run-all           # backend + Streamlit
make migrate           # Alembic upgrade head
make format            # Ruff format + isort
make lint              # ruff + mypy + vulture (soft)
make type-check        # mypy (non-blocking)
make secrets-check     # detect-secrets scan
make audit             # secrets + deps cross-check
make docker-build      # multi-stage Docker
make check-strict      # ruff + creosote + secrets (blocking)
make ship              # fix → check-strict → commit → push
make scaffold type=service name=invoices   # boilerplate
make routes            # список DSL-маршрутов
make actions           # список actions
make progress          # статус фаз
make phase-audit PHASE=A1    # аудит готовности фазы
make readiness-check   # все guards локально
```

## 25. Guard-скрипты · `tools/`

Все требуют commit-message формата `[phase:<ID>] summary` (6 локальных hooks +
CI jobs):

| Файл | Назначение |
|---|---|
| `check_phase_commit.py` | Enforce commit format `[phase:<ID>] ...` |
| `check_adr_link.py` | Требует ADR-ссылку в commit для архитектурных фаз |
| `check_no_tests.py` | **Hard-block** на тестовую инфраструктуру |
| `check_phase_order.py` | Не даёт закрыть фазу без закрытия зависимостей |
| `check_deps_matrix.py` | Сверяет `pyproject.toml` с матрицей ADD/REMOVE per phase |
| `update_progress.py` | Синхронизирует `PROGRESS.md` + `PHASE_STATUS.yml` по commit |
| `report_phases.py` | Печатает сводку статуса (используется локально + CI) |
| `render_mr_description.py` | Генерирует Markdown для описания MR |

Вспомогательные: `scaffold.py`, `dsl_diff.py`, `generate_*.py`, `DSL-TOOLS.md`.

`scripts/audit.sh <phase-id>` — проверка готовности конкретной фазы (артефакты,
PROGRESS-запись, линтеры).

## 26. Как добавить новую фичу — пошаговый рецепт

Сценарий: нужно добавить новый endpoint `/api/v1/invoice/create` + бизнес-логику
+ таблицу в БД.

### Шаг 1 · Pydantic-схемы · `src/schemas/route_schemas/invoices.py`

```python
from app.schemas.base import BaseSchema

class InvoiceSchemaIn(BaseSchema):
    customer_id: int
    amount: Decimal
    currency: str = "RUB"

class InvoiceSchemaOut(BaseSchema):
    id: int
    customer_id: int
    amount: Decimal
    currency: str
    created_at: datetime
```

И filter: `src/schemas/filter_schemas/invoices.py`.

### Шаг 2 · ORM-модель · `src/infrastructure/database/models/invoices.py`

```python
from app.infrastructure.database.models.base import BaseModel
from app.infrastructure.database.tenant_filter import TenantMixin

class Invoice(BaseModel, TenantMixin):
    __tablename__ = "invoices"

    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
```

### Шаг 3 · Миграция Alembic

```bash
poetry run alembic revision --autogenerate -m "add invoices"
poetry run alembic upgrade head   # или: make migrate
```

### Шаг 4 · Репозиторий · `src/infrastructure/repositories/invoices.py`

```python
from app.infrastructure.repositories.base import SQLAlchemyRepository

class InvoiceRepository(SQLAlchemyRepository[Invoice]):
    model = Invoice
```

### Шаг 5 · Сервис · `src/services/core/invoices.py`

```python
from app.services.core.base import BaseService

class InvoiceService(BaseService):
    def __init__(self, repo: InvoiceRepository):
        super().__init__(repo=repo, ...)

    async def issue(self, customer_id: int, amount: Decimal) -> Invoice:
        return await self.add({"customer_id": customer_id, "amount": amount})
```

### Шаг 6 · Регистрация в svcs + ActionHandlerRegistry · в `lifecycle.py`

```python
register_factory("invoices", lambda: InvoiceService(repo=InvoiceRepository(...)))

action_handler_registry.register(
    action="invoices.create",
    service_getter=lambda: get_service("invoices"),
    service_method="issue",
    payload_model=InvoiceSchemaIn,
)
```

### Шаг 7 · DSL-маршрут · `src/dsl/routes.py`

```python
route = (
    RouteBuilder.from_("invoices.create", source="http:/api/v1/invoice/create")
    .validate(InvoiceSchemaIn)
    .dispatch_action("invoices.create")
    .log()
    .build()
)
route_registry.register(route)
```

Или через автоген API Generator (`ActionRouterBuilder`) — endpoint создастся
автоматически.

### Шаг 8 · Коммит

```
[phase:<ID>] invoices: add schema + model + service + DSL route

ADR: — (если архитектурных решений нет)
```

Если фаза требует ADR — создать `docs/adr/ADR-NNN-invoices.md` (формат MADR).

### Шаг 9 · Обновить `CLAUDE.md`

Если добавился новый модуль или новый процессор — дописать соответствующую
секцию этого файла, чтобы следующая сессия Claude видела актуальную картину.
Пример: новая таблица → дополнить раздел 11.1; новый процессор → дополнить
раздел 8.

## 27. Известные gap-ы и follow-up задачи

### 27.1 B1 phase-2 — декомпозиция `builder.py`

**Текущее:** `src/dsl/builder.py` = 1313 LOC.
**Цель:** 11 файлов по ≤300 LOC в `src/dsl/builders/` (Core/EIP/Transport/
Streaming/AI/RPA/Banking/BankingAI/Storage/Security/Observability).
**Риск:** высокий без тестов. Публичный API должен сохраниться байт-в-байт.
**План:** выполнять в smoke-окружении заказчика с ручной верификацией ключевых
routes. Отдельный коммит `[phase:B1+] physical split builder.py`.

### 27.2 H1 docs gap — 6 недостающих документов

Нужно создать на русском:
- `docs/RUNBOOK.md` — on-call playbook.
- `docs/SECURITY.md` — threat model, OWASP, incident response.
- `docs/SCALING.md` — HPA/VPA, pool sizing, backpressure.
- `docs/ROLLOUT.md` — blue-green, canary, feature flags.
- `docs/TROUBLESHOOTING.md` — частые ошибки DSL.
- `docs/CONTRIBUTING.md` — local setup, commit format, PR template.

Коммит: `[phase:H1+] complete documentation set`.

### 27.3 H3_PLUS — физическое удаление legacy зависимостей (cooldown до 2026-07-01)

**Удалить из `pyproject.toml` и `src/`:**
- `aiohttp` (1 import в `src/infrastructure/clients/transport/http.py`).
- `pandas` (~10 imports, legacy analytics).
- `zeep` (2 imports в `soap.py` + 2 в `soap_adapter.py`).
- `sqlalchemy-utils` (по возможности заменить на native SA 2.0 types).
- `starlette-exporter` (дубль prometheus-client).

Коммит: `[phase:H3+] remove deprecated modules (cooldown passed)`.

Матрица учитывает через фиктивную фазу `H3_PLUS` в `tools/check_deps_matrix.py` —
активируется после 2026-07-01.

### 27.4 Production-доводка (итеративно, по запросу заказчика)

Проект находится в состоянии «40 фаз зафиксированы, идёт постепенная доводка».
Типовые follow-up задачи:
- Реальные конфиги Kafka/Vault/OPA/Qdrant под инфраструктуру заказчика.
- Наполнение extras-коннекторов (iot/web3/legacy/enterprise) под конкретные
  протоколы заказчика.
- Prometheus rules + Grafana dashboards для SLO.
- Helm-chart / K8s manifests под prod-кластер.
- Security review с учётом 152-ФЗ / PCI DSS / SWIFT CSP.

## 28. Ссылки на документацию

### 28.1 Progress / статус

- `docs/PROGRESS.md` — чек-лист 40 фаз (строки `- [x] <ID> ... — статус: done`).
- `docs/adr/PHASE_STATUS.yml` — машиночитаемый registry (`meta.total_phases`,
  `meta.closed`).
- `docs/DEPRECATIONS.md` — shim registry (service_registry, http.aiohttp, soap.zeep
  — все до H3_PLUS).

### 28.2 ADR · `docs/adr/` (21 файл, MADR формат)

| ADR | Тема |
|---|---|
| ADR-001 | DSL центральная абстракция |
| ADR-002 | svcs единый DI |
| ADR-003 | CORS policy + explicit origins |
| ADR-004 | gRPC TLS + AuthInterceptor |
| ADR-005 | tenacity-only retry (RetryProcessor удалён) |
| ADR-006 | Granian как prod ASGI |
| ADR-007 | msgspec на hot-paths |
| ADR-008 | polars заменяет pandas |
| ADR-009 | httpx заменяет aiohttp |
| ADR-010 | CloudEvents 1.0 + Schema Registry |
| ADR-011 | Transactional Outbox + Inbox |
| ADR-012 | OPA + Casbin двухуровневая авторизация |
| ADR-013 | FastStream как унифицированная абстракция Kafka/RabbitMQ |
| ADR-014 | qdrant-client + fastembed RAG stack |
| ADR-015 | Developer Portal как отдельный FastAPI-роутер |
| ADR-016 | Temporal как альтернатива Prefect для long-running |
| ADR-017 | Rust/Cython hot-paths |
| ADR-018 | HTTP/3 + compression |
| ADR-019 | Shared-memory IPC + jemalloc |
| ADR-020 | DSL AST compiler |
| ADR-021 | LSP server standalone |

### 28.3 Phases · `docs/phases/` (40 файлов)

PHASE_A1..PHASE_A5, PHASE_B1..PHASE_B2, PHASE_C1..PHASE_C11, PHASE_D1..PHASE_D3,
PHASE_E1..PHASE_E2, PHASE_F1..PHASE_F2, PHASE_G1..PHASE_G3, PHASE_H1..PHASE_H4,
PHASE_I1..PHASE_I2, PHASE_J1, PHASE_K1, PHASE_L1, PHASE_M1, PHASE_N1, PHASE_O1.

Каждый содержит секцию `## Definition of Done` с галочками и ссылками на
изменённые файлы.

### 28.4 Руководства

- `docs/DSL_COOKBOOK.md` — примеры EIP / AI / RPA / banking.
- `docs/ARCHITECTURE.md` — обзор архитектуры.
- `docs/DEVELOPER_GUIDE.md` — гайд для разработчиков.
- `docs/AI_INTEGRATION.md` — AI-подсистема в деталях.
- `docs/RPA_GUIDE.md` — RPA-процессоры.
- `docs/CDC_GUIDE.md` — CDC настройка.
- `docs/EXTENSIONS.md` — opt-in extras.
- `docs/PROCESSORS.md` — полный каталог процессоров.
- `docs/DEPLOYMENT.md` — деплой.

## 29. Быстрый старт для нового разработчика

1. **Установка:** `make init` → Poetry создаёт `.venv`, ставит deps.
2. **Локальный прогон БД:** `docker compose up -d postgres redis`.
3. **Миграции:** `make migrate`.
4. **Запуск:** `make run-all` (backend на :8000 + Streamlit).
5. **Открыть:** http://localhost:8000/docs (Swagger) и http://localhost:8501
   (Streamlit).
6. **Проверить routes:** `make routes`.
7. **Проверить actions:** `make actions`.
8. **Прогнать линтеры:** `make lint`.
9. **Прочитать сначала:** этот файл (CLAUDE.md), затем `src/dsl/builder.py` и
   `src/dsl/engine/exchange.py`, затем пример маршрута в `src/dsl/routes.py`.

**Никогда:**
- Не создавать `tests/`, `conftest.py`, не импортировать `pytest` (hard-block).
- Не коммитить без `[phase:<ID>]` префикса (pre-commit блокирует).
- Не использовать `git add -A` в Makefile — заменено на explicit paths (A2).
- Не добавлять `"*"` в `cors_origins` для prod (validator rejects).
- Не использовать `passlib` / `psycopg2` / `async_timeout` / `aioboto3` (удалены).

---

## История изменений

| Дата | Изменение |
|---|---|
| 2026-04-21 | Первоначальное создание knowledge graph на основе ревью 40 закрытых фаз (v1.0). Собрано 4 параллельными Explore-агентами. |

<!--
Инструкция к обновлениям:
  * Добавлять новую строку в таблицу истории при значимой правке.
  * Не удалять старые записи — это audit-trail.
  * Формат: YYYY-MM-DD · краткое описание правки (какую секцию меняли и зачем).
-->

