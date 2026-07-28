# Infrastructure Domain — Deep Audit Report (Cycle 31)

> **Объект:** Домен "Инфраструктура" проекта `gd_integration_tools`.
> **Метод:** Независимая перекрёстная проверка через 4 параллельных
> sub-агента: (1) layer independence, (2) facade completeness, (3) library
> overlaps, (4) DSL↔infrastructure integration. Все выводы основаны на
> чтении реального кода.
> **Объём:** 427 Python-файлов / ~67K LOC / ~30 поддоменов.
> **Дата:** 2026-07-28

---

## TL;DR (одно предложение)

Инфраструктурный слой **зрелый и хорошо стратифицированный**, но содержит **три класса решаемых проблем**: (A) **23 layer-violation** (18 fixable, 5 acceptable) — высокий leverage-fix перемещает `dsl/codec/json.py` в `core/` и закрывает 13/23 одним движением; (B) **4 incomplete facade** (Cache без Redis impl, Messaging — stub, `infrastructure_facade.py` — service locator not facade, Auth — verify-only); (C) **5 library overlaps** (HTTP double-retry, dual MongoDB, cbor2 dead, retry API proliferation, presidio triple-pin).

---

## 1. Layer Independence (23 нарушений)

### 1.1 Реальная картина
| Категория | Кол-во | Действие |
|---|---|---|
| Codec utility misplaced (`dsl/codec/json`) | 13 | **FIX** — move to `core/codec/json.py` |
| DSL engine contracts (Exchange/Middleware) | 4 | **FIX** — extract protocols to `core.pipeline.contracts` |
| Services: `SchemaKind` enum | 1 | **FIX** — move enum to `core` |
| Services: embedding provider | 1 | **FIX** — protocol injection |
| Bootstrap/composition wiring | 2 | **ACCEPT** (composition root) |
| Services: deprecated shim | 1 | **ACCEPT** (pending deletion) |
| Services: scheduler wiring | 1 | **ACCEPT** (composition root) |

### 1.2 Enforcement
- **Custom AST-based** `tools/check_layers.py` через `make layers`
- Module-level AND lazy imports проверены (S65 W2)
- `TYPE_CHECKING`-blocks exempt
- 207 строк allowlist для legacy debt
- `--strict` mode для CI/release gates

### 1.3 Корневые причины нарушений
**Root Cause A: `dsl/codec/json.py` — misplaced shared utility** (13 файлов)
- Это orjson-wrapper без DSL-логики (`json_dumps`, `canonical_json_bytes`)
- Используется в `infrastructure/observability/immutable_audit.py`,
  `infrastructure/sinks/*.py` (7 файлов), `infrastructure/workflow/temporal_backend.py`,
  `infrastructure/decorators/caching/*.py` (3 файла),
  `infrastructure/clients/transport/http_httpx.py`,
  `infrastructure/clients/transport/http/prep_mixin.py`

**Root Cause B: DSL engine contracts в infra middleware** (4 файла)
- `infrastructure/observability/metrics.py` — реализует `PrometheusMetricsMiddleware`
- `infrastructure/observability/tracing.py` — реализует `TracingMiddleware`
- `infrastructure/workflow/executor/sequential_mixin.py` — wraps payload in DSL `Exchange`
- `infrastructure/notifications/adapters/express.py` — calls DSL processor helper

**Root Cause C: Composition roots** (2 файла — `infrastructure/workflow/worker.py`,
`infrastructure/clients/external/cdc/client.py`)

**Root Cause D: Services imports** (4 файла)
- `infrastructure/cache/rag/semantic.py` — `services.ai.embedding_providers`
- `infrastructure/clients/messaging/event_bus.py` — `services.schema_registry.registry.SchemaKind`
- `infrastructure/scheduler/scheduled_tasks.py` — `services.ai.memory.langmem_service`
- `infrastructure/security/presidio_sanitizer.py` — deprecated shim

---

## 2. Facades Completeness (6 основных фасадов)

### 2.1 Сводная оценка
| Фасад | LOC | Готовность | Главные gaps |
|---|---|---|---|
| **Storage** | 167 | **85%** ✅ | нет copy/move/stat(metadata) |
| **Audit** | 9 модулей | **90%** ✅ | нет query API (emit-only by design) |
| **Database** | 238 | **80%** ✅ | нет bulk executemany, нет introspection |
| **Auth** | 343 | **55%** ⚠️ | нет issuance, SAML stub, нет LDAP/revoke/refresh |
| **Cache** | 224 | **60%** ⚠️ | **нет Redis impl** (production-unusable), нет bulk/expire/incr |
| **Messaging** | 22 | **10%** ❌ | **нет настоящего фасада**, только `get_stream_client` lazy proxy |

### 2.2 Главные находки

