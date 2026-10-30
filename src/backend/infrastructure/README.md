# Infrastructure Layer

**Role:** External-world adapters, runtime services, and platform infrastructure.
**Boundary rule:** Core/DSL/services MAY import from infrastructure via `core/di/providers/*` facade ONLY.
Direct `from src.backend.infrastructure.*` in core/ is a **layer violation** (currently 33 such import statements in 16 files — tracked for E2 migration).

## Navigation Index

Счётчик «Files» — число `.py`-файлов в подкаталоге (рекурсивно, без
`__pycache__`). Всего в слое — 455 .py-файлов в 32 подкаталогах плюс
3 файла в корне слоя (`__init__.py`, `registry.py`,
`registry_vault_bridge.py`).

| Subdir | Files | Role |
|--------|------:|------|
| `ai/` | 4 | AI/ML runtime: model orchestration, embeddings, sandbox (e2b_code_interpreter) |
| `antivirus/` | 10 | Antivirus scanning (ClamAV unix/TCP, HTTP API) via ChainedAntivirusBackend |
| `application/` | 7 | Health aggregator + system-level runtime services |
| `audit/` | 5 | Audit event log + audit pipeline (immutable records) |
| `cache/` | 24 | Cache backends (Redis/KeyDB/Memcached/Memory) + RAG three-tier + invalidator tiers |
| `cdc/` | 5 | Change Data Capture: Debezium, poll, listen/notify backends |
| `chaos/` | 1 | Chaos engineering (resilience testing) |
| `clients/` | 73 | External service clients (HTTP/SOAP/GRPC/SFTP/SMTP/IMAP/NATS) |
| `database/` | 44 | Database primitives (SQLAlchemy session, init, dialect types, migrations) |
| `decorators/` | 6 | Cross-cutting decorators (caching, callbacks) |
| `di_bridge/` | 6 | DI bridges to core-owned providers (lazy accessors) |
| `eventing/` | 5 | Event bus + outbox pattern |
| `execution/` | 2 | Dask/RQ/sync execution backends |
| `external_apis/` | 5 | External API adapters (search, docs, etc.) |
| `import_gateway/` | 5 | Import schemas from external sources (Postman/OpenAPI/WSDL) |
| `logging/` | 11 | Structured logging (structlog, stdlib, graylog, console) |
| `messaging/` | 25 | Queue adapters (Kafka/RabbitMQ/Redis Streams/NATS) + DLQ |
| `monitoring/` | 2 | Health checks + system metrics |
| `notifications/` | 14 | Notification gateway (email/telegram/slack/etc.) |
| `observability/` | 18 | OpenTelemetry, Prometheus, audit traces, metrics registry |
| `persistence/` | 2 | Degradation state + persistence helpers |
| `policy/` | 5 | Capability + RBAC policy runtime |
| `repositories/` | 15 | SQLAlchemy repository pattern (base + per-domain) |
| `resilience/` | 27 | Circuit breakers, retries, rate limiters, bulkheads, health |
| `scheduler/` | 10 | APScheduler + DLQ + job queue |
| `secrets/` | 9 | Vault integration, env-secrets, secret rotation |
| `security/` | 27 | Token registry, env-secrets, security primitives |
| `sinks/` | 15 | Sink adapters (HTTP/MQ/SOAP/S3/file/webhook/etc.) |
| `sources/` | 24 | Source adapters (HTTP/Kafka/CDC/IMAP/file/etc.) |
| `storage/` | 10 | Object storage (S3/MinIO/LocalFS) + fallback chain + quotas |
| `watermark/` | 4 | Watermark store (memory/postgres) for incremental processing |
| `workflow/` | 32 | Workflow backends (Temporal/LiteTemporal/pg_runner/fake) + builder + executor |

## Layer Position

```
  entrypoints  ──┐
                 │
  dsl           ─┼─► infrastructure (this layer)
                 │       │
  services      ──┘       ▼
                         external systems (DB / cache / queue / API)
```

## Facade / Single-Entry-Points

Per E1 (commit `ed02768`) + S168/S170, extensions/devs MUST use `core/di/providers/` facade instead of importing from this layer directly:

| Domain | Facade Provider |
|--------|-----------------|
| AI/ML | `get_ai_provider()` → `core/di/providers/ai.py` |
| Auth | `get_auth_provider()` → `core/di/providers/auth.py` |
| Cache | `get_cache_provider()` → `core/di/providers/cache.py` |
| DB | `get_db_provider()` → `core/di/providers/db.py` |
| HTTP | `get_http_provider()` → `core/di/providers/http.py` |
| Jupyter | `get_jupyter_provider()` → `core/di/providers/jupyter.py` |
| Storage | `get_storage_facade_provider()` → `core/di/providers/storage.py` |
| Workflow | `get_workflow_provider()` → `core/di/providers/workflow.py` |

## Health Check Coverage

Health checks implemented in: `application/health_aggregator.py`, `monitoring/health_check.py`, `resilience/health.py`.
Per-connector health: each `clients/transport/<protocol>` module exposes `is_healthy()` via singleton accessor.

## Resilience Patterns

All external calls use `resilience/` (27 modules, 15 верхнего уровня +
`components/`):

- `coordinator.py` — orchestrator for fallback chain
- `client_breaker.py` — per-client circuit breaker
- `retry.py` — exponential backoff with jitter
- `rate_limiter.py` + `unified_rate_limiter.py` — distributed rate limiting
- `reconnection.py` — connection recovery
- `time_limiter.py` — async timeout enforcement
- `bulkhead.py` — concurrent call isolation
- `health.py` — liveness/readiness probes

## Audit Status (2026-10-30)

- ✅ DI registry unified (svcs_registry is single source)
- ✅ 32 subdirs organized by concern (adapters/clients/repositories/runtime)
- ⚠️  33 direct `from src.backend.infrastructure` import statements in
  `core/` (16 files) — bridge re-exports; baseline слоёв: 37 legacy + 4
  contract (`tools/check_layers.py`)
- ⚠️  Connector-level health/facade coverage thin (only 1 facade pattern site)
- ✅ Resilience stack production-grade (27 modules, 61 fallback patterns)

## Pending (Milestone 1)

1. Health check facade for each connector category (`clients/transport/*`)
2. Architecture-decision-record for the 33 re-export bridges (when to retire them)
3. `core/di/providers/` extension coverage for CDC, scheduler, notifications, web_search
