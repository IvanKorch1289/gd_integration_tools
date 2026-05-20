# GAP-анализ GD_INTEGRATION_TOOLS — Полный отчёт v2

> **Дата**: Май 2026
> **Метод**: Agent-based deep inspection × 3 агента (Scout → Analyst → Developer) + ручная верификация
> **Проект**: GD_INTEGRATION_TOOLS — integration bus (Python 3.14+)
> **Цель**: 90% production-ready

---

## Сводная таблица

| # | Слой | P0 | P1 | P2 | Всего | Overeng. | Dead code |
|---|------|----|----|----|-------|----------|-----------|
| 1 | Infrastructure/Clients | 2 | 6 | 7 | 15 | 2 | 1 |
| 2 | Messaging | 1 | 4 | 3 | 8 | 1 | 0 |
| 3 | Observability | 1 | 3 | 2 | 6 | 0 | 0 |
| 4 | DSL/Route Engine | 1 | 3 | 5 | 9 | 2 | 1 |
| 5 | AI/RAG | 1 | 2 | 4 | 7 | 1 | 0 |
| 6 | Orchestration/Temporal | 1 | 3 | 4 | 8 | 0 | 1 |
| 7 | Security | 0 | 3 | 5 | 8 | 0 | 0 |
| 8 | Plugin/Extension | 0 | 3 | 4 | 7 | 0 | 1 |
| 9 | API/REST | 0 | 2 | 4 | 6 | 0 | 0 |
| 10 | Streamlit UI | 0 | 1 | 7 | 8 | 0 | 0 |
| 11 | Testing/CI | 0 | 3 | 3 | 6 | 0 | 0 |
| **ИТОГО** | | **7** | **30** | **44** | **81** | **6** | **3** |

---

## P0 — Критические (устранить немедленно)

### 🔴 L1-P0-1: threading.RLock в async контексте (DEADLOCK RISK)
- **Файл**: `services/schema_registry/registry.py:66`
- **Код**: `self._lock = threading.RLock()` — используется в async-сервере
- **Проблема**: `threading.RLock` блокирует event loop thread; в async-коде должен быть `asyncio.Lock`
- **Риск**: deadlock при высокой нагрузке, когда registry вызывается из нескольких concurrent async tasks
- **Исправление**: заменить на `asyncio.Lock()`:
```python
# Было:
self._lock = threading.RLock()

# Стало:
self._lock = asyncio.Lock()

# И все with self._lock: → async with self._lock:
```

### 🔴 L1-P0-2: SFTP client — нет connection pooling
- **Файл**: `infrastructure/clients/transport/ftp.py`
- **Проблема**: каждый вызов открывает новое TCP-соединение; нет reconnect logic
- **Альтернатива**: использовать `asyncssh` с session pooling
- **Библиотека**: `asyncssh` (1MB, maintained, supports connection pooling, known_hosts)

### 🔴 L1-P0-3: FTP client — нет connection pooling
- **Файл**: `infrastructure/clients/transport/ftp.py`
- **Проблема**: тот же файл, FTP и SFTP без pooling
- **Библиотека**: `asyncssh` поддерживает и SFTP и FTP

### 🔴 L2-P0-1: No Transactional Outbox в одной DB-транзакции
- **Файл**: `infrastructure/messaging/outbox/dispatcher.py`
- **Проблема**: outbox events отправляются отдельно от business transaction
- **Исправление**: outbox record должен создаваться в той же DB-транзакции что и business data
```python
async with session.begin():
    await session.execute(insert(BusinessOrder), order_data)
    await session.execute(insert(OutboxEvent), outbox_record)  # в той же транзакции
```

### 🔴 L3-P0-1: OTel Metrics (OTLP) не подключены к pipeline
- **Файл**: `infrastructure/observability/otel/setup.py`
- **Проблема**: OTLP exporter инициализирован, но метрики не экспортируются автоматически в workflow/REST
- **Исправление**: подключить `OTLPMetricExporter` в `setup.py`

