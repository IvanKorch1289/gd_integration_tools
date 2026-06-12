# ADR-0163 — Sprint 81 closure: P1 #8 CircuitBreakerMiddleware restoration (per-route state, sliding window, 13 NEW tests) (4 commits)

* Статус: Accepted (Autonomous work cycle S81, 2026-06-12)
* Связано с: FINAL_REPORT_V2 P1 #8 ("Вернуть CircuitBreakerMiddleware"),
  направление #16, ADR-005 (original removal)

## Контекст

S81 = **P1 #8 closure** (FINAL_REPORT_V2 P1 #8: "Вернуть CircuitBreakerMiddleware").
Pre-S81: middleware REMOVED в A2 (ADR-005) — global-state bug.
S81 W1: новый design без global state.

## Команда результаты (4 commits)

### W1: Middleware class (commit `c2961985`)
- File: `src/backend/entrypoints/middlewares/circuit_breaker.py` (NEW, 243 LOC)
- `BreakerPolicy` dataclass: failure_threshold, window_seconds,
  reset_timeout, excluded_statuses
- `BreakerState` enum: CLOSED, OPEN, HALF_OPEN
- `RouteBreakerState` dataclass: per-route mutable state
- `CircuitBreakerMiddleware` class (ASGI):
  - Per-route state (NOT global — instance-scoped)
  - Sliding window (deque)
  - State machine CLOSED → OPEN → HALF_OPEN → CLOSED
  - Per-route BreakerPolicy (longest-prefix match)

### W2: Middleware registry integration (commit `55e72b10`)
- File: `src/backend/entrypoints/middlewares/setup_middlewares.py` (+21, -1)
- Import CircuitBreakerMiddleware + BreakerPolicy
- Removed "CircuitBreakerMiddleware удалён в A2" comment
- New registration: order=250 (Layer 2)
- default_policy: 5 failures / 60s window / 30s reset

### W3: Tests (commit `3c8f8e73`)
- File: `tests/unit/entrypoints/middlewares/test_circuit_breaker.py` (NEW, 250 LOC)
- 13 NEW tests (2 policy + 5 state machine + 1 sliding + 3 per-route + 1 excluded + 1 ASGI)

### W4: Closure (this commit)

## Final state vs FINAL_REPORT_V2 P1 #8

| Aspect | Before S81 | After S81 |
|---|---|---|
| CircuitBreakerMiddleware class | ❌ removed | ✅ **restored (S81 W1)** |
| Middleware registry entry | ❌ commented out | ✅ **registered (S81 W2)** |
| Per-route state | ❌ (was global) | ✅ |
| Sliding window | ❌ | ✅ (deque-based) |
| Per-route config | ❌ | ✅ (BreakerPolicy + prefix match) |
| Tests | 0 | **13 NEW** |

**Status vs FINAL_REPORT_V2 P1 #8**: CLOSED.

## Why original was removed (A2 / ADR-005)

* Single global counter для ALL routes
* Один route flood → все routes отключались
* Memory leak (counter never reset)
* No per-route tuning

## S81 fixes

* **Per-route state** (independent failure tracking)
* **Sliding window** (auto-trim old failures)
* **Per-route BreakerPolicy** (different thresholds per route)
* **State machine** (recovery via HALF_OPEN probe)
* **Excluded statuses** (4xx не считаются failures)

## Use case

```python
# Production deployment: setup_middlewares() auto-registers:
app.add_middleware(
    CircuitBreakerMiddleware,
    default_policy=BreakerPolicy(
        failure_threshold=5, window_seconds=60.0, reset_timeout=30.0,
    ),
    # Optional per-route tuning:
    route_policies={
        "/api/v1/slow": BreakerPolicy(failure_threshold=3),
    },
)

# /api/v1/slow → 3 failures за 60s → OPEN → 503 immediate
# After 30s → HALF_OPEN → 1 probe → success → CLOSED
```

## Files changed summary

- W1: 1 file (+243, -0) — circuit_breaker.py
- W2: 1 file (+21, -1) — setup_middlewares.py
- W3: 1 file (+250, -0) — 13 NEW tests
- W4: 3 files (closure, this commit)
- **Total: 6 files, NET +610 LOC**

## S82+ epic candidates

1. **S82: docs/cookbooks/** (P1 направление #13) — 5+ recipes
2. **S83+: tools/check_decomp_bugs.py** (recurring pattern fix)
3. **S83+: 196 layer violations** (направление #2 class moves)
4. **S83+: AI stack consolidation** (5 frameworks → 2-3)
5. **S83+: Redis-based CB state** (current in-memory lost on restart)
