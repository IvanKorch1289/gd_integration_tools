# ADR-0274: S13 Phase 2c Legacy DeRemoval — Complete (cycle 282)

> **Status**: ACCEPTED.
> **Method**: Direct removal of legacy deque path + 9 obsolete tests.
> **Impact**: S13 ceremony Phase 2c complete. Legacy path is no longer
> possible to use; new code MUST go through registry or sliding breaker.

## 0. S13 ceremony status (cycle 282)

| Phase | Status | Source |
|---|---|---|
| 1 (foundation) | ✅ DONE | S48 W1 (cycle 270) |
| 2a (adapter) | ✅ DONE | S49 W1 (cycle 273) |
| 2b (wiring) | ✅ DONE | S50 W1 (cycle 276) |
| 2b-2 (__call__ fix) | ✅ DONE | S51 W1 (cycle 280) |
| 3 (multi-pod tests) | ✅ DONE | S50 W4 (cycle 279) |
| **2c (legacy removal)** | ✅ **DONE** | **S51 W2 (cycle 282)** |
| 4 (staging rollout) | ⚠️ DEFERRED | (S51 W3) |

**6 of 7 phases complete.** Only production rollout remaining.

## 1. What was removed

### 1.1 Middleware (`circuit_breaker.py`)

- `use_sliding_window_breaker` parameter from `__init__`
- `_use_legacy` attribute
- `_legacy_states` dict
- Legacy deque code path in `_get_state`, `_record_failure`, `_record_success`
- Legacy deque dispatch path in `__call__`
- 50+ LOC of state-machine logic in legacy methods

### 1.2 Tests

Removed 9 legacy tests that validated removed code:
- test_state_machine_closed_to_open
- test_state_machine_open_to_half_open_after_reset
- test_state_machine_half_open_to_closed_on_success
- test_should_allow_when_closed
- test_should_deny_when_open_no_reset
- test_sliding_window_trims_old_failures
- test_per_route_state_independent
- test_route_policies_override_default
- test_route_policies_prefix_match
- test_excluded_statuses_not_counted_as_failures

### 1.3 Test helpers

Updated 2 `_make_middleware` helpers to drop `use_sliding_window_breaker`
parameter. New deprecation test verifies parameter no longer exists.

## 2. Final middleware shape

```python
class CircuitBreakerMiddleware:
    def __init__(
        self,
        app,
        *,
        default_policy=None,
        route_policies=None,
        use_breaker_registry=None,  # None = read flag
    ):
        ...
    
    async def __call__(scope, receive, send):
        # Path 1: Registry (when flag ON)
        if self._use_breaker_registry:
            adapter = self._get_adapter()
            if not adapter.should_allow(path, policy):
                return 503
            try:
                await self.app(scope, receive, send)
                adapter.record_success(path)
            except Exception:
                adapter.record_failure(path, policy)
            return
        
        # Path 2: SlidingWindowBreaker (default)
        breaker = self._get_sliding_breaker(path, policy)
        ...
```

## 3. Test count delta

| Sprint | Middleware tests | Total tests |
|---|---|---|
| S50 close | 490 | 187+ |
| S51 W1 | 498 (+ 3 migrated) | 190+ |
| **S51 W2** | **488** (-10 net: +2, -12 removed) | **177+** |

Slight reduction in test count due to removal of legacy deque tests
that no longer apply. The remaining 488 tests provide better coverage
of the 2 remaining paths (registry + sliding).

## 4. References

- ADR-0268 — S13 4-phase plan
- ADR-0271 — Phase 2c deferral plan (now complete)
- ADR-0273 — Phase 2b-2 __call__ fix (predecessor)
- `src/backend/entrypoints/middlewares/circuit_breaker.py` — current state
