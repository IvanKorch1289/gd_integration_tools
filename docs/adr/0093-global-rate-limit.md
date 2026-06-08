# ADR-0093: Global rate-limit (formalize existing production-ready implementation)

**Date:** 2026-06-08
**Status:** Accepted (S69 W1 — formalize decision, S66 W1 backlog)
**Sprint:** S69
**Deciders:** core/net team
**Supersedes:** — (formalizes W14.1.C + Sprint 6-9 rate-limit work)
**Related:** ADR-0051, unified_rate_limiter.py, global_ratelimit.py

## Context

Backlog S66-W1: "Rate-limit global" (от роевого анализа V22).
Подразумевалось что global rate-limit отсутствует или не покрывает
все протоколы.

Audit проведён 2026-06-08 — **Global rate-limit ALREADY PRODUCTION-READY**
(920 LOC, 6 модулей).

**Components (verified wc -l):**
```
src/backend/infrastructure/resilience/unified_rate_limiter.py        141 LOC
src/backend/entrypoints/middlewares/global_ratelimit.py              395 LOC
src/backend/core/resilience/rate_limiter.py                           71 LOC
src/backend/core/resilience/_pyrate_compat.py                        113 LOC (pyrate-limiter)
src/backend/services/execution/middlewares/rate_limit_middleware.py  139 LOC (W14.1.C)
src/backend/entrypoints/dependencies/rate_limit.py                    61 LOC
Total:                                                                920 LOC
```

**Plus:**
* `dsl/blueprints/rate_limit_burst.yaml` — declarative burst-limit policy
* `core/interfaces/ratelimit_gateway.py` — Protocol interface
* `infrastructure/observability/grafana/slo_burn_rate.json` — Grafana dashboard
* `infrastructure/resilience/distributed_rl_cluster.py` — cluster-wide RL
* `infrastructure/resilience/rate_limiter.py` — base RateLimiter Protocol
* `core/config/services/resilience.py` — config

## Decision

Признать Global rate-limit PRODUCTION-READY. Реализация W14.1.C +
Sprint 6-9 закрыта.

**Features (verified в unified_rate_limiter.py):**
* **Multi-instance safety** — все токены в Redis (atomic INCR/EXPIRE)
* **Multi-strategy** — Per-API-key, Per-IP, Per-action, Global fallback
* **Token bucket** — primary algorithm
* **Exception type** — `RateLimitExceeded(limit, window, retry_after)`
* **Integration** — `BaseEntrypoint.dispatch()` + FastAPI middleware
* **Cluster mode** — `distributed_rl_cluster.py` для multi-pod coordination
* **pyrate-limiter compat** — `_pyrate_compat.py` для drop-in использования
  community-стандарта (libraries > custom per S58 W1 LESSON)
* **Declarative** — `rate_limit_burst.yaml` blueprint
* **Configurable** — `core/config/services/resilience.py` per-route/per-action

**Usage pattern:**
```python
limiter = get_rate_limiter()  # Redis-backed
limit = RateLimit(limit=100, window=60)  # 100 req/min
if not await limiter.check(identifier="api_key:abc123", limit=limit):
    raise RateLimitExceeded(
        limit=limit.limit, window=limit.window, retry_after=60
    )
```

## Consequences

### Positive

* Все протоколы покрыты: REST, SOAP, gRPC, GraphQL, WebSocket, SSE,
  MQTT, MCP[FastMCP], CDC, FileWatcher (через BaseEntrypoint.dispatch())
* Multi-instance safety: cluster-wide limits работают (Redis atomic)
* Per-action metadata (`ActionMetadata.rate_limit`) — declarative
  per-endpoint limits через `rate_limit_middleware.py`
* Grafana SLO burn-rate dashboard — observability из коробки
* pyrate-limiter integration — community standard (libraries > custom)

### Negative

* Redis required (нет in-memory fallback для production)
* 920 LOC distributed — много модулей, нужно знать public API
* Per-action metadata нуждается в registry population

### Neutral

* RateLimitExceeded exception type — recoverable=True, code=rate_limited
* Per-tenant isolation — через `identifier="tenant:api_key:..."` pattern

## Implementation Status

| Component | Status | Location |
|-----------|--------|----------|
| `RedisRateLimiter` (token bucket) | DONE | infrastructure/resilience/unified_rate_limiter.py |
| `get_rate_limiter()` factory | DONE | infrastructure/resilience/unified_rate_limiter.py |
| `RateLimitExceeded` exception | DONE | infrastructure/resilience/unified_rate_limiter.py |
| `BaseEntrypoint.dispatch()` integration | DONE | entrypoints/middlewares/global_ratelimit.py |
| FastAPI middleware | DONE | entrypoints/middlewares/global_ratelimit.py |
| `RateLimitMiddleware` (ActionMetadata) | DONE | services/execution/middlewares/rate_limit_middleware.py |
| pyrate-limiter compat | DONE | core/resilience/_pyrate_compat.py |
| `RateLimit` dataclass | DONE | core/resilience/rate_limiter.py |
| `rate_limit_burst.yaml` blueprint | DONE | dsl/blueprints/rate_limit_burst.yaml |
| `ratelimit_gateway` Protocol | DONE | core/interfaces/ratelimit_gateway.py |
| `distributed_rl_cluster` (multi-pod) | DONE | infrastructure/resilience/distributed_rl_cluster.py |
| Grafana SLO dashboard | DONE | observability/grafana/slo_burn_rate.json |
| Per-tenant rate-limit override через DSL | TODO | out of scope (S67 backlog) |
| Adaptive rate-limit (per tenant load) | TODO | out of scope |
| Rate-limit admin UI (Streamlit) | TODO | out of scope |

## References

* `src/backend/infrastructure/resilience/unified_rate_limiter.py` (141 LOC)
* `src/backend/entrypoints/middlewares/global_ratelimit.py` (395 LOC)
* `src/backend/core/resilience/rate_limiter.py` (71 LOC)
* `src/backend/core/resilience/_pyrate_compat.py` (113 LOC)
* `src/backend/services/execution/middlewares/rate_limit_middleware.py` (139 LOC)
* `src/backend/entrypoints/dependencies/rate_limit.py` (61 LOC)
* `src/backend/dsl/blueprints/rate_limit_burst.yaml`
* `src/backend/core/interfaces/ratelimit_gateway.py`
* `src/backend/infrastructure/observability/grafana/slo_burn_rate.json`
* W14.1.C: original rate_limit_middleware sprint
* Sprint 6-9: global rate-limit baseline
* S58 W1 LESSON: libraries > custom (pyrate-limiter chosen)