### 🔴 L4-P0-1: Нет LSP/IDE плагина для DSL
- **Файл**: `dsl/cli/linter.py` (только batch CLI)
- **Проблема**: `dsl/linter.py` — batch-only; реального Language Server Protocol нет
- **Библиотека**: `pygls` (Python Generic Language Server) — стандарт для LSP
- **Реализация**: обернуть `linter.py` в `pygls` для VSCode/IntelliJ автокомплита

### 🔴 L5-P0-1: Adaptive RAG не реализован
- **Файл**: `services/ai/rag_service.py`, `dsl/engine/processors/ai.py`
- **Проблема**: HyDE и multi_query стратегии есть, но динамический выбор стратегии по типу запроса отсутствует
- **Исправление**: добавить `QueryClassifier` → маршрутизация в `RAGStrategy`

---

## P1 — Высокий приоритет

### L1-P1-1: Decorrelated jitter отсутствует в retry
- **Файл**: `core/retry.py` или `resilience.py`
- **Проблема**: retry с фиксированным или экспоненциальным backoff без jitter
- **Библиотека**: `tenacity` (уже в зависимостях `tenacity>=9.0.0`) — имеет `jitter`
```python
from tenacity import retry, stop_after_attempt, wait_random_exponential

@retry(wait=wait_random_exponential(multiplier=0.5, max=30))
async def unreliable_call(): ...
```

### L1-P1-2: Vector stores — нет unified interface
- **Файл**: `infrastructure/clients/storage/vector_store.py`
- **Проблема**: Qdrant/Milvus/Chroma реализованы в одном файле, но нет abstract base
- **Библиотека**: написать abstract base class (рекомендуется свой ABC как в других клиентах)

### L1-P1-3: Cache Redis — нет graceful degradation при Redis down
- **Файл**: `infrastructure/cache/redis_cluster.py`
- **Проблема**: при недоступности Redis нет fallback на in-memory LRU
- **Библиотека**: `cachetools` (уже в зависимостях) — добавить TTLCache как fallback

### L1-P1-4: Vault secrets — нет авториотации
- **Файл**: `core/secrets_sources.py`, `core/config/features.py:461`
- **Проблема**: `vault_rotation_enabled` flag есть, но механизм ротации не реализован
- **Библиотека**: `hvac` (HashiCorp Vault client, уже используется)

### L1-P1-5: HTTP client — нет request tracing (OTel)
- **Файл**: `infrastructure/clients/transport/http_httpx.py`
- **Проблема**: httpx instrumented для OTel tracing, но propagation headers не добавляются
- **Исправление**: добавить `trace_context` propagation в outgoing requests

### L1-P1-6: Circuit breaker — нет state persistence
- **Файл**: `infrastructure/resilience/` (breaker logic)
- **Проблема**: circuit breaker state in-memory, теряется при рестарте
- **Библиотека**: `pybreaker` (уже есть как концепт, заменить custom на `pybreaker`)
```python
import pybreaker
breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=60)
```

### L2-P1-1: EventBus — нет publisher retries
- **Файл**: `infrastructure/clients/messaging/event_bus.py`
- **Проблема**: publish один раз, при брокер-down сообщение теряется
- **Исправление**: добавить retry с exponential backoff в publisher

### L2-P1-2: Consumer groups — нет explicit offset management
- **Файл**: `mq_sink.py`, `nats_jetstream.py`
- **Проблема**: FastStream handles internally; нет fine-grained control
- **Исправление**: expose consumer group config в DSL

### L2-P1-3: ReplyChannel — нет TTL на корреляционные ID
- **Файл**: `infrastructure/clients/messaging/reply_channel.py`
- **Проблема**: asyncio.Future хранится вечно, memory leak при таймаутах
- **Исправление**: добавить TTL и cleanup task для orphaned futures

### L3-P1-1: /health endpoints — нет composite health для SLA
- **Файл**: `infrastructure/application/health_aggregator.py`
- **Проблема**: per-component health, но нет weighted SLA-level aggregate
- **Исправление**: добавить `sla_health = Σ(critical_weight * component_health)`

### L3-P1-2: Logs OTLP — нет gRPC exporter
- **Файл**: `infrastructure/observability/otel/setup.py`
- **Проблема**: OTLP HTTP exporter есть, gRPC не настроен
- **Исправление**: добавить `OTLPLogExporter` с gRPC transport

