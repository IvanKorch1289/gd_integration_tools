# Integration Layer Guide (Sprint 171 M7)

> **Архитектура интеграционного слоя: routes, multi-protocol,
> middleware facades, per-route policies, security.**

## Архитектура

```
Route (YAML route.toml + *.dsl.yaml)  →  RouteBuilder  →  Pipeline
        ↓                                       ↓
   Plugin routes                       Multi-protocol auto-registration:
   (extensions/<name>/routes/)         REST, SOAP, WSDL, gRPC, GraphQL,
                                       AsyncAPI, WS, SSE, MCP, MQTT
        ↓
   Setup_middlewares (30+ ASGI)
   MiddlewareRegistry
   Per-route policies (.policy.*)
   Capability gates + Audit
```

## RouteBuilder (Camel-style fluent)

```python
from src.backend.dsl.builders.base import RouteBuilder

route = (
    RouteBuilder.from_("api.users.list", source="http:GET /api/users")
    .policy.rate_limit(rate=100, per_seconds=1)
    .policy.cache(ttl_seconds=60)
    .entity_list(entity="users", result_property="body.users")
    .build()
)
```

## Per-route policies (`policy_mixin.py`)

| Policy | Пример | Use case |
|--------|--------|----------|
| `cache` | `.policy.cache(ttl_seconds=60)` | Idempotent read endpoints |
| `circuit_breaker` | `.policy.circuit_breaker(threshold=5, recovery_seconds=30)` | External API calls |
| `rate_limit` | `.policy.rate_limit(rate=100, per_seconds=1)` | Public endpoints |
| `timeout` | `.policy.timeout(seconds=10)` | Slow operations |
| `retry` | `.policy.retry(max_attempts=3)` | Transient failures |
| `bulkhead` | `.policy.bulkhead(limit=10)` | Concurrent limits |
| `adaptive_timeout` | `.policy.adaptive_timeout()` | ML-based timeout |
| `idempotency` | `.policy.idempotency(ttl=86400)` | Webhook deduplication |

## Multi-protocol auto-registration (14+ protocols)

| Protocol | Directory | Notes |
|----------|-----------|-------|
| REST | `entrypoints/api/` | FastAPI |
| SOAP | `entrypoints/soap/` | SOAP server |
| WSDL | `entrypoints/soap/wsdl/` | Service description |
| gRPC | `entrypoints/grpc/` | Protocol buffers |
| GraphQL | `entrypoints/graphql/` | Graphene |
| AsyncAPI | `entrypoints/asyncapi/` | WebSocket/async |
| WebSocket | `entrypoints/stream/` | WS |
| SSE | `entrypoints/stream/` | Server-sent events |
| MCP | `entrypoints/mcp/` | Model Context Protocol |
| MQTT | `entrypoints/mqtt/` | IoT |
| HTTP/3 | `entrypoints/http3/` | QUIC |
| CDC | `entrypoints/cdc/` | Change data capture |
| email | `entrypoints/email/` | SMTP/IMAP |
| filewatcher | `entrypoints/filewatcher/` | FS events |
| scheduler | `entrypoints/scheduler/` | Cron jobs |

## Entity CRUD auto-generation

```python
# src/backend/dsl/builders/entity.py
route = (
    RouteBuilder.from_("api.users.create", source="http:POST /api/users")
    .entity_create(entity="users", payload_from="body")
    .build()
)
```

Methods: `entity_create`, `entity_get`, `entity_update`, `entity_list`, `entity_delete` (5 ops).

## Unified middleware facades (`core/facades.py`)

```python
from src.backend.core.facades import (
    AuthorizationGateway, CapabilityGate, PIITokenizer,
    UnifiedRateLimiter, get_rate_limiter,
    CircuitBreaker, circuit_breaker,
    get_cache, get_tenant_cache, get_tiered_cache,
    with_timeout, async_timeout,
    retry_async, default_retryable,
    Bulkhead, get_bulkhead,
)
```

Single import → 17 middleware primitives across 6 categories (auth, timeout, retry, rate-limit, CB, bulkhead).

## Call types (6 supported)

| Type | DSL | When |
|------|-----|------|
| sync | default | Quick operations |
| async | `async def process` (default) | Standard |
| deferred | `DeferredExecutionMixin` | Scheduled/later |
| background | `resilience_mixin.outbox` | Fire-and-forget |
| distributed | Temporal + LiteTemporalBackend | Multi-node workflows |
| multithreaded | `cpu_bound.run_cpu_bound(use_process_pool=True)` | CPU-bound tasks |

## External DB DSL

```python
# src/backend/dsl/engine/processors/db_call_procedure.py
route = (
    RouteBuilder.from_("api.calc", source="http:POST /api/calc")
    .db_call_procedure(
        profile="oracle_prod",
        name="recalc_credit_score",
        params_from="body",
        schema="public",
        result_property="body.result",
    )
    .build()
)
```

Supports: PostgreSQL, MS SQL, Oracle, MySQL, DB2.

## CDC DSL

```python
# src/backend/dsl/engine/processors/cdc_capture.py
from src.backend.dsl.engine.processors.cdc_capture import CDCCaptureProcessor

p = CDCCaptureProcessor(
    source="debezium_postgres.public.users",
    table="users",
    to="body.events",
)
```

Plus `cdc_transform.py` for event filtering/transformation.

## Directory scan DSL (M7 new)

```python
# src/backend/dsl/engine/processors/rpa/operations/directoryscanprocessor.py
from src.backend.dsl.engine.processors.rpa.operations.directoryscanprocessor import (
    DirectoryScanProcessor,
)

p = DirectoryScanProcessor(
    directory="/incoming",
    pattern="**/*.csv",
    min_size=100,
    modified_after=datetime(2026, 6, 1),
    to="body.files",
)
```

Differences from FileListProcessor: recursive (`**`), size/mtime filters, sorted.

## Security (defense in depth)

3 layers for RCE-shaped operations:
1. **HTTP**: `RpaPolicyMiddleware` (deny-by-default for `/api/v1/rpa/*`)
2. **DSL**: `required_capability` per-processor
3. **Audit**: per-processor `audit_event` + middleware logs

Plus: `AgentToolPolicy` (default-deny tool permissions), `CapabilityGate` (DSL-level gate).

## Connection pools

| Pool | File |
|------|------|
| gRPC | `infrastructure/clients/transport/grpc_pool.py` |
| IMAP | `infrastructure/clients/transport/imap_pool.py` |
| NATS | `infrastructure/clients/transport/nats_pool.py` |

## D-rules (M7)

- **D160**: Unified middleware facade pattern (`core/facades.py`)
- **D161**: Per-route DSL via `policy_mixin.py` (8 policies)
- **D162**: Multi-protocol auto-registration (14+ protocols)
- **D163**: Call type DSL (6 types)
- **D164**: External DB facade (`db_call_procedure.py`)
- **D165**: CDC DSL (`cdc_capture.py` + `cdc_transform.py`)
- **D166**: Directory scan DSL (`directoryscanprocessor.py`)

## See also

- `docs/middleware/MIDDLEWARE.md` — middleware architecture (M5)
- `docs/rpa/RPA_GUIDE.md` — RPA tools (M6)
- `docs/config/SETTINGS_GUIDE.md` — settings + Consul (M6.1)
- `docs/ai/AGENT_GUIDE.md` — agent workflow (M7)
