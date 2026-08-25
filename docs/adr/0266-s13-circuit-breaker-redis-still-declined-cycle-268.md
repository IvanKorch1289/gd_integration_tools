# ADR-0266: S13 Circuit Breaker Redis — still DECLINED (cycle 268)

> **Status**: REAFFIRMS ADR-0251 (DECLINED).
> **Method**: Direct re-read of `core/resilience/breaker.py:155-180` +
> `purgatory` API.
> **Conclusion**: S13 still requires proper ceremony, not a code change
> in a single sprint slice.

## 0. Why DECLINED again

Per ADR-0251 (originally Sprint 45 S43 decision):
1. **DI/lifecycle**: `BreakerRegistry.__init__` hardcodes `AsyncCircuitBreakerFactory()`
   with in-memory UOW. To switch to Redis, factory needs lazy init + RedisSettings
   access. BreakerRegistry is module-level singleton, RedisSettings requires async init.
2. **Middleware coupling**: 4 separate CB implementations (`breaker.py`,
   `middleware.py`, `client_breaker.py`, `circuit_breakers.py`) need consolidation
   onto `BreakerRegistry`. Per audit DEEP-AUDIT-2026-06-22 §10: "640-line middleware
   not wired to retry packages".
3. **No multi-pod test coverage**: Existing tests are single-process in-memory.
4. **Audit trail gap**: BreakerRegistry publishes state changes; middleware
   state changes are NOT published (inconsistent observability).

## 1. Verifying the situation (cycle 268)

```
$ grep -n "class BreakerRegistry\|AsyncInMemoryUnitOfWork\|AsyncRedisUnitOfWork" \
       src/backend/core/resilience/breaker.py
157:class BreakerRegistry:
289:def get_breaker_registry() -> BreakerRegistry:
(no AsyncRedisUnitOfWork references — confirms still in-memory)
```

`BreakerRegistry.__init__` (line 160):
```python
def __init__(self) -> None:
    self._factory = AsyncCircuitBreakerFactory()  # ← no Redis wiring
    self._breakers: dict[str, Breaker] = {}
    self._factory.add_listener(self._on_event)
```

## 2. What ceremony would look like

For S13 to be DONE in a future cycle, the following must happen in order:

### Phase 1: Foundation (1 cycle, 4-6h)

1. Add `BreakerRegistry.__init__(self, *, redis_url: str | None = None)`
2. Lazy factory init: if `redis_url` provided, use `AsyncRedisUnitOfWork(redis_url)`
3. Update `get_breaker_registry()` to accept optional `redis_url` parameter
4. Add `get_breaker_registry(redis_url=...)` factory + DI integration
5. **Tests**: in-memory vs Redis produce same break/recover behavior

### Phase 2: Middleware consolidation (1 cycle, 4-6h)

1. Refactor `entrypoints/middlewares/circuit_breaker.py` to use `BreakerRegistry.get_or_create(route)`
2. Remove `RouteBreakerState` dict from middleware
3. **Tests**: HTTP request → breaker open on N failures → middleware rejects subsequent
4. Verify metrics emission works (single source: BreakerRegistry listeners)

### Phase 3: Multi-pod validation (1 cycle, 2-4h)

1. Integration test with 2 app instances pointing to same Redis
2. Verify pod A opens breaker → pod B sees open state
3. Verify race conditions handled (purgatory's atomic ops)

### Phase 4: Deployment (1 cycle, 1-2h)

1. Dev environment: enable Redis CB
2. Staging: enable Redis CB, monitor for 1 week
3. Prod: enable Redis CB via feature flag, gradual rollout

**Total**: 4 cycles (~12-18h work + 1 week staging observation)

## 3. Risk if attempted prematurely

| Risk | Impact |
|---|---|
| Async init in singleton | All pods may fail to start (no fallback) |
| Middleware coupling introduces new state | Production behavior change in security-critical path |
| Multi-pod race conditions | Data loss or split-brain scenarios |
| Audit trail inconsistency | Observability gap, debugging difficult |

Per AGENTS.md "Не упрощать валидацию на границах доверия" — production
state-changing infrastructure requires the ceremony above.

## 4. Alternative paths

If S13 cannot wait 4 cycles, consider:
1. **Read-only Redis mirror** (1-2 cycles, low risk): Keep in-memory as
   source-of-truth, async-mirror state to Redis for cross-pod visibility
   (eventual consistency). Does NOT solve race conditions but enables
   monitoring.
2. **Stick with in-memory** (current state): Accept multi-pod state
   divergence. Document as known limitation.
3. **External CB service** (1-2 cycles, medium risk): Run sidecar
   like `resilience4j-prometheus` or Envoy's `circuit_breakers` filter
   for HTTP-level CB, leave in-app CB for backend calls.

## 5. Recommendation

**Defer S13 to S48+** with explicit ceremony plan (above). In S47 W4
retro, surface this as a known high-effort item.

## 6. References

- `src/backend/core/resilience/breaker.py:155-298` — current state
- `docs/adr/0251-s13-circuit-breaker-shared-state.md` — original DECLINED
- DEEP-AUDIT-2026-06-22 §10 — original audit finding
