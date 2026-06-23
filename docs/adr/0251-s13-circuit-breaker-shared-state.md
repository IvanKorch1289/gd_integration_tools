# ADR-0251 — S13: Circuit Breaker Middleware → Shared State

**Дата**: 2026-06-22
**Sprint**: 46 (proposed)
**Status**: 🔴 DECLINED — K8s multi-pod safety requires Redis, but wiring `BreakerRegistry` to Redis needs architectural ceremony before deployment
**Risk**: HIGH — production multi-pod safety; incorrect fix can cause all pods to open circuits simultaneously

---

## Context

DEEP-AUDIT-2026-06-22 §10 reported:
> CircuitBreaker shared state: Each of the 4 retry packages maintains its own CB state → multi-pod K8s: pod A opens CB, pods B/C don't know → continue sending requests. Middleware at `core/resilience/circuit_breaker/middleware.py` (640 lines) not wired to retry packages.

After full investigation (S13 audit, 2026-06-22):

### What exists

**4 circuit breaker implementations:**

| File | LOC | Scope | State storage | Used by |
|---|---|---|---|---|
| `core/resilience/breaker.py` | 245 | Canonical (`purgatory`) | In-memory (`AsyncInMemoryUnitOfWork`) | 15+ infrastructure clients |
| `entrypoints/middlewares/circuit_breaker.py` | 238 | HTTP middleware | In-memory `dict[route, RouteBreakerState]` | FastAPI app |
| `infrastructure/resilience/client_breaker.py` | 92 | Per-client wrapper | Delegates to `core/breaker.py` | HTTP/Redis/DB clients |
| `infrastructure/clients/external/circuit_breakers.py` | 63 | Registry adapter | Delegates to `core/breaker.py` | Legacy callsites |

**Key finding**: `core/resilience/breaker.py` already has:
- `BreakerState` dataclass (ready for Redis serialization)
- `AsyncRedisUnitOfWork` support (`purgatory` built-in, URL-based)
- `@lru_cache(maxsize=1)` singleton `get_breaker_registry()`
- 15+ production consumers (HTTP, gRPC, FTP, SFTP, Kafka, DB, Graylog)

**The actual problem is narrower**: `CircuitBreakerMiddleware` uses its own in-memory `RouteBreakerState` dict, NOT `BreakerRegistry`. In K8s multi-pod:
- Pod A's middleware: 5 failures → circuit OPEN
- Pod B/C: still CLOSED (independent dict) → continue sending

### What purgatory provides

```python
# Redis backend — ALREADY AVAILABLE in purgatory 3.0.1
from purgatory import AsyncCircuitBreakerFactory, AsyncRedisUnitOfWork

factory = AsyncCircuitBreakerFactory()
factory.uow = AsyncRedisUnitOfWork("redis://redis-prod:6379/0")  # single line
```

`BreakerRegistry.__init__` hardcodes `AsyncInMemoryUnitOfWork()`. Needs lazy init to read `RedisSettings`.

### Dev vs Prod profiles

| Profile | Redis | Behavior |
|---|---|---|
| `dev_light` | **disabled** (`enabled=False`) | In-memory only — single process only |
| `prod` | **enabled** (`host=redis-prod`) | Redis-backed shared state |

---

## Decision: DECLINED for Sprint 46 (needs ceremony first)

**Why declined, not deferred**: The fix IS feasible (3-line change to wire `AsyncRedisUnitOfWork`). But deployment without proper ceremony is dangerous:

1. **`BreakerRegistry` initialization**: `__init__` hardcodes in-memory UOW. Need to change to lazy Redis init — requires updating `get_breaker_registry()` with settings access. This is a DI/lifecycle concern: `BreakerRegistry` is a module-level singleton created at import time, but `RedisSettings` requires async initialization.

2. **`CircuitBreakerMiddleware` coupling**: Middleware would need to call `BreakerRegistry.get_or_create(route)` — adds coupling to singleton. Currently the middleware is self-contained.

3. **No test coverage**: No tests for multi-pod CB behavior. Would need integration tests.

4. **Audit trail gap**: `BreakerRegistry._publish_metric` already publishes state changes. Middleware state changes are NOT published.

### Correct approach (S46+)

#### Phase 1: Safe, reversible — Wire BreakerRegistry → Redis (no middleware change)

```python
# core/resilience/breaker.py — add optional Redis UOW

@lru_cache(maxsize=1)
def get_breaker_registry(*, redis_url: str | None = None) -> BreakerRegistry:
    registry = BreakerRegistry()
    if redis_url:
        from purgatory import AsyncRedisUnitOfWork
        registry._factory.uow = AsyncRedisUnitOfWork(redis_url)
    return registry
```

**This alone fixes 15+ infrastructure clients** (HTTP, gRPC, FTP, etc.) — they already use `BreakerRegistry`. Multi-pod safety for infrastructure clients, zero changes to their callsites.

**Then at app startup** (composition root):
```python
# entrypoints/main.py or app factory
from src.backend.core.config.services.cache import get_redis_settings
from src.backend.core.resilience.breaker import get_breaker_registry

redis_settings = get_redis_settings()
if redis_settings.enabled:
    get_breaker_registry(redis_url=redis_settings.redis_url)
```

#### Phase 2: Middleware wiring (S47)

`CircuitBreakerMiddleware` uses `BreakerRegistry.get_or_create(route)` instead of local dict. State published through `_publish_metric` automatically.

#### Phase 3: DSL integration (S48+)

Expose `circuit_breaker(name, spec)` in DSL route builders.

---

## Why not deferred forever

The 15 infrastructure clients (HTTP, gRPC, Kafka, etc.) already use `BreakerRegistry` — wiring it to Redis is the highest-value, lowest-risk step. It fixes the majority of the multi-pod problem for the production services layer WITHOUT touching the middleware.

**Estimated effort**: 2-3 hours for Phase 1. 4-6 hours for full S13.

---

## Files impacted

| File | Change | Risk |
|---|---|---|
| `src/backend/core/resilience/breaker.py` | Add `redis_url` param to `get_breaker_registry()` | LOW — backward compat, adds optional param |
| `src/backend/entrypoints/main.py` / app factory | Wire Redis at startup | MEDIUM — lifecycle ordering |
| `src/backend/entrypoints/middlewares/circuit_breaker.py` | Replace local dict with `BreakerRegistry` | HIGH — state machine coupling |
| `tests/` | Add Redis-backed CB integration tests | HIGH — needs Redis test container |

---

## Dependencies

- Requires `RedisSettings.enabled = True` (prod/staging; dev_light = False)
- Requires `purgatory 3.0.1` (already installed)
- Requires app startup composition root access (entrypoint initialization)

---

## Status per ADR-0248

**P1** (not P0): Circuit breaker middleware is S81 W1 restore. In-memory per-route state was explicitly documented as limitation ("для prod use Redis-based"). The infrastructure clients using `BreakerRegistry` are the more critical path.

**Recommended action**: Execute Phase 1 (BreakerRegistry → Redis) in next sprint, skip middleware change, update DEEP-AUDIT-2026-06-22 §10 status to "P1, Phase 1 in progress".