### L3-P1-3: Kafka trace context propagation — нет в headers
- **Файл**: `infrastructure/sinks/kafka_sink.py`
- **Проблема**: trace_id не пробрасывается в Kafka message headers
- **Исправление**: inject `traceparent` header в produce()

### L4-P1-1: Blueprint library — нет персистентного репозитория
- **Файл**: `dsl/blueprint_loader.py`
- **Проблема**: blueprints загружаются из YAML файлов, нет API для управления
- **Исправление**: добавить `BlueprintRepository` с CRUD в БД

### L4-P1-2: DSL dry-run — нет WebSocket streaming
- **Файл**: `pages/46_DSL_DryRun.py`
- **Проблема**: синхронный вызов dry_run_route(), результат приходит целиком
- **Исправление**: добавить SSE endpoint для пошагового output

### L4-P1-3: DSL version migration — нет automated migration tool
- **Файл**: `dsl/versioning/migrations.py`
- **Проблема**: framework есть, но миграции v0→v1, v1→v2 делаются вручную
- **Исправление**: добавить `dsl migrate --from v0 --to v2` CLI command

### L5-P1-1: Streaming RAG не реализован
- **Файл**: `services/ai/rag_service.py`
- **Проблема**: все retrieval синхронное, streaming через SSE отсутствует
- **Исправление**: добавить `StreamingRAGProcessor` с SSE

### L5-P1-2: Model Registry UI не реализован
- **Файл**: `core/config/features.py:137` (`frontend_schema_registry_ui` flag)
- **Проблема**: backend protocol есть, pages в Streamlit нет
- **Исправление**: создать pages/XX_Model_Registry.py

### L6-P1-1: Workflow versioning — нет version history
- **Файл**: `infrastructure/workflow/temporal_backend.py`
- **Проблема**: WorkflowRegistry есть, но история версий не сохраняется
- **Исправление**: добавить `WorkflowVersion` model в БД

### L6-P1-2: Replay UI не реализован
- **Файл**: `pages/17_Workflow_Replay.py`
- **Проблема**: timeline view есть, но replay с точки не работает
- **Исправление**: добавить `replay_from_event(event_id)` backend call

### L6-P1-3: TaskGroup не реализован
- **Проблема**: Temporal TaskGroup primitive отсутствует
- **Исправление**: реализовать `TaskGroupProcessor` через asyncio.gather с cancel-on-error

### L7-P1-1: JWT introspection (RFC 7662) не реализован
- **Проблема**: токены валидируются локально, introspection endpoint отсутствует
- **Исправление**: добавить `GET /auth/introspect` endpoint

### L7-P1-2: Fine-grained RBAC — только coarse-grained
- **Файл**: `core/interfaces/action_dispatcher.py:172`
- **Проблема**: `@require_role` — role-based only, нет attribute-based (ABAC)
- **Библиотека**: `casbin` — ABAC engine
```python
enforcer = casbin.Enforcer("rbac_model.conf", adapter)
enforcer.enforce(user, "workflow", "replay", {"tenant": "acme"})
```

### L7-P1-3: Audit log — нет streaming
- **Файл**: `entrypoints/middlewares/audit_log.py`
- **Проблема**: batch запись в ClickHouse; нет real-time SSE
- **Исправление**: добавить SSE endpoint `/admin/audit/stream`

### L8-P1-1: Plugin dependency resolution — нет topological sort
- **Файл**: `services/plugins/loader_v11.py`
- **Проблема**: `plugin.toml` имеет `dependencies` field, но парсинг и сортировка отсутствуют
- **Исправление**: добавить `PluginGraphResolver` с topological sort + cycle detection
```python
from cachetools import OrderedGraph
graph = OrderedGraph()
for plugin in plugins: graph.add(plugin.name, plugin.dependencies)
sorted_loading_order = list(graph.topological_sort())
```

### L8-P1-2: Plugin versioning API — нет REST endpoints
- **Файл**: `services/plugins/versioning.py` (internal only)
- **Проблема**: versioning работает internal, но API для list/rollback отсутствует
- **Исправление**: добавить `GET/PATCH /api/v1/plugins/{id}/versions`

