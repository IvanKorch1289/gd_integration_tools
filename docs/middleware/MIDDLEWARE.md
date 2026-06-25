# Middleware Guide (Sprint 171 — M5)

> **For all engineers:** middleware architecture, scaffolding, and the new
> centralization helpers (TimeoutHelper, RetryPolicyHelper, StreamingBodyHash,
> ObservabilityMiddleware).

## Inventory

The project has **30+ ASGI middleware** wired via `MiddlewareRegistry`
(see `src/backend/entrypoints/middlewares/registry.py`) and **3 DSL
middleware** (TimeoutMiddleware, ErrorNormalizerMiddleware, MetricsMiddleware)
at `src/backend/dsl/engine/middleware.py`.

### ASGI middleware (Layer 1-4)

| Layer | Range | Purpose |
|-------|-------|---------|
| 1 — early exit | 0-249 | Blocked routes, admin IP allowlist, blocked auth methods |
| 2 — request mgmt | 250-499 | Correlation ID, request context, request body cache, idempotency, timeout |
| 3 — body/auth | 500-749 | Auth required, API key, data masking, PII response, request body cache, response cache, circuit breaker, rate limits |
| 4 — logging/metrics | 750-999 | Audit log, admin audit, OTel, Prometheus, request log |

### DSL middleware (per-route via `RouteBuilder`)

- `TimeoutMiddleware(op, timeout_s)` — per-route timeout
- `ErrorNormalizerMiddleware(normalizer)` — convert exception → user-friendly
- `MetricsMiddleware(metric_name)` — emit metric per invocation

## Scaffolding (D136)

Generate a new ASGI middleware via Makefile target:

```bash
make new-middleware NAME=request_signature ARGS="--layer 2 --description 'Verify HMAC signature'"
```

This creates:
- `src/backend/entrypoints/middlewares/request_signature.py` — class scaffold
- `tests/unit/entrypoints/middlewares/test_request_signature.py` — test scaffold

Layer-aware default order (1: 0-249, 2: 250-499, 3: 500-749, 4: 750-999).

## Centralization helpers (M5 — Sprint 171)

| Helper | Purpose | Replaces |
|--------|---------|----------|
| `core.utils.timeout_helper.with_timeout` | `asyncio.wait_for` wrapper with structured logging | 8+ scattered uses |
| `core.utils.timeout_helper.async_timeout` | async context manager (soft deadline) | inline `try: asyncio.wait_for` blocks |
| `core.utils.retry_helper.retry_async` | tenacity retry with logging | inline `for attempt in range(max)` loops |
| `entrypoints.middlewares._body_hash.payload_hash` | sha256 hexdigest for in-memory bytes | 4× duplicates (audit_log, admin_audit, response_cache, data_masking) |
| `entrypoints.middlewares._body_hash.etag_hash` | RFC 7232 ETag format | response_cache.py:61 |
| `entrypoints.middlewares._streaming_hash.StreamingBodyHasher` | incremental sha256 for streaming responses | OOM risk in data_masking.py for SSE/large files |
| `entrypoints.middlewares._streaming_hash.hash_stream` | async iterator hashing | n/a |
| `entrypoints.middlewares.observability.ObservabilityMiddleware` | facade for OTel + Prometheus + Audit | facade over 3 existing middlewares (not a replacement) |

### Usage examples

```python
# TimeoutHelper
from src.backend.core.utils.timeout_helper import with_timeout

async def fetch_data():
    return await http.get(...)

data = await with_timeout(
    fetch_data(),
    timeout=5.0,
    op="http.fetch",
    slow_threshold=2.0,  # log warning if >2s
)

# RetryPolicyHelper
from src.backend.core.utils.retry_helper import retry_async

async def flaky_db_query():
    return await db.execute(...)

result = await retry_async(
    flaky_db_query,
    max_attempts=5,
    base_delay=0.5,
    retryable=(ConnectionError, asyncio.TimeoutError),
    op="db.query",
)

# StreamingBodyHash for SSE / large responses
from src.backend.entrypoints.middlewares._streaming_hash import StreamingBodyHasher

hasher = StreamingBodyHasher()
async for chunk in response.body_iterator:
    hasher.update(chunk)
etag = hasher.etag()
```

## Patterns (D-rules)

- **D136**: `make new-middleware NAME=foo [--layer 1-4]` scaffolds new middleware
- **D137**: body-hash centralization in `entrypoints.middlewares._body_hash`
- **D138**: INN validation single source via `dsl.helpers.banking.validate_inn`
- **D139**: TimeoutHelper — thin wrapper over `asyncio.wait_for`
- **D140**: RetryPolicyHelper — thin wrapper over `tenacity.AsyncRetrying`
- **D141**: StreamingBodyHash — incremental sha256 wrapper
- **D142**: ObservabilityMiddleware facade — opt-in (all 3 channels default False)

## Adding a new middleware

1. Generate scaffold: `make new-middleware NAME=your_name ARGS="--layer N --description '...'"`
2. Implement `dispatch()` in the generated file
3. Add tests in the generated `test_your_name.py`
4. Register in `setup_middlewares.py` via `registry.register(...)` with explicit `order`
5. Run: `make lint && make type-check && make test`
6. Update this document with a row in the inventory table

## See also

- `src/backend/entrypoints/middlewares/registry.py` — MiddlewareRegistry
- `src/backend/entrypoints/middlewares/setup_middlewares.py` — built-in registrations
- `src/backend/dsl/engine/middleware.py` — DSL middleware base classes
- `src/backend/dsl/builders/base/middleware_mixin.py` — fluent builder integration