1. **`core/messaging/stream_facade.py` — заглушка (22 строки)**
   ```python
   def __getattr__(name):
       if name == "get_stream_client":
           from src.backend.infrastructure.clients.messaging.stream import get_stream_client
           return get_stream_client
   ```
   - Это единственная "фасадная" функция для messaging
   - EventBusFacade существует в `services/messaging/eventbus_facade.py`, но не
     surface через core/messaging
   - **Fix:** перенести EventBusFacade в `core/messaging/event_bus_facade.py`
     (или выставить через core/api), чтобы DSL processors не импортировали
     `get_event_bus` напрямую (см. п.5)

2. **`UnifiedCacheFacade` — без Redis impl**
   - ABC определён, но `get_cache_facade()` ворочает
     `FallbackCacheFacade(primary=memory, fallback=memory)` — оба tier'а memory
   - В production cache пробирается через `AdminCacheStorageProtocol` напрямую
   - **Fix:** добавить `RedisCacheFacade` impl (декларативно через
     `redis.asyncio.Redis` + backend protocol)

3. **`core/di/providers/infrastructure_facade.py` — service locator, не фасад**
   - 391 LOC, 90+ getter'ов, `_PROVIDERS_REGISTRY` (44 entries)
   - Возвращает **конкретные infra-классы** typed `-> Any`
   - **Нет capability gate** в отличие от StorageFacade
   - **Действие:** переименовать в `infrastructure_locator.py`, в докстринг
     явно отметить "for DI only, use domain facades for business logic"

4. **`core/api/__init__.py` не re-export'ит domain facades**
   - Facades discoverable только через module paths
   - Extension-developer не найдёт `UnifiedCacheFacade`, `AuthFacade`, `StorageFacade`
   - **Fix:** добавить `__all__` entry для каждого facade в `core/api/__init__.py`

5. **72 Protocol contracts в `core/interfaces/`**
   - Богатейший Protocol layer (DB / Cache / Storage / HTTP / Messaging / AI)
   - **Но DI-providers возвращают `Any`** — mypy не может валидировать контракты
   - **Fix:** типизировать return values в DI-providers

---

## 3. Library Landscape — Overlaps, Gaps, Dead Weight

### 3.1 Категоризированный инвентарь
| Категория | Библиотеки |
|---|---|
| Database | sqlalchemy, asyncpg, psycopg2, alembic, sqlalchemy-utils, sqlalchemy-continuum, greenlet, aiosqlite + extras oracledb/aioodbc/aiomysql |
| Cache | redis, diskcache, cachetools, aiomcache |
| Messaging | faststream[kafka], aiokafka, aio-pika, nats-py, aiomqtt, aioimaplib, grpcio, protobuf |
| Storage/Search | elasticsearch, qdrant-client, motor, whoosh-reloaded, chromadb |
| HTTP | httpx[http2], httpx-retries, hishel, zeep, starlette + extras aioquic |
| Observability | opentelemetry-{api,sdk,instrumentation-*}, structlog, sentry-sdk, starlette-exporter, asgi-correlation-id, langfuse |
| Resilience | purgatory (CB), tenacity (retry) |
| Workflow | apscheduler, croniter + extras temporalio |
| Security | cryptography, hvac, joserfc, casbin, argon2-cffi, passlib + extras presidio, python3-saml |
| Serialization | orjson, msgspec, msgpack, cbor2, pyyaml, fastavro, xmltodict, cloudevents |

### 3.2 Топ-5 рекомендованных изменений

| # | Issue | Severity | Действие |
|---|---|---|---|
| **O1** | **HTTP double-retry**: tenacity (app-level) + httpx-retries (transport-level) оба активны для status codes (429,502,503,504) → stacked backoff до 5×5=25 попыток | **High** | Разделить: httpx-retries = только transport errors (connection reset); tenacity = HTTP status codes |
| **O2** | **Retry API proliferation**: 4 wrappers вокруг одного tenacity (`with_retry`, `make_async_retry`, `retry_async`, `async_retry`) + 2 прямых call-site в `http_httpx.py`, `request_mixin.py` | Medium | Консолидировать в один `with_retry(policy=RetryPolicy(...))` |
| **O3** | **Dual MongoDB async**: `motor` (mongodb.py, sources/mongo.py) + `pymongo.AsyncMongoClient` native (cert_store/backend_mongo.py) — две async-stack'и | Medium | Migrate на `pymongo>=4.9` native `AsyncMongoClient` |
| **O4** | **Dead weight cbor2**: используется в 1 файле (`dsl/codec/__init__.py`) | Low | Удалить dep + codec branch |
| **O5** | **presidio triple-pin**: `presidio-analyzer` pinned в `[project]` + `[ai]` + `[security]` + `[ai-safety]` extras (4× same package) | Low | De-duplicate extras |
| **O5b** | **mem0ai dead code**: dep удалён, но lingers: docstring ref к `Mem0MemoryAdapter` (class never defined), feature flag `mem0ai_enabled` | Trivial | Удалить flag + docstring |

