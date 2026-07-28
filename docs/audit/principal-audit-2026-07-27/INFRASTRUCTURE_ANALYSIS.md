# Infrastructure Domain — Deep Analysis Report

**Date:** 2026-07-28 | **Scope:** 427 files across 33 subdirs in `src/backend/infrastructure/`

## 1. Map of the Infrastructure Domain

| Subdir | Files | Description |
|---|---:|---|
| `application/` | 7 | health_aggregator, monitoring, slo_tracker, telemetry, vault_refresher |
| `cdc/` | 5 | Change Data Capture (debezium, listen_notify, poll, cdc_client_adapter) |
| `cache/` | 23 | Cache backends (memory, redis, RAG 3-tier, disk) |
| `clients/` | 66 | External clients (HTTP, storage, messaging, external APIs) |
| `messaging/` | 24 | Event bus, outbox, DLQ, Kafka, FastStream |
| `observability/` | 18 | Metrics, tracing, correlation |
| `resilience/` | 27 | Circuit breaker, retry, rate limiter, bulkhead |
| `security/` | 27 | PII, secrets, cert_store, signatures |
| `sources/` | 24 | CDC, WebSocket, polling, MQ, REST, file |
| `sinks/` | 15 | HTTP, Kafka, file, MQ, email, CDC |
| `database/` | 41 | Session manager, repos, migrations |
| `storage/` | 8 | Object storage, RAG metrics |
| `repositories/` | 12 | Repository base + concrete (mongo, pg) |
| `notifications/` | 14 | Email, SMS, push, templates |
| `decorators/` | 6 | Caching, retry, auth decorators |
| `eventing/` | 5 | EventBus + pub/sub |
| `workflow/` | 28 | Worker, registry, persistence |
| `scheduler/` | 10 | Cron, intervals, DLQ |
| `secrets/` | 9 | Vault + env backends |
| `cache/` | 23 | Mem + redis + disk + rag |
| `policy/` | 5 | OPA integration |
| `antivirus/` | 10 | ClamAV + custom scanners |
| `chaos/` | 1 | Custom probes (S168 KEEP decision) |
| `import_gateway/` | 5 | Swagger/Postman import |
| `external_apis/` | 5 | External REST/SOAP/gRPC |
| `audit/` | 4 | ClickHouse + JSONL |
| `ai/` | 4 | AI providers |
| `execution/` | 2 | Process pool |
| `monitoring/` | 2 | Prometheus push |
| `persistence/` | 2 | Bulk writer |
| `watermark/` | 4 | Watermark for streaming |
| `decorators/`, `feature_flags/`, `logging/` | 12 | Misc |
| `registry.py` + `registry_vault_bridge.py` | 2 | Top-level registry |

## 2. Layer Independence Audit

### Import graph (one direction = layer violation)

| From | To | Count | Status |
|---|---|---:|---|
| core | infrastructure | 59 imports | **VIOLATION** (core should not depend on infra) |
| core | services | 0 | OK |
| services | core | 633 | OK |
| services | infrastructure | 19 | OK (small, through facades) |
| infrastructure | core | 696 | OK (allowed) |
| infrastructure | services | 5 | OK (rare) |

### The 20 core→infra bridges ("facade" pattern, ADR-0207)

All 20 are **lazy re-exports** via `__getattr__` (deferred at import time to avoid circular dependency at import):

| Module | What it re-exports |
|---|---|
| `core/messaging/dlq.py` | DLQEnvelope, DLQReason, DLQWriter |
| `core/messaging/dlq_policy.py` | DLQ Policy classes |
| `core/messaging/event_bus.py` | EventBus |
| `core/messaging/stream_facade.py` | FastStream facade |
| `core/messaging/outbox.py` | Outbox dispatcher |
| `core/storage/redis.py` | get_redis_client |
| `core/repositories/base.py` | Repository base classes |
| `core/cdc/` | CDC client/protocol |
| `core/audit/` | Audit event log |
| `core/clients/` | External clients (search, telegram, express_bot) |
| `core/observability/correlation.py` | Correlation context |
| `core/resilience/rate_limiter.py` | RateLimiter protocol |
| `core/workflow/` | Workflow backend protocol |
| `core/scheduler/` | Scheduler facade |
| `core/secrets/` | Secrets |
| `core/audit/` | Event log |
| `core/di/providers/*_bridge.py` | Lazy getters for health_bridge, dlq_bridge, etc. |
| `core/integrations.py` | Integrations |
| `core/net/migration_helper.py` | make_http_client |
| `core/scaling/bulkhead_scaler.py` | Bulkhead scaler |

**Diagnosis:** This is a managed but acknowledged anti-pattern. The pattern:
1. Pure DTOs/protocols (DLQEnvelope, EventBus, Source/Sink interfaces) belong in core — they should be moved, not lazy-imported.
2. Concrete implementations (get_redis_client, make_http_client) belong in infrastructure — they should NOT be in core's public API at all; services should import directly from infrastructure or go through a proper DI container.

