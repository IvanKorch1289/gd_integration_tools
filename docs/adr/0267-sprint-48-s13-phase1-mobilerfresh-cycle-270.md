# ADR-0267: Sprint 48 Plan + S13 Phase 1 Foundation (cycle 270)

> **Status**: ACCEPTED.
> **Sprint**: 48 (S47 complete retro handoff).
> **Goal**: S13 Circuit Breaker Phase 1 — lazy factory init + Redis UOW support.

## 0. Sprint 48 plan

| Week | Focus | Deliverable |
|---|---|---|
| **W1** | **S13 Phase 1 Foundation** | BreakerRegistry lazy factory init + optional Redis UOW + tests |
| W2 | Mobile JWT refresh token endpoint | `/mobile/v1/auth/refresh` + tests |
| W3 | S13 Phase 2 (middleware consolidation) | Refactor `entrypoints/middlewares/circuit_breaker.py` |
| W4 | Multi-pod breaker tests + S48 retro + swarm | Cross-pod integration tests + comprehensive retro |

## 1. Phase 1 scope (this cycle)

### 1.1 Goal

Make `BreakerRegistry` capable of using either in-memory OR Redis-backed
breaker state, controlled by configuration. Default behavior unchanged
(in-memory) — Redis is opt-in via env var.

### 1.2 Changes

1. `BreakerRegistry.__init__` accepts optional `uow_factory` callable
2. New `RedisBreakerUOW` wrapper class around `purgatory.AsyncRedisUnitOfWork`
3. `get_breaker_registry()` factory takes optional `redis_url` parameter
4. Feature flag `breaker_redis_enabled` (default OFF)
5. Tests: in-memory vs Redis produce same break/recover behavior (mocked Redis)

### 1.3 Why NOT full Phase 2/3 in this cycle

Per AGENTS.md Ponytail skill — security/observability infra needs ceremony.
Phase 1 ships the foundation. Phase 2 (middleware) + Phase 3 (multi-pod
tests) need their own cycles to avoid scope creep.

### 1.4 Backward compatibility

- `get_breaker_registry()` with no args = current behavior (in-memory)
- Existing 15+ infrastructure clients continue to work unchanged
- New Redis path is opt-in via `get_breaker_registry(redis_url=...)`

## 2. Verification slice

- [ ] `make lint && make type-check` passes
- [ ] New tests for `RedisBreakerUOW` (mocked Redis client)
- [ ] Existing tests still pass (no regression)
- [ ] Feature flag verified default OFF

## 3. References

- ADR-0266 — S13 CB Redis still DECLINED (reaffirmed in S47)
- ADR-0251 — original DECLINED + ceremony plan
- `src/backend/core/resilience/breaker.py:155-298` — current BreakerRegistry
- `src/backend/core/auth/jwt_blacklist.py` — reference impl for Redis-backed store