### 3.3 Hand-rolled reimplementations — все justified
- `for attempt in range(...)` в `messaging/outbox/dispatcher.py:281` — нужна cancellation-aware asyncio.wait_for
- `class NatsConnectionPool` / `ImapConnectionPool` / `TemporalWorkerPool` — специфика протоколов
- Compression — использует stdlib/brotli

### 3.4 Best practice confirmation (отраслевые стандарты)
- **HTTP retry composition**: общепринятая best practice — только один retry layer на транспорте (industry: requests/httpx docs, Sentry/Kubernetes-style)
- **MongoDB async**: PyMongo 4.9+ native async — official recommendation; Motor в maintenance mode per MongoDB official guidance
- **Codec placement**: shared serialization utilities belong in `core/` or `utilities/` (architectural consensus)
- **Layer enforcement**: import-linter / custom AST checker — well-established pattern (Python community)

---

## 4. DSL ↔ Infrastructure Integration

### 4.1 Импорты по слоям
| Слой | Total imports | Files affected | Module-level | Lazy |
|---|---|---|---|---|
| **DSL** | **94** | **60** | **4** | **90** |
| **Services** | **19** | **15** | **8** | **11** |
| **Extensions** | **0** | **0** | **0** | **0** |

**Extensions — perfect** (0 нарушений). **DSL builders — clean** (через `_add_lazy` строковые ссылки).

### 4.2 DSL processors — главные нарушения

**#1 (HIGH) — EventBusFacade bypassed**
- `dsl/engine/processors/integration.py:41,124` и `request_reply.py:107`
- Импортируют `from ...event_bus import get_event_bus` напрямую
- Capability-checked `EventBusFacade` существует в `services/messaging/eventbus_facade.py`
- **Fix:** swap `get_event_bus()` → `get_event_bus_facade()` — 1-line change

**#2 (HIGH) — DB manager direct import**
- `dsl/engine/processors/components/databasequeryprocessor.py`
- `from src.backend.infrastructure.database.database import get_db_manager`
- **Fix:** introduce `DatabaseFacade` protocol in `core/` (отсутствует)

**#3 (MEDIUM) — 4 module-level DSL→infra imports (hard coupling)**
- `dsl/engine/versioning.py:21` → `infrastructure.database.session_manager`
- `dsl/engine/execution_engine.py:18` → `infrastructure.observability.tracing`
- `dsl/processors/dask_compute.py:26` → `infrastructure.execution.dask_backend`
- `dsl/agents/fastmcp_server.py:36` → `infrastructure.workflow.registry`
- **Fix:** Convert to lazy imports (move inside functions) or inject via DI/context

**#4 (MEDIUM) — S3 dual paths**
- `dsl/engine/processors/storage/s3.py` — uses `StorageFacade` via DI ✅ (correct pattern)
- `dsl/engine/processors/components/s3writeprocessor.py` — imports `storage_client` from `s3_pool` ❌
- `dsl/engine/processors/components/s3readprocessor.py` — same ❌
- **Fix:** Migrate `components/s3*processor.py` на `_get_storage_facade()` pattern (deprecate old)

**#5 (MEDIUM) — sink_publish: no SinkFacade/protocol**
- `sink_publish/protocols.py` — `from ...grpc_sink import GrpcSink` (concrete class)
- `sink_publish/messaging.py` — `from ...mq_sink import MqSink`
- **Fix:** Introduce `SinkProtocol` in `core/`

---

## 5. Remediation Plan (приоритизированный, без overengineering)

### Приоритет 0 — Quick wins (≤2h каждое, no design changes)

| # | Действие | Файл | Эффект |
|---|---|---|---|
| 0.1 | **EventBusFacade swap** | `dsl/engine/processors/integration.py:41,124`; `request_reply.py:107` | 3 строки, устраняет #1 нарушение |
| 0.2 | **Mem0ai dead-code cleanup** | `core/interfaces/ai_memory.py` (docstring ref), `core/config/features/infrastructure.py:131` (feature flag) | Удалить, ~5 LOC |
| 0.3 | **Presidio de-pin (extra duplication)** | `pyproject.toml` (4 entries → 1) | Dep hygiene |
| 0.4 | **cbor2 removal** | `pyproject.toml` (dep), `dsl/codec/__init__.py` (1 branch) | -1 dep |

### Приоритет 1 — Highest-leverage refactor

| # | Действие | Эффект | Effort |
|---|---|---|---|
| 1.1 | **Move `dsl/codec/json.py` → `core/codec/json.py`** (с re-export shim в dsl/codec для backward compat) | **Закрывает 13/23 layer violations одним действием** | Small (~30 min) |

