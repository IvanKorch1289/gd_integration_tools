# ADR-0273: S13 Phase 2b-2 __call__ Dispatch Fix (cycle 281)

> **Status**: ACCEPTED.
> **Method**: Direct verification via failed test (JSON serialization error
> revealed __call__ was bypassing registry path).
> **Impact**: Completes Phase 2b — middleware __call__ now routes through
> BreakerPolicyAdapter when flag enabled.

## 0. Background

S50 W1 (cycle 276, ADR-0270) shipped Phase 2b: middleware test API methods
(`_get_state`, `_should_allow`, `_record_failure`, `_record_success`)
delegated to BreakerPolicyAdapter when `circuit_breaker_use_registry`
flag was ON.

## 1. Bug discovered in S51 W1

During test migration (S51 W1 cycle 280), test
`test_open_circuit_returns_503` failed with:

```
TypeError: Object of type MagicMock is not JSON serializable
when serializing dict item 'state'
```

**Root cause**: `__call__` method did NOT use the registry path even when
flag was ON. It only used SlidingWindowBreaker. So when test set
`_use_breaker_registry=True` and mocked adapter to simulate OPEN state,
`__call__` still called `_get_sliding_breaker` which returned a
SlidingWindowBreaker — but the test's mocking targeted the wrong path.

## 2. Fix (cycle 280)

Added explicit registry dispatch path at top of `__call__`:

```python
if self._use_breaker_registry:
    adapter = self._get_adapter()
    if not adapter.should_allow(path, policy):
        # 503 with 'source: registry' for observability
        ...
        return
    # Allow — call upstream, record outcome
    try:
        await self.app(scope, receive, send)
        adapter.record_success(path)
    except Exception:
        adapter.record_failure(path, policy)
    return
```

## 3. Purgatory limitation (still applies)

The BreakerPolicyAdapter's `record_failure()` calls
`breaker.record_failure()` which is NOT exposed in current purgatory
version (graceful no-op with warning log per breaker_policy_adapter.py:131).
This means real production state mutation through the registry path
still depends on either:
- purgatory library upgrade (exposes public API)
- Different breaker library (e.g., pybreaker, circuitbreaker)
- Custom state tracking on top of registry

For testing purposes, the adapter is mocked to simulate OPEN state.

## 4. S13 ceremony status (cycle 281)

| Phase | Status | Source |
|---|---|---|
| 1 (foundation) | ✅ DONE | S48 W1 (cycle 270) |
| 2a (adapter) | ✅ DONE | S49 W1 (cycle 273) |
| 2b (wiring) | ✅ DONE | S50 W1 (cycle 276) |
| 2b-2 (__call__ fix) | ✅ DONE | **S51 W1 (cycle 280)** |
| 3 (multi-pod tests) | ✅ DONE | S50 W4 (cycle 279) |
| 2c (legacy removal) | ⚠️ DEFERRED | ADR-0271 (S51 W2) |
| 4 (staging rollout) | ⚠️ DEFERRED | (S51 W3) |

## 5. References

- ADR-0268 — S13 4-phase plan
- ADR-0270 — Sprint 50 plan + Phase 2b scope
- ADR-0271 — Phase 2c deferral
- `src/backend/entrypoints/middlewares/circuit_breaker.py:369-410` — fixed __call__
- `tests/unit/entrypoints/middlewares/test_circuit_breaker.py` — migrated tests
