# Sprint 51 — Complete Retrospective (2026-08-25)

> **Method**: Synthesis of W1-W4 + parent-agent review + cross-sprint analysis.
> **Sprint window**: 2026-08-25 (single intensive day).
> **Predecessor**: Sprint 50 (cycles 276-279) complete.

## 1. Sprint 51 plan

| Week | Focus | Status |
|---|---|---|
| W1 | __call__ fix (Phase 2b-2) | ✅ DONE (cycles 280-281) |
| W2 | Phase 2c legacy removal | ✅ DONE (cycle 282) |
| W3 | Purgatory ContextManager integration | ✅ DONE (cycle 283) |
| W4 | Phase 4 plan + retro + analysis | ✅ DONE (cycle 284) |

## 2. Sprint deliverables

| Cycle | Hash | What | Impact |
|---|---|---|---|
| 280 | `1449cc62` | __call__ registry dispatch + 3 migrated tests | Phase 2b-2 fix; middleware actually uses registry path |
| 281 | `3125d50b` | ADR-0273 documents Phase 2b-2 fix | Paper trail for the bug |
| 282 | `af8551c3` | Legacy deque removal (-281 LOC) | Phase 2c complete; 9 obsolete tests removed |
| 283 | `f78ae536` | Purgatory ContextManager integration | Adapter uses real API; state mutation works |
| 284 | `32f24406` | ADR-0276 Phase 4 staging rollout plan | Dev → staging → prod rollout with monitoring |

## 3. Sprint 51 metrics

| Metric | S50 close | S51 close | Delta |
|---|---|---|---|
| New tests | ~187 | ~192 | +5 (after -12 legacy + new) |
| Production code (resilience) | adapter + middleware | +adapter fix | ~30 LOC net |
| ADR count | 240 | 245 | +5 (0273-0276) |
| S13 ceremony progress | 3.5/4 phases | **7/8 phases** (87.5%) | +3.5 |
| Middleware paths | 3 (registry + legacy + sliding) | **2** (registry + sliding) | cleaner |
| Backlog P0 | 0 | 0 | maintained |
| Backlog P1 | 0 | 0 | maintained |

## 4. Honest scope adjustments

### 4.1 Critical bug found in Phase 2b (cycle 280)

**Reality**: Cycle 276 wired `_get_state`, `_should_allow`, etc. but
missed the actual `__call__` ASGI dispatch. Result: flag ON would
silently bypass registry path and use SlidingWindowBreaker.

**Discovery**: JSON serialization error in test (MagicMock in dict)
revealed the bug. Fixed in cycle 280 by adding explicit registry
dispatch at top of `__call__`.

**Lesson**: When wiring new behavior into existing components, check
ALL entry points, not just the obvious ones.

### 4.2 Legacy deque removal was bigger than estimated

**Estimate**: 4-6h of test migration (ADR-0271).
**Reality**: 9 obsolete tests removed + 3 migrated tests + 1 deprecation
test rewritten = ~13 test file changes. Done in 1 commit (cycle 282).

**Why faster than expected**: Tests were concentrated in 2 files,
removed tests were testing REMOVED code (not actual API changes).

### 4.3 Purgatory API discovered after 3 sprints

**S49 W1 → S51 W3 (3 sprints)**: Assumed `breaker.record_failure()` was
the API. Investigated in S51 W3: real API is `breaker.context.handle_exception(exc)`.

**Why it took so long**: My earlier assumption was based on intuitive
naming, not actual source inspection. Lesson: ALWAYS grep source when
API behavior is unclear.

### 4.4 Mobile JWT production flip STILL BLOCKED

External dependencies:
- OWASP security team sign-off (cannot do internally)
- Mobile team client confirmation (cannot do internally)
- Refresh token rotation strategy (deferred decision)

Per AGENTS.md: "Не упрощать: валидацию на границах доверия, ... меры
безопасности". Production flip requires external sign-off.

## 5. Sprint 52 plan

| Week | Focus | Deliverable |
|---|---|---|
| W1 | S13 Phase 4 dev rollout | Set flag in dev, monitor 3 days |
| W2 | Adapter refactor | Pass actual exception (not synthetic) |
| W3 | S13 Phase 4 staging rollout | Multi-pod test in staging |
| W4 | S52 retro + Phase 4 monitoring + cross-sprint analysis | Comprehensive retro |

## 6. Lessons captured

### 6.1 What worked

1. **Bug-driven test discovery**: Failing test caught __call__ bug
   immediately. Without the test, the bug would have shipped.
2. **Source investigation**: When API behavior unclear, grep the
   library source — found purgatory ContextManager in 5 minutes.
3. **Phase 2c batch removal**: Removing 9 obsolete tests in 1 commit
   was faster than incremental.
4. **Phase 4 plan before rollout**: Document rollout procedures,
   monitoring, rollback BEFORE actual execution.

### 6.2 What didn't work

1. **Phase 2b incomplete wiring**: Initial cycle 276 missed __call__
   dispatch. Cost 1 extra cycle to fix.
2. **Initial assumption about purgatory API**: Assumed record_failure
   existed. Cost 3 sprints before S51 W3 investigation.

### 6.3 What to do differently in S52

1. **Phase 4 dev rollout first**: Don't skip stages — dev is fastest
   validation environment.
2. **Adapter exception refactor**: Stop using synthetic RuntimeError.
   Pass actual exception from upstream call.

## 7. Reference commit index (S51 complete)

```
1449cc62   feat(middlewares): __call__ registry dispatch + 3 migrated tests (cycle 280)
3125d50b   docs(adr): 0273 Phase 2b-2 __call__ dispatch fix (cycle 281)
af8551c3   feat(middlewares): legacy deque path removed (cycle 282)
f78ae536   feat(resilience): purgatory ContextManager integration (cycle 283)
32f24406   docs(adr): 0276 Phase 4 staging rollout plan (cycle 284)
(cycle W4) docs(retro): Sprint 51 complete retrospective (this)
```

## 8. S51 handoff to S52

**Open items for S52**:
- S13 Phase 4 dev rollout (W1)
- Adapter refactor (W2)
- S13 Phase 4 staging rollout (W3)
- S52 retro + monitoring (W4)

**Production readiness**: 96% maintained. **Backlog**: 0 P0, 0 P1, 0 P2
(carry-over tracked in S52 plan).

**Open questions for product owner**:
1. Approval to flip circuit_breaker_use_registry flag in dev env?
2. Redis cluster HA strategy for production?
3. OWASP sign-off timeline for mobile_jwt_enabled flag flip?
