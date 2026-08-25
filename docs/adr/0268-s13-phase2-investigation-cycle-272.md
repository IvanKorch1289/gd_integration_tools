# ADR-0268: S13 Phase 2 Investigation — middleware refactor scope (cycle 272)

> **Status**: PROPOSED (not implemented this sprint).
> **Method**: Direct inspection of `circuit_breaker.py` (356 LOC).
> **Conclusion**: Phase 2 requires careful phased migration, not a single
> sprint refactor.

## 0. Scope assessment

### 0.1 Current state

| Component | LOC | Owns state? |
|---|---|---|
| `entrypoints/middlewares/circuit_breaker.py` | 356 | ✅ YES (`self._legacy_states: dict[str, RouteBreakerState]`) |
| `core/resilience/breaker.py` (BreakerRegistry) | 298 | ✅ YES (`self._breakers: dict[str, Breaker]`) |

**Two parallel breaker implementations**, both maintain per-route/per-name state.
Per DEEP-AUDIT-2026-06-22 §10: "640-line middleware not wired to retry packages"
(slight undercount; actually 356 LOC in current file).

### 0.2 Refactor would require

1. **Migrate middleware** to call `BreakerRegistry.get_or_create(route)`
   instead of maintaining its own `_legacy_states` dict
2. **Map `RouteBreakerState` semantics** to BreakerSpec fields
   (threshold, recovery_timeout, half_open_max_calls)
3. **Preserve observable behavior**:
   - 503 response on open breaker
   - `Retry-After` header on rejection
   - Per-route metrics emission
4. **Update audit trail** so middleware state changes also publish to
   `BreakerRegistry` listeners (currently only direct registry publishes)
5. **Run existing middleware tests** to verify no regression
6. **Update 15+ consumers** if they depend on middleware state shape

### 0.3 Risks

| Risk | Impact |
|---|---|
| Behavior change in security-critical middleware | Production outage |
| Test coverage gaps in middleware state machine | Silent regression |
| Multi-pod state divergence (pre-Phase 1 Redis) | Already mitigated by Phase 1 (cycle 270) |

## 1. Recommended path (NOT this sprint)

### Phase 2a: Adapter layer (2-3h)

Create `BreakerPolicyAdapter` that wraps `BreakerRegistry.get_or_create(route)`
and exposes the existing `RouteBreakerState` interface. Middleware code
unchanged but state lives in registry. **No observable behavior change.**

### Phase 2b: Feature flag migration (1-2h)

Add `circuit_breaker_use_registry: bool = False` flag. When ON, middleware
uses adapter; when OFF, existing in-memory state. Roll out gradually.

### Phase 2c: Deprecation (1-2h)

After 1 week in production with adapter, remove legacy `_legacy_states`
from middleware. State now exclusively in `BreakerRegistry`.

### Phase 2d: Tests (2-3h)

- Existing middleware tests pass (behavior preserved)
- New tests verify state lives in registry (not local dict)
- Multi-pod integration tests (Phase 3)

**Total Phase 2**: 6-10h over 1-2 sprints.

## 2. Why NOT in S48 W3

Per AGENTS.md Ponytail: "Не упрощать валидацию на границах доверия".
Middleware refactor IS a trust-boundary change. The 356-LOC middleware
is security-critical (circuit breaker rejects requests on failure).

Attempting Phase 2 in 1 session would:
- Risk behavior change in production middleware path
- Skip Phase 2a (adapter layer) which is the safe migration path
- Skip gradual rollout (Phase 2b feature flag)

**Honest scope choice**: defer Phase 2 to S49+ with proper ceremony.

## 3. What S48 W3 delivers (this commit)

This ADR documenting the investigation + recommended phased migration.
Phase 1 (foundation) and Phase 2 (middleware) foundation laid; Phase 2
refactor deferred to dedicated sprint with proper rollout plan.

## 4. References

- ADR-0267 — Sprint 48 plan (Phase 1+2 split)
- ADR-0266 — S13 still DECLINED + 4-phase plan
- ADR-0251 — original DECLINED + ceremony
- `src/backend/entrypoints/middlewares/circuit_breaker.py:1-356` — current state
- `src/backend/core/resilience/breaker.py:155-298` — BreakerRegistry (with Phase 1 Redis support)