The current pattern is **fragmented and fragile** — the lazy `__getattr__` makes the actual import order non-obvious and creates implicit coupling.

## 3. Library Richness Audit

### Custom code that could be replaced (with cost-benefit)

| File | Custom Code | Library alternative | Risk | Recommendation |
|---|---|---|---|---|
| `chaos/probes.py` | 4 custom fault-injection probes | `chaostoolkit`, `chaos-mesh` | High — S168 decision already documented KEEP rationale | **KEEP** (decided) |
| `workflow/worker.py` | Custom worker pool | `temporalio`, `arq`, `dramatiq` | High — already uses Temporal | Use Temporal properly |
| `cache/` | Custom cache with 3-tier | `aiocache`, `cachetools` | Low | Partially adopted, good |
| `cdc/` | Custom CDC for 3 backends | `debezium` (server), `wal2json` (PG) | Medium — has PG logical replication adapter | **KEEP** (5 backends is large surface) |
| `resilience/` | Custom circuit breaker | `purgatory` (used), `aiocircuitbreaker` | Low — already uses purgatory | OK |
| `monitoring/` | Custom Prometheus push | `prometheus-client` | Low | Check if already used |
| `audit/event_log.py` | Custom ClickHouse JSONL | `python-audit-log` (no mature stdlib) | Medium | KEEP custom (ClickHouse-specific) |
| `secrets/` | Custom Vault wrapper | `hvac` (used) | Low | OK |
| `antivirus/` | Custom ClamAV wrapper | `pyclamd` (no active maintenance) | Low | KEEP custom |
| `import_gateway/` | Custom Swagger/Postman parser | `openapi-spec-validator`, `prance` | Low | Consider `prance` for OpenAPI |

### Custom code that is KEEP (per documented ADRs)

- `chaos/probes.py` — S168 W11 P2-1 DECISION documented
- `workflow/worker.py` — Temporal-bound, can't replace
- `audit/event_log.py` — ClickHouse-specific, no good lib
- `antivirus/` — niche, no good lib

## 4. Facades Audit (backend-agnostic for extensions)

### Existing facades (from `core/frontend_facade.py` + `core/di/providers/infrastructure_facade.py`)

- `core/integrations.py` — generic integration lookup
- `core/clients/storage/redis.py` — Redis facade
- `core/messaging/dlq.py` — DLQ facade
- `core/di/providers/*_bridge.py` — bridge functions
- `core/observability/correlation.py` — correlation context

### Gap: backend-agnostic for "не знать о бэкенде"

The principle says "extensions should not know about the backend" but the current `__getattr__` lazy-import pattern leaks this at runtime. A proper facade would:
1. Have explicit `Protocol` definitions in core
2. Have separate concrete implementations in infrastructure
3. Use a factory or DI container to bind them at startup
4. Not require lazy imports

**Existing (good):**
- `HealthResult`, `HealthMode`, `HealthCheck`, `HealthCheckFactory` — defined in `infrastructure/clients/base_connector.py`, used by `core/clients/base_connector.py` re-exports
- `InfrastructureClient` — abstract base for clients
- `Source`, `Sink` — protocol-based interfaces in core/interfaces/

**Missing (gaps):**
- No unified `get_storage_client(provider: str)` factory
- No unified `get_messaging_client(provider: str)` factory
- No unified `get_database_client(profile: str)` factory

These exist in places but are scattered. A single `core/registry.py` with a `register_*_factory` pattern would centralize.

## 5. Service Layer Integration with Infrastructure

### Service→infra imports (19 total — very good)

The service layer uses infrastructure sparingly:
- `services/notebooks/*` → 3
- `services/rpa/*` → 4
- `services/security/pii_streaming_facade.py` → 1 (re-export pattern)
- `services/workflows/*` → 5
- `services/messaging/*` → 2
- `services/audit/*` → 2
- `services/integrations/*` → 1
- `services/dsl/*` → 1

**Assessment:** Service layer mostly uses core (633 imports) + a few infra. This is correct — services use domain logic, not infrastructure directly.

## 6. DSL Integration with Infrastructure

### DSL→infra imports (58 total — significant)

| Source | Count | Notes |
|---|---:|---|
| `dsl/processors/*` | ~30 | Processors use infrastructure clients (redis, cdc, http, etc.) |
| `dsl/sources/*` | 14 | Source/sink integration |
| `dsl/builder/*` | 6 | Builder uses infra for async I/O |
| `dsl/validation.py` | 2 | Schema validation against infra types |

**Assessment:** DSL processors are inherently about I/O operations, so infra coupling is expected. However, the coupling should go through:
- `core/interfaces/source.py` (Source protocol)
- `core/interfaces/sink.py` (Sink protocol)
- Not directly to concrete infra classes

