# ADR-0275: Purgatory ContextManager Protocol Integration (cycle 283)

> **Status**: ACCEPTED.
> **Method**: Direct investigation of purgatory 3.0.1 API + implementation
> + tests.
> **Impact**: S13 ceremony Phase 4 (staging rollout) now viable. Production
> state mutation through registry path is no longer a no-op.

## 0. Problem

S50 W4 (cycle 279) discovered that purgatory 3.0.1's `Breaker` class
doesn't expose `record_failure()` / `record_success()` as public API.
Adapter's `record_failure()` calls were graceful no-ops with warning logs.

This meant:
- Registry path was testable but didn't actually mutate state in production
- Multi-pod breaker state (with Redis UOW) wouldn't propagate
- Phase 4 (staging rollout) was blocked on real state mutation

## 1. Investigation (cycle 283)

Examined purgatory 3.0.1 source (`purgatory/domain/model.py:1-100`):
- `Context` class exposes `handle_exception(exc)` and `handle_end_request()`
- These are called via the `__enter__`/`__exit__` context manager
- `AsyncCircuitBreaker.context` provides access to the Context instance

## 2. Fix

Replaced adapter's no-op calls with real purgatory API:

```python
# Before (S49 W1):
breaker.record_failure()  # AttributeError → graceful no-op

# After (S51 W3):
breaker.context.handle_exception(RuntimeError("recorded failure"))
```

```python
# Before (S49 W1):
breaker.record_success()  # AttributeError → graceful no-op

# After (S51 W3):
breaker.context.handle_end_request()
```

## 3. Why synthetic RuntimeError?

purgatory's `handle_exception(exc)` expects a BaseException to determine
which exceptions count as failures (via `exclude` list). Since adapter
doesn't have the original exception, passes synthetic RuntimeError.

In production callers (Phase 4+), adapter should be refactored to accept
the actual exception from upstream. ADR-0276 (future) will track this.

## 4. S13 ceremony status (cycle 283)

| Phase | Status | Source |
|---|---|---|
| 1 (foundation) | ✅ DONE | S48 W1 |
| 2a (adapter) | ✅ DONE | S49 W1 |
| 2b (wiring) | ✅ DONE | S50 W1 |
| 2b-2 (__call__ fix) | ✅ DONE | S51 W1 |
| 3 (multi-pod tests) | ✅ DONE | S50 W4 |
| 2c (legacy removal) | ✅ DONE | S51 W2 |
| **3.5 (purgatory integration)** | ✅ **DONE** | **S51 W3** |
| 4 (staging rollout) | ⚠️ DEFERRED | (S51 W4 prep / S52+ actual) |

**7 of 8 phases complete.** State mutation is now real.

## 5. Test updates

- `test_record_failure_delegates_to_breaker`: now verifies
  `breaker.context.handle_exception.assert_called_once()`
- `test_record_success_delegates_to_breaker`: now verifies
  `breaker.context.handle_end_request.assert_called_once()`

## 6. References

- `src/backend/core/resilience/breaker_policy_adapter.py:111-145` — fix
- `tests/unit/core/resilience/test_breaker_policy_adapter.py:80-110` — test updates
- ADR-0268 — S13 4-phase plan
- ADR-0269 — Phase 2a foundation
- `.venv/lib/python3.14/site-packages/purgatory/domain/model.py` — Context API
