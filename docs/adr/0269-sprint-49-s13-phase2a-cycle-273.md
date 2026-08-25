# ADR-0269: Sprint 49 Plan + S13 Phase 2a Adapter (cycle 273)

> **Status**: ACCEPTED.
> **Sprint**: 49 (S48 handoff).
> **Goal**: S13 Phase 2a — BreakerPolicyAdapter bridging middleware → registry.

## 0. Sprint 49 plan

| Week | Focus | Deliverable |
|---|---|---|
| **W1** | **S13 Phase 2a (Adapter)** | `BreakerPolicyAdapter` class bridging `RouteBreakerState` ↔ `BreakerRegistry` |
| W2 | S13 Phase 2b (Feature flag) | `circuit_breaker_use_registry` flag + dual-state support in middleware |
| W3 | Mobile JWT refresh integration | /auth/refresh uses MobileJwtVerifier when mobile_jwt_enabled ON |
| W4 | Code review + cross-sprint analysis + S49 retro | Parent agent (no swarm) |

## 1. Phase 2a scope (this cycle)

### 1.1 Goal

Provide a thin adapter that exposes the existing `RouteBreakerState`
interface but backs it with `BreakerRegistry.get_or_create(route)`.
No behavior change. No middleware code modification yet (Phase 2b).

### 1.2 Adapter design

```python
class BreakerPolicyAdapter:
    """Bridge between RouteBreakerState (middleware) and BreakerRegistry.

    Phase 2a (cycle 273): shape + interface only.
    Phase 2b (W2): middleware uses this adapter when flag ON.
    """

    def __init__(self, *, registry: BreakerRegistry) -> None:
        self._registry = registry

    def get_state(self, route: str) -> RouteBreakerState:
        """Return middleware-compatible state object backed by registry."""
        breaker = self._registry.get_or_create(route)
        return RouteBreakerState.from_breaker(breaker)

    def record_failure(self, route: str, policy: BreakerPolicy) -> None:
        breaker = self._registry.get_or_create(route)
        breaker.record_failure()  # purgatory API

    def record_success(self, route: str) -> None:
        breaker = self._registry.get_or_create(route)
        breaker.record_success()
```

### 1.3 What Phase 2a does NOT do

- Does NOT modify `entrypoints/middlewares/circuit_breaker.py` (Phase 2b)
- Does NOT add feature flag (Phase 2b)
- Does NOT remove legacy `_legacy_states` (Phase 2c)
- Does NOT add multi-pod tests (Phase 3, S49 W4)

## 2. Verification slice

- [ ] `make lint && make type-check` passes
- [ ] New tests for BreakerPolicyAdapter
- [ ] Existing middleware tests pass (no regression)
- [ ] Adapter can be constructed from default registry

## 3. References

- ADR-0268 — S13 Phase 2 investigation + 4-phase rollout plan
- ADR-0266 — S13 still DECLINED (now Phase 1 done)
- ADR-0267 — Sprint 48 plan
- `src/backend/core/resilience/breaker.py:155-298` — BreakerRegistry (Phase 1 Redis support)
- `src/backend/entrypoints/middlewares/circuit_breaker.py:1-356` — middleware