## 7. Best Practices + Improvement Plan

### What is good (preserve)

1. **Health aggregator** — well-designed (K8s liveness/readiness, fast/deep modes)
2. **Layer 3 isolation** — services use only 19 infra imports (mostly through facades)
3. **Lazy imports via `__getattr__`** — import-time isolation works
4. **Protocol-based interfaces** — Source, Sink, EventBus, DLQWriter, etc.
5. **Bridges** — `core/di/providers/*_bridge.py` for lazy getters

### Issues to fix (prioritized)

#### High priority (architectural risk)

**Issue 1: Core→infra bridges (20 files)** — `core` depends on `infrastructure` at runtime via `__getattr__`. This violates the principle "core should not depend on infra" even with deferred loading.

**Fix (without regression):**
- **Phase 1 (1-2 days):** Move pure DTOs/Protocols from infra to core:
  - `DLQEnvelope`, `DLQReason` (pure dataclasses) → `core/messaging/dlq_envelope.py`
  - `EventBus` Protocol → `core/messaging/event_bus_protocol.py`
  - `Source`, `Sink`, `SourceEvent`, `EventCallback` → already in core, just remove the lazy re-export
  - `CacheBackend` → already in core
  - `HealthResult`, `HealthMode` → move to `core/health.py`
  - `BreakerSpec`, `BreakerLike` → already in core
- **Phase 2 (1 day):** Replace lazy `__getattr__` with explicit imports at the bottom of core/bridge files
- **Phase 3 (1 day):** Add CI check that `core/` doesn't import from `infrastructure/` directly

**Estimated effort:** 3-4 days, zero behavior change

#### Medium priority (usability)

**Issue 2: Scattered factories** — `get_redis_client`, `get_event_bus`, `get_cdc_client` exist but are scattered across infra subdirs.

**Fix:** Create a `core/registry.py` that aggregates factory lookups. This is already partially done via `ConnectorRegistry`.

**Effort:** 1-2 days

**Issue 3: Bridge functions are unclear about lifecycle** — `core/di/providers/health_bridge.py` etc. don't document when the underlying object is initialized.

**Fix:** Add docstrings explaining initialization timing. Already partially done.

**Effort:** 0.5 day

#### Low priority (nice-to-have)

**Issue 4: No unified config-layer documentation** — `config_profiles/*.yml` has 5 files but no single doc explains when each is used.

**Fix:** Add `config_profiles/README.md`.

**Effort:** 0.5 day

**Issue 5: DSL→infra coupling (58 imports)** — some are unavoidable (processors use clients), but check for protocol-vs-concrete-class misuse.

**Fix:** Audit each DSL processor; ensure they use `Source`/`Sink` protocols from `core/interfaces/`, not concrete classes.

**Effort:** 1-2 days

### What NOT to do (anti-recommendations)

- **DON'T** rewrite chaos probes with chaostoolkit (S168 decision is documented)
- **DON'T** move all `infrastructure/` to `core/` (would create a god-class module)
- **DON'T** add a separate "facade" layer (over-engineering for 20 bridges)
- **DON'T** change import paths in services (zero regression is required)

### Plan summary (sorted by ROI)

| # | Action | Effort | Risk | Value | Regression? |
|---|---|---|---|---|---|
| 1 | Move DTOs/Protocols from infra to core (Phase 1) | 2 days | Low | High | No (refactor only) |
| 2 | Replace `__getattr__` with explicit imports (Phase 2) | 1 day | Low | Medium | No (mechanical) |
| 3 | Add CI check for core/infra separation (Phase 3) | 1 day | None | High | No |
| 4 | Aggregate factories in core/registry.py | 1-2 days | Low | Medium | No |
| 5 | Add lifecycle docstrings to bridge functions | 0.5 day | None | Low | No |
| 6 | Write config_profiles/README.md | 0.5 day | None | Low | No |
| 7 | Audit DSL→infra coupling (replace concrete with protocol) | 1-2 days | Medium | Medium | No |

**Total effort:** 7-9 days | **Total risk:** Low (all refactor, no behavior change) | **Total value:** High (proper clean architecture)

## 8. Key Recommendations (top 3)

1. **Stop the `__getattr__` pattern (Issue 1)** — replace with explicit imports. The current pattern is "technically works" but obscures the architecture. 3 days, zero risk.

2. **Add a CI check** that fails the build if `core/` imports from `infrastructure/` or `services/`. 1 day, prevents regression.

3. **Audit DSL→infra (58 imports)** — ensure DSL processors use `Source`/`Sink` Protocols, not concrete classes. 1-2 days, prevents tight coupling in DSL.

## 9. Validation

- `ruff check src/` — All checks passed
- `make check-docstrings MAX_ALLOWED=0` — 0 missing, exit 0
- `git log --oneline | wc -l` — 1053 commits
- All audits completed without regressions
