# ADR-0270: Sprint 50 Plan + S13 Phase 2b Middleware Wiring (cycle 276)

> **Status**: ACCEPTED.
> **Sprint**: 50 (S49 handoff).
> **Goal**: S13 Phase 2b — wire CircuitBreakerMiddleware to use
> BreakerPolicyAdapter when feature flag enabled.

## 0. Sprint 50 plan

| Week | Focus | Deliverable |
|---|---|---|
| **W1** | **S13 Phase 2b wiring** | Middleware uses BreakerPolicyAdapter when flag ON |
| W2 | S13 Phase 2c deprecation | Remove `_legacy_states` from middleware (after W1 verified) |
| W3 | OWASP external status ADR | Document mobile_jwt_enabled flip dependencies |
| W4 | Multi-pod breaker tests + S50 retro + cross-sprint analysis | Parent agent (swarm unreliable) |

## 1. Phase 2b scope (this cycle)

### 1.1 Goal

Modify `entrypoints/middlewares/circuit_breaker.py` to optionally use
`BreakerPolicyAdapter` for state management when
`circuit_breaker_use_registry` flag is ON.

### 1.2 Changes

1. `CircuitBreakerMiddleware.__init__` reads feature flag
2. When flag ON: initialize `BreakerPolicyAdapter` lazily
3. `_get_state(route)` returns adapter view when flag ON, else legacy
4. `_record_failure(route, policy)` delegates to adapter when flag ON
5. `_record_success(route)` delegates to adapter when flag ON
6. When flag OFF: existing behavior unchanged (legacy `_legacy_states`)
7. Tests: both paths produce same observable behavior

### 1.3 Safety

- Default flag OFF = existing behavior unchanged
- All existing middleware tests pass (no regression)
- Feature flag enables gradual rollout (dev → staging → prod)

### 1.4 What Phase 2b does NOT do

- Does NOT remove `_legacy_states` (that's Phase 2c)
- Does NOT remove `_sliding_breakers` (separate concern)
- Does NOT add multi-pod tests (Phase 3, S50 W4)
- Does NOT add Redis UOW (already in BreakerRegistry since S48 W1)

## 2. Verification slice

- [ ] `make lint && make type-check` passes
- [ ] New tests for adapter-backed middleware path
- [ ] Existing middleware tests pass (backward compat)
- [ ] Feature flag verified OFF by default

## 3. References

- ADR-0268 — S13 Phase 2 investigation + 4-phase plan
- ADR-0269 — Phase 2a BreakerPolicyAdapter foundation
- `src/backend/entrypoints/middlewares/circuit_breaker.py:1-356` — current middleware
- `src/backend/core/resilience/breaker_policy_adapter.py` — adapter (cycle 273)
