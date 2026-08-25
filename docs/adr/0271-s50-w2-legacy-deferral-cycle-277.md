# ADR-0271: Phase 2c Legacy Deprecation — Deferred to S51 (cycle 277)

> **Status**: PROPOSED (deferral).
> **Method**: Direct inspection of legacy users.
> **Conclusion**: Phase 2c (remove `_legacy_states`) requires test migration
> that is its own dedicated cycle, not part of S50 W2.

## 0. Current state (cycle 277)

Phase 2b (cycle 276) shipped: middleware has `use_breaker_registry` flag
support + `BreakerPolicyAdapter` integration. Default flag OFF preserves
backward compat.

Phase 2c plan per ADR-0268: "Remove legacy `_legacy_states` from
middleware. State now exclusively in `BreakerRegistry`."

## 1. Why Phase 2c is NOT this sprint

### 1.1 Legacy code still in use

```bash
$ grep -rn "use_sliding_window_breaker *= *False" tests/
tests/unit/entrypoints/middlewares/test_circuit_breaker_sliding.py:150:
    MagicMock(), use_sliding_window_breaker=False,
tests/unit/entrypoints/middlewares/test_circuit_breaker.py:204:
    m = _make_middleware(default_policy=policy, use_sliding_window_breaker=False)
```

At least 2 test files depend on `use_sliding_window_breaker=False` legacy
path. These tests directly manipulate `state.failures` and call
`_record_failure(state, policy)` which is state-only (no route).

### 1.2 Migration scope

For full Phase 2c:
1. Migrate 2+ test files to use route-aware adapter API
2. Update test fixtures (`_make_middleware` helpers)
3. Remove `use_sliding_window_breaker` parameter from middleware
4. Remove `_legacy_states` dict from middleware
5. Update SlidingWindowBreaker if no longer used
6. Verify all 490 tests still pass

**Estimated effort**: 4-6h of test migration work.

## 2. Recommended path (NOT this sprint)

### Phase 2c-1 (S50 W2): Deprecation warning, NO removal

- Update deprecation warning on `use_sliding_window_breaker=False`
- Document removal target (S52+)
- Existing legacy path still works

### Phase 2c-2 (S51 W1-2): Test migration sprint

- Migrate test files to route-aware API
- Remove `use_sliding_window_breaker` parameter
- Remove `_legacy_states` from middleware

### Phase 2c-3 (S51 W3): Verification

- All 490 tests pass with new API
- Multi-pod integration tests added
- Production rollout begins (dev → staging → prod)

## 3. Current S50 W2 deliverable (this cycle)

This ADR documenting the deferred Phase 2c plan. No code changes
(legacy path still works as before).

## 4. References

- ADR-0268 — S13 Phase 2 investigation + 4-phase rollout plan
- ADR-0270 — Sprint 50 plan + Phase 2b scope
- `src/backend/entrypoints/middlewares/circuit_breaker.py` — current state with Phase 2b wiring
- `tests/unit/entrypoints/middlewares/test_circuit_breaker*.py` — legacy users