### L8-P1-3: Plugin telemetry — нет plugin-isolated spans
- **Проблема**: OTel generic, plugin-specific trace context isolation отсутствует
- **Исправление**: передавать `plugin_name` в span attributes

### L9-P1-1: Global rate limiting middleware — нет ASGI-level
- **Файл**: `entrypoints/dependencies/rate_limit.py:36`
- **Проблема**: rate limiting per-route через `Depends()`, нет глобального ASGI middleware
- **Исправление**: добавить `RateLimitMiddleware` в `setup_middlewares.py`
```python
from fastapi_limiter import FastAPILimiter
@app.middleware("http")
async def rate_limit_middleware(request, call_next):
    key = request.client.host
    await FastAPILimiter.limit(key)(request)
    return await call_next(request)
```

### L9-P1-2: API changelog endpoint отсутствует
- **Проблема**: `/api/v1/changelog` не найден
- **Исправление**: создать endpoint возвращающий историю изменений API

### L10-P1-1: Search history не персистентный
- **Файл**: `pages/41_Search.py:39` (session_state only)
- **Проблема**: история поиска теряется между сессиями
- **Исправление**: сохранять в БД + table widget для истории

### L11-P1-1: Coverage ≥75% gate отсутствует
- **Файл**: `pyproject.toml` (coverage config)
- **Проблема**: `fail_under = 75` не установлен
- **Исправление**: добавить в `[tool.coverage.report]`:
```toml
[tool.coverage.report]
fail_under = 75
```

### L11-P1-2: Per-layer coverage breakdown отсутствует
- **Проблема**: нет скрипта для coverage по слоям L1-L11
- **Исправление**: создать `tools/coverage/breakdown_by_layer.py`

### L11-P1-3: ADR-002 contract tests отсутствуют
- **Проблема**: ADR-002 referenced, но contract tests для DI container нет
- **Исправление**: создать `tests/unit/test_adr002_di_contract.py`

---

## P2 — Средний приоритет (доработка до 90%)

### L1-P2-1: S3 — нет multipart upload для больших файлов
### L1-P2-2: GraphQL client — нет batched queries
### L1-P2-3: gRPC — нет load balancing (round-robin)
### L1-P2-4: AMQP — нет publisher confirms
### L1-P2-5: NATS — нет JetStream persistence config
### L1-P2-6: MQTT — нет last-will testament
### L1-P2-7: Batch cursor pagination — нет для коллекций

### L2-P2-1: Consumer group rebalance listeners
### L2-P2-2: DLQ — нет retry schedule (exponential backoff)
### L2-P2-3: Schema Registry — Avro/Protobuf support

### L3-P2-1: K8s resource attributes в telemetry
### L3-P2-2: SLA bucket metrics (p50/p90/p99)

### L4-P2-1: DSL hot-reload race conditions (debounce 500ms)
### L4-P2-2: Multi-tenant DSL isolation
### L4-P2-3: DSL Builder IDE autocomplete
### L4-P2-4: JSON-Schema validation для blueprint файлов
### L4-P2-5: LSP real-time diagnostics (см. P0)

### L5-P2-1: HyDE document embedding cache
### L5-P2-2: Multi-query expansion cache
### L5-P2-3: RAG evaluation harness (RAGAS, Trulens)
### L5-P2-4: Reranking — BGE reranker v2 upgrade

### L6-P2-1: Saga orchestrator implementation (Protocol есть, impl нет)
### L6-P2-2: Continue-as-new для long-running workflows
### L6-P2-3: Workflow cost estimator
### L6-P2-4: Cancel DSL mid-execution

### L7-P2-1: mTLS certificate auto-rotation
### L7-P2-2: Secrets rotation implementation (flag есть, impl нет)
### L7-P2-3: PII masking — добавить больше regex patterns
### L7-P2-4: Audit log — SSE streaming (см. P1)
### L7-P2-5: Security headers — добавить CSP directives

### L8-P2-1: Plugin health-check изолированный
### L8-P2-2: Sandbox resource limits enforcement
### L8-P2-3: Plugin telemetry — plugin-level spans
### L8-P2-4: Hot-swap — проверить race condition при concurrent calls

