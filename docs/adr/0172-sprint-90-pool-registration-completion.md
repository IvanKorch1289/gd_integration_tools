# ADR-0172: Sprint 90 — Pool Registration Completion (V3 #5)

**Status:** Accepted
**Date:** 2026-06-12
**Sprint:** 90
**Author:** Assistant (autonomous cycle)

## Context

FINAL_REPORT_V3 (2026-06-12) identified **V3 #5 OPEN**: not all backend
pools are registered in `PoolHealthMonitor` / `UnifiedPoolManager`. The
report listed MongoDB / Elasticsearch / Redis / S3 / HTTP as unregistered.

## Re-verification findings

Direct inspection of `_register_pools_in_unified_manager` in
`src/backend/plugins/composition/setup_infra/pools.py` (2026-06-12):

| Pool | Registered | Sprint | Note |
|------|-----------|--------|------|
| `db_main` (PG) | ✅ | S60 W3 | `pools.py:47` |
| `redis_cache` | ✅ | S60 W3 | `pools.py:67` |
| `s3_main` | ✅ | S60 W3 | `pools.py:81` |
| `clickhouse_main` | ✅ | S60 W3 | `pools.py:93` |
| `litellm_main` | ✅ | S80 W2 | `pools.py:113` |
| **`mongodb_main`** | ❌ → ✅ | **S90 W1** | NEW: `pools.py:104-114` |
| **`elasticsearch_main`** | ❌ → ✅ | **S90 W2** | NEW: `pools.py:116-126` |
| Kafka (aiokafka producer) | ⏸ deferred | S91+ | DI-injected, no central accessor |
| NATS (jetstream) | ⏸ deferred | S91+ | Per-component connections, not singleton |
| HTTP (httpx) | N/A | — | Connection pool per-request, not centralised |

**V3 audit was 80% accurate** (MongoDB, Elasticsearch confirmed unregistered),
**20% outdated** (Redis, S3 already registered by S60 W3 — V2 audit also missed
this fact; this is the same V2/V3 misreport pattern that affected #9 branch).

## Decision

### S90 W1+W2: register MongoDB and Elasticsearch pools

**Pattern follows existing S60 W3 + S80 W2:**

1. Add `_mongo_enabled()` / `_es_enabled()` guards backed by
   `settings.mongo.enabled` / `settings.elasticsearch.enabled` (default
   `True` for mongo, `False` for es — matches the underlying client
   defaults).
2. Inside the registration function, wrap each `manager.register(...)`
   call in `try/except Exception` so a missing backend never crashes
   startup — this is the established fault-tolerance pattern.
3. Use the existing `ping()` method on each client (MongoDB:
   `client.admin.command("ping")`, ES: `client.ping()`). Both return
   `bool` and swallow network errors internally.

### S90 W3: Kafka registration deferred

Kafka producer is **per-component DI injection** (e.g. `KafkaDLQWriter.__init__(producer=...)`).
Centralised registration would require:
- A new singleton accessor (`get_kafka_producer()`) in composition root
- A lifecycle hook to start/stop the producer
- A health-check strategy for `aiokafka` (no native ping; would need
  cluster metadata fetch or cluster probe)

This is **architectural scope** (not a wiring fix) and is tracked
as S91+ follow-up. The current DLQ usage continues to work.

### S90 W3: NATS registration deferred

NATS clients (jetstream producers/consumers) are created **per-component**
in `nats_jetstream.py` and `nats_writer.py` — no central singleton.
Same justification as Kafka: would require a new accessor and
lifecycle hook. Deferred to S91+.

### HTTP not considered a "pool"

`httpx.AsyncClient` uses a per-request connection pool managed by the
client itself. There's no separate backend connection to register. The
httpx instances live in the transport layer (`http_httpx.py`,
`http_upstream.py`) and don't fit the `PoolHealthMonitor` model.

## Consequences

### Positive

- 7/9 backend connection pools now registered in `UnifiedPoolManager`:
  - `db_main`, `redis_cache`, `s3_main`, `clickhouse_main`, `litellm_main`,
    **`mongodb_main`**, **`elasticsearch_main`**.
- 3 NEW regression tests (S90 W4) verify registration logic.
- No new abstractions: follows the established pattern (S60 W3).

### Negative / Limitations

- 2/9 backend pools deferred (Kafka, NATS) — will need architectural work
  in S91+ to add a central accessor + lifecycle hooks.
- HTTP transport not registered (by design, see Decision above).

### Risk

- The MongoDB registration `try/except` means a broken MongoDB connection
  will be silently logged at debug level and skipped. This is the
  same fault-tolerance as the existing S60 W3 code path. If strict
  fail-on-startup is required, the `_mongo_enabled()` guard should
  return `False` and the operator should set `settings.mongo.enabled=False`
  explicitly.

## Alternatives Considered

### A) Refactor `_register_pools_in_unified_manager` into a registry pattern

Each pool type would register a `PoolFactory` (with enablement check,
accessor, ping callable) into a central registry, and the function
would iterate over it.

**Rejected**: Adds an abstraction layer for 7 pools with 4 different
shapes (PG, Redis, S3, ClickHouse, LiteLLM, Mongo, ES). The current
`if _enabled(): try: manager.register(...) except: log.debug(...)`
pattern is 14 lines per pool, all in one place, easy to read.

### B) Use `aiokafka` cluster probe as Kafka ping

Could use `producer.client.fetch_all_metadata()` or a similar call to
verify connectivity. But this:
1. Requires the producer to be started (post-`await producer.start()`),
   which currently happens lazily in DLQ writers.
2. Adds network overhead on every health tick (30s interval).

**Rejected for S90**: needs architectural decision first (where does
the producer live, when does it start). Deferred to S91+ as part of
the broader Kafka centralisation work.

## References

- `_register_pools_in_unified_manager`: `src/backend/plugins/composition/setup_infra/pools.py`
- Settings: `src/backend/core/config/mongo.py`, `src/backend/core/config/elasticsearch.py`
- Clients: `src/backend/infrastructure/clients/storage/mongodb.py`, `src/backend/infrastructure/clients/storage/elasticsearch.py`
- V3 report section "V3 #5 OPEN" (FINAL_REPORT_V3.md, 2026-06-12)
- Related: ADR-0140 (S60 W3 — original pool registration), ADR-0159 (S80 W2 — LiteLLM registration)
