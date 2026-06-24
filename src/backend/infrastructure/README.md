# Infrastructure Layer

**Role:** External-world adapters, runtime services, and platform infrastructure.
**Boundary rule:** Core/DSL/services MAY import from infrastructure via `core/di/providers/*` facade ONLY.
Direct `from src.backend.infrastructure.*` in core/ is a **layer violation** (currently 42 such imports — tracked for E2 migration).

## Navigation Index

| Subdir | Files | Role |
|--------|------:|------|
| `ai/` | 5 | AI/ML runtime: model orchestration, embeddings, sandbox (e2b_code_interpreter) |
| `antivirus/` | 6 | Antivirus scanning (ClamAV unix/TCP, HTTP API) via ChainedAntivirusBackend |
| `application/` | 7 | Health aggregator + system-level runtime services |
| `audit/` | 4 | Audit event log + audit pipeline (immutable records) |
| `cache/` | 9 | Cache backends (Redis/KeyDB/Memcached/Memory) + RAG three-tier |
| `cdc/` | 5 | Change Data Capture: Debezium, poll, listen/notify backends |
| `chaos/` | 1 | Chaos engineering (resilience testing) |
| `clients/` | 6 | External service clients (HTTP/SOAP/GRPC/SFTP/SMTP/IMAP/NATS) |
| `database/` | 11 | Database primitives (SQLAlchemy session, init, dialect types) |
| `decorators/` | 6 | Cross-cutting decorators (caching, callbacks) |
| `eventing/` | 6 | Event bus + outbox pattern |
| `execution/` | 2 | Dask/RQ/sync execution backends |
| `external_apis/` | 5 | External API adapters (search, docs, etc.) |
| `import_gateway/` | 5 | Import schemas from external sources (Postman/OpenAPI/WSDL) |
| `logging/` | 7 | Structured logging (structlog, stdlib, graylog, console) |
| `messaging/` | 2 | Queue adapters (Kafka/RabbitMQ/Redis Streams) |
| `monitoring/` | 2 | Health checks + system metrics |
| `notifications/` | 5 | Notification gateway (email/telegram/slack/etc.) |
| `observability/` | 16 | OpenTelemetry, Prometheus, audit traces, metrics registry |
| `persistence/` | 2 | Degradation state + persistence helpers |
| `policy/` | 3 | Capability + RBAC policy runtime |
| `repositories/` | 8 | SQLAlchemy repository pattern (base + per-domain) |
| `resilience/` | 17 | Circuit breakers, retries, rate limiters, bulkheads, health |
| `scheduler/` | 10 | APScheduler + DLQ + job queue |
| `secrets/` | 9 | Vault integration, env-secrets, secret rotation |
| `security/` | 9 | Token registry, env-secrets, security primitives |
| `sinks/` | 13 | Sink adapters (HTTP/MQ/SOAP/S3/file/webhook/etc.) |
| `sources/` | 23 | Source adapters (HTTP/Kafka/CDC/IMAP/file/etc.) |
| `storage/` | 7 | Object storage (S3/MinIO/LocalFS) + fallback chain |
| `watermark/` | 4 | Watermark store (memory/postgres) for incremental processing |
| `workflow/` | 13 | Workflow backends (Temporal/pg_runner/fake) + builder + executor |

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

All external calls use `resilience/` (15 modules):

- `coordinator.py` — orchestrator for fallback chain
- `client_breaker.py` — per-client circuit breaker
- `retry.py` — exponential backoff with jitter
- `rate_limiter.py` + `unified_rate_limiter.py` — distributed rate limiting
- `reconnection.py` — connection recovery
- `time_limiter.py` — async timeout enforcement
- `bulkhead.py` — concurrent call isolation
- `health.py` — liveness/readiness probes

## Audit Status (2026-06-24)

- ✅ DI registry unified (svcs_registry is single source)
- ✅ 32 subdirs organized by concern (adapters/clients/repositories/runtime)
- ⚠️  42 direct `from src.backend.infrastructure` in `core/` (bridge re-exports)
- ⚠️  Connector-level health/facade coverage thin (only 1 facade pattern site)
- ✅ Resilience stack production-grade (15 components, 61 fallback patterns)

## Pending (Milestone 1)

1. Health check facade for each connector category (`clients/transport/*`)
2. Architecture-decision-record for the 42 re-export bridges (when to retire them)
3. `core/di/providers/` extension coverage for CDC, scheduler, notifications, web_search