### L9-P2-1: OpenAPI examples в schema export
### L9-P2-2: Per-IP global rate limit middleware
### L9-P2-3: API versioning — sunset headers для deprecated endpoints
### L9-P2-4: API deprecation timeline endpoint

### L10-P2-1: Tenant switcher widget
### L10-P2-2: Dark mode
### L10-P2-3: Keyboard shortcuts
### L10-P2-4: Mobile responsive layout
### L10-P2-5: Workflow timeline — real Gantt chart (bar_chart partial)
### L10-P2-6: WebSocket real-time updates в dry-run page
### L10-P2-7: DSL dry-run waterfall — step-by-step rendering

### L11-P2-1: Contract testing — schemathesis для OpenAPI
### L11-P2-2: Coverage report automation (GitHub Actions)
### L11-P2-3: Chaos engineering — fault injection toolkit

---

## Overengineering (избыточная сложность)

### OE-1: DSL hot-reload через watchfiles при наличии uvicorn --reload
- **Файл**: `core/config/hot_reload.py` (134 lines)
- **Проблема**: uvicorn уже имеет `--reload` флаг; custom watchfiles + 500ms debounce дублирует функциональность
- **Рекомендация**: удалить `hot_reload.py` если uvicorn --reload покрывает use-case

### OE-2: Custom retry logic когда tenacity уже есть
- **Файл**: `core/retry.py` или аналогичный
- **Проблема**: custom retry decorator когда `tenacity>=9.0.0` уже в зависимостях
- **Рекомендация**: заменить custom на `from tenacity import retry, ...`

### OE-3: LiteTemporalBackend — overengineering для dev_light
- **Файл**: `infrastructure/workflow/lite_temporal_backend.py`
- **Проблема**: полноценный Temporal сервер есть; in-process LiteTemporalBackend — избыточная complex abstraction
- **Рекомендация**: упростить до заглушки которая просто вызывает activity напрямую

### OE-4: Dual pydantic v1/v2 patterns в одном codebase
- **Проблема**: `pydantic>=2.10.3` (v2) но遗留 код использует v1 patterns (BaseModel vs pydantic.BaseModel)
- **Рекомендация**: мигрировать весь код на v2 (`model_validate`, `model_dump`)

### OE-5: 36+ Streamlit pages — UI monolith
- **Файл**: `src/frontend/streamlit_app/pages/`
- **Проблема**: 77 файлов в pages/ — слишком много для одного app; нарушает Single Responsibility
- **Рекомендация**: выделить `pages_ai/`, `pages_admin/`, `pages_workflow/` как отдельные apps

### OE-6: Schema Registry — RAM-only (можно потерять при рестарте)
- **Файл**: `services/schema_registry/registry.py`
- **Проблема**: registry в памяти; при рестарте пересоздаётся из populator
- **Рекомендация**: добавить опциональный persistence layer (Redis или DB)

---

## Dead Code

### DC-1: RouteBuilder.clone() — никогда не вызывается
- **Файл**: `dsl/route/builder/`
- **Проблема**: `clone()` method есть в RouteBuilder, но grep не находит вызовов
- **Действие**: проверить и удалить если не используется

### DC-2: Blueprint versioning flags без migration implementation
- **Файл**: `dsl/versioning/` — migration framework есть, но реальные миграции v0→v1 отсутствуют
- **Действие**: либо реализовать миграции, либо удалить framework

### DC-3: windows_worker/ — RPA sidecar не подключен к main app
- **Файл**: `windows_worker/`
- **Проблема**: Windows RPA sidecar существует, но не интегрирован в main app lifecycle
- **Действие**: проверить интеграцию или удалить

---

## Dependency Audit

### ⚠️ Critical: Empty extras (документированные но пустые)
```toml
iot = []          # задеклаарировано, не реализовано
web3 = []         # задеклаарировано, не реализовано
legacy = []       # задеклаарировано, не реализовано
banking = []      # задеклаарировано, не реализовано
enterprise = []   # задеклаарировано, не реализовано
datalake = []     # задеклаарировано, не реализовано
temporal = []     # задеклаарировано, не реализовано
beam = []         # задеклаарировано, не реализовано
```
**Проблема**:混乱 в dependencies; разработчики и CI не знают что эти extras пустые
**Действие**: удалить пустые extras из pyproject.toml