### Приоритет 2 — Facade completeness

| # | Действие | Файл | Эффект |
|---|---|---|---|
| 2.1 | **Re-export domain facades in `core/api/__init__.py`** | `core/api/__init__.py` | Extension DX: discoverable facades |
| 2.2 | **Implement `RedisCacheFacade`** | `infrastructure/cache/backends/redis_cache_facade.py` + register в DI | Production-usable cache |
| 2.3 | **Move EventBusFacade → `core/messaging/event_bus_facade.py`** (re-export from services for compat) | New file in core/messaging | Surfaces facade for DSL #1 fix |

### Приоритет 3 — Library governance

| # | Действие | Файл | Эффект |
|---|---|---|---|
| 3.1 | **HTTP retry de-stack** | `infrastructure/clients/transport/http_httpx.py:build_unified_transport` | Disable status-code retries в httpx-retries; let tenacity own status codes |
| 3.2 | **Retry API consolidation** | `core/resilience/retry.py` | Collapse 4 wrappers → `with_retry(policy=RetryPolicy(...))` only |
| 3.3 | **pymongo native async migration** | `infrastructure/clients/storage/mongodb.py`, `infrastructure/sources/mongo.py` | Drop motor; use pymongo>=4.9 native |

### Приоритет 4 — DSL-infrastructure boundary

| # | Действие | Файл | Эффект |
|---|---|---|---|
| 4.1 | **Convert 4 hard DSL→infra imports to lazy** | `dsl/engine/versioning.py`, `execution_engine.py`, `dsl/processors/dask_compute.py`, `dsl/agents/fastmcp_server.py` | Decouple DSL cold-start from infra presence |
| 4.2 | **Migrate components/s3* to StorageFacade** | `dsl/engine/processors/components/s3writeprocessor.py`, `s3readprocessor.py` | Single S3 access path |
| 4.3 | **Introduce `SinkProtocol` in `core/`** | `core/interfaces/sink.py` | sink_publish decoupled from concrete infra |

### Приоритет 5 — Composition roots & Deprecated shims (low priority)

| # | Действие | Эффект |
|---|---|---|
| 5.1 | **Delete `infrastructure/security/presidio_sanitizer.py`** (deprecated shim) | Layer-violation closure |
| 5.2 | **Move `infrastructure/scheduler/scheduled_tasks.py`** → `bootstrap/scheduler_wiring.py` (composition root) | Cleaner architectural layer |
| 5.3 | **Move `infrastructure/workflow/worker.py`** → `bootstrap/workflow_worker.py` | Same |

### Что делать НЕ нужно (deliberate non-action)

- **RouteBuilder 36-mixin god-class** — separate cycle (Cycle 30 P4-#4)
- **pg_runner replay() full implementation** — defer to Wave D.2+
- **Полный import-linter adoption** — custom AST checker is working; no need to swap
- **Replace `httpx-retries` with homegrown retry** — keep both, just split responsibilities
- **Refactor entire services layer** — services IS the facade layer by design

---

## 6. Метрика / Validation

Все предложенные изменения должны пройти:
- `make layers` — layer enforcement (0 new violations)
- `make lint && make type-check && make test` — CI gates
- Regression test для каждого behavior-changing fix (red → green)
- CHANGELOG.md update в формате существующих entries

Ожидаемые метрики после полного цикла remediation:
- **Layer violations**: 23 → 5 (composition roots remaining)
- **Domain facades re-exported in `core/api`**: 4 → 7 (Cache, Auth, DB, Storage, Audit, Messaging, EventBus)
- **Dependency count**: -3 (cbor2, presidio triplicate, motor)
- **Retry wrappers**: 4 → 1 (`with_retry` only)
- **DSL→infra hard imports**: 4 → 0
- **Test coverage**: target = maintain current % (no regression)

---

## 7. Что мы НЕ предлагаем (anti-overengineering)

- ❌ Не предлагаем rewrite на другую DI-систему (svcs работает, не трогаем)
- ❌ Не предлагаем вводить вторую DI / orchestration abstraction
- ❌ Не предлагаем замену custom AST checker на import-linter (оба одинаковы по силе)
- ❌ Не предлагаем переименование всех существующих "facade"-классов
- ❌ Не предлагаем замену каких-либо Provider-классов в `core/interfaces/` (72 — это хорошо)
- ❌ Не предлагаем миграцию на asyncio-nats 2.x или pika-async 1.x — текущие стабильные
- ❌ Не предлагаем замену httpx на другую HTTP-библиотеку (hishel caching layer — отдельный concern)
- ❌ Не предлагаем создание новой metadata-системы для codec — текущая `canonical_json_bytes` достаточна