### ⚠️ Heavy dependencies
| Package | Size | Recommendation |
|---------|------|----------------|
| mlflow (ai-model-registry) | ~150MB | Использовать `mlflow-rest-client` или только нужные extras |
| paddlepaddle (rpa-ocr) | ~500MB | OK (уже optional) |
| docling (multimodal-rag) | Heavy | OK (уже optional) |
| inspect-ai (ai) | Heavy | OK (уже optional) |
| dask[distributed] | Heavy | Если не нужен distributed cluster — убрать [distributed] |

### ✅ Dependency chain — Good practices
- `python-multipart>=0.0.18` — safe from CVE-2024-24762 ✅
- `pydantic>=2.10.3` — modern v2 API ✅
- `opentelemetry-api>=1.30.0` — full OTel stack ✅
- `tenacity>=9.0.0` — retry library available ✅
- `orjson>=3.11.8` — fast JSON ✅
- `uvloop>=0.21.0` — fast async event loop ✅
- `structlog>=24.4.0` — structured logging ✅

### 📦 Missing dependencies for production
| Package | Why needed |
|---------|------------|
| `pybreaker` | Circuit breaker state machine (заменит custom) |
| `structlog-sentry` | Structured Sentry integration |
| `httpx-ws` | WebSocket support for httpx |
| `pip-audit` | Dependency vulnerability scanning |

---

## Библиотечные замены для custom functionality

| Custom code | Библиотека | Обоснование |
|-------------|------------|-------------|
| Custom retry decorator | `tenacity` (уже есть) | Battle-tested, configurable backoff/jitter/retries |
| Custom circuit breaker | `pybreaker` | State machine с fail_max, reset_timeout |
| Custom rate limiter | `fastapi-limiter` (уже есть) + `purgatory` | ASGI middleware integration |
| Custom hot-reload | `uvicorn --reload` | Уже есть в stack |
| Custom PII masker | `presidio-analyzer` (уже есть в security extra) | Лучше regex patterns + ML |
| Custom Lock (threading) | `asyncio.Lock` (stdlib) | Для async context |
| Custom LSP для DSL | `pygls` | Standard Python LSP implementation |
| Plugin dependency graph | `cachetools.OrderedGraph` (уже есть) | topological sort + cycle detection |
| Workflow versioning | Temporal workflow history (уже есть) | Встроенное в Temporal |

---

## 90% Production Readiness — Roadmap

### Фаза 1: Critical Fixes (1-2 спринта)

**Must-fix перед prod:**
1. L1-P0-1: `threading.RLock` → `asyncio.Lock` (registry.py:66)
2. L1-P0-2/3: SFTP/FTP pooling (asyncssh)
3. L2-P0-1: Transactional Outbox в одной DB transaction
4. L3-P0-1: OTel metrics pipeline подключить
5. L4-P0-1: pygls LSP server (или удалить linter batch-only)
6. L5-P0-1: Adaptive RAG QueryClassifier
7. Удалить пустые extras из pyproject.toml
8. `tenacity` заменить custom retry decorators

### Фаза 2: High Priority (3-4 спринта)

1. Все P1 gaps из таблицы выше
2. Plugin dependency resolution (topological sort)
3. Global ASGI rate limiting middleware
4. Workflow versioning + Replay UI
5. Coverage ≥75% gate + per-layer breakdown
6. JWT Introspection endpoint
7. Circuit breaker → pybreaker

### Фаза 3: Polish (5-6 спринтов)

1. Все P2 gaps
2. Dark mode + keyboard shortcuts + mobile layout
3. Search history persistence
4. ADR-002 contract tests
5. Streaming RAG + WebSocket dry-run
6. Secrets rotation implementation
7. Audit log SSE streaming

### Фаза 4: Nice-to-have (7+ спринтов)

1. LSP IDE integration (pygls)
2. Multi-tenant DSL isolation
3. Saga orchestrator concrete implementation
4. Contract testing с schemathesis
5. Chaos engineering toolkit
6. RAG evaluation harness
