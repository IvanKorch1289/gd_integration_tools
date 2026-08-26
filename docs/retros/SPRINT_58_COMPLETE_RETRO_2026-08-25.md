# Sprint 58 — Complete Retrospective (2026-08-25)

> **Method**: Verify-first + real gap discovery + bounded refactor.
> **Sprint window**: 2026-08-25 (single intensive day).
> **Predecessor**: Sprint 57 (production flip evidence) complete.
> **Focus**: S13 Phase 4 staging runbook + close real metric wiring gap.

## 1. Sprint 58 plan

| Week | Focus | Status |
|---|---|---|
| W1 | S13 Phase 4 staging rollout runbook | ✅ DONE (10349 bytes, 4-phase procedure) |
| W2 | Coverage ratchet + real gap discovery | ✅ DONE (Prometheus metrics wired, 7 tests) |
| W3 | Natural coverage via W2 | ✅ DONE (+7 tests, real metric gap closed) |
| W4 | Sprint 58 retro + cross-sprint S49-S58 analysis | ✅ DONE (this) |

## 2. Sprint deliverables

| Cycle | Hash | What | Impact |
|---|---|---|---|
| 298 | (this) | S13 Phase 4 staging rollout runbook | Operational counterpart to ADR-0276 |
| 299 | (this) | Prometheus metrics wired into middleware | **REAL GAP closed** — Grafana dashboards now have data |
| 300 | (this) | 7 tests for metric wiring | Best-effort + label verification |

**Production code changed**: ~60 LOC
- `circuit_breaker.py`: added `_record_breaker_metric()` helper + 4 metric call sites
  (OPEN paths in registry + sliding window, success paths in both)
- Imports `record_circuit_breaker_state` from observability module

**Tests added**: 7
- `test_circuit_breaker_metrics.py`: 7 tests (registry path OPEN/CLOSED, sliding window OPEN/CLOSED,
  best-effort failure modes, label verification)

**Test count**: 587 → 594 (+7)
**Middleware test pass rate**: 495/495 PASS (was 488 at S56 close, +7)
**Mobile test pass rate**: 106/106 PASS (maintained)

## 3. Sprint 58 metrics

| Metric | S57 close | S58 close | Delta |
|---|---|---|---|
| Production code LOC | stable | +60 | +60 (metric wiring) |
| Tests | 587 | 594 | +7 |
| Middleware test pass rate | 488/488 | 495/495 | +7 |
| Mobile test pass rate | 106/106 | 106/106 | maintained |
| Real gaps closed | — | **1** (metric wiring) | +1 |

## 4. Sprint 58 implementation details

### 4.1 W1: S13 Phase 4 staging rollout runbook

**File**: `docs/security/S13_PHASE4_STAGING_ROLLOUT_RUNBOOK.md` (10349 bytes).

**Content** (mirrors S57 mobile JWT runbook structure):
- Architecture context (refs ADR-0276, all 7 phases complete)
- Pre-flight checklist (code, infra, config, observability)
- Phase 1: Dev (3-day soak)
- Phase 2: Staging (5-day soak + multi-pod test)
- Phase 3: Production canary (10% → 50% → 100%, 3+3+7 day soaks)
- Rollback procedure (immediate flag disable + full code rollback)
- Monitoring & alerting (4 critical alerts, Grafana dashboards)
- Test infrastructure (488+15+6 tests)
- References + change log

**Sibling runbook pattern**: Same structure as `MOBILE_JWT_PRODUCTION_FLIP_RUNBOOK.md`
(S57 W1), enabling consistent ops experience across two production flip procedures.

### 4.2 W2: Prometheus metrics wiring (REAL GAP closed)

**Problem discovered**: The S13 Phase 4 staging runbook referenced Prometheus metrics
for Grafana dashboards (`circuit_breaker_state`, `circuit_breaker_open_total`,
etc.). However:
- `_breaker_gauge` defined в `metrics.py:71-75` with proper state mapping
  (0=closed, 1=open, 2=half_open)
- `record_circuit_breaker_state()` defined в `metrics.py:183`
- BUT `circuit_breaker.py` middleware did NOT call them
- Dashboards were configured to query metrics that were never emitted

**Solution**:
1. Added `_record_breaker_metric()` helper in `circuit_breaker.py` (best-effort,
   never fails caller)
2. Wired metric calls at 4 sites:
   - Registry path OPEN → emit state_value=1
   - Registry path success → emit state_value=0
   - Registry path failure → re-fetch state and emit
   - Sliding window OPEN → emit state_value=1
   - Sliding window success → emit state_value=0
   - Sliding window failure (if breaker now open) → emit state_value=1

**State mapping** (`_BREAKER_STATE_TO_METRIC_VALUE`):
```python
BreakerState.CLOSED = 0
BreakerState.OPEN = 1      # Open takes precedence (most actionable for alerts)
BreakerState.HALF_OPEN = 2
```

### 4.3 W2: Tests added

**File**: `test_circuit_breaker_metrics.py` (7 tests):

1. `test_registry_path_circuit_open_emits_metric` — circuit OPEN → metric(1)
2. `test_registry_path_success_emits_metric` — success → metric(0)
3. `test_sliding_window_circuit_open_emits_metric` — sliding window OPEN → metric(1)
4. `test_sliding_window_success_emits_metric` — sliding window 200 → metric(0)
5. `test_metrics_failure_does_not_break_middleware` — metric raises → middleware OK
6. `test_metrics_module_unavailable_does_not_break_middleware` — ImportError → OK
7. `test_metric_label_uses_route_path` — `name` label = request path

**Bug fix during testing**:
- Initial MagicMock for `send` failed (JSONResponse awaits send multiple times)
- Fixed to AsyncMock
- Required `app=AsyncMock()` instead of `MagicMock()` for middleware factory

### 4.4 W3: Coverage ratchet via W2

**Approach**: Natural coverage growth from real gap fix.

7 new tests cover:
- Metric emission at 4 code sites
- Best-effort failure handling
- Label correctness

**Coverage gain estimate**: ~60 LOC new code, ~200 LOC test surface → +0.1% honest.

Per Ponytail/YAGNI: no speculative additions.

## 5. Sprint 58 real gap discovery

**Pattern**: Verifying runbook claims against actual code revealed discrepancy.

| Runbook claim | Reality | Sprint 58 resolution |
|---|---|---|
| Prometheus metrics emitted for Grafana | Metrics function exists but never called | Wired 4 metric call sites |
| 488 middleware tests pass | Still true (488 + 7 new = 495) | Maintained |

**Lesson**: Verify-first methodology surfaced real gap that prior sprints didn't catch.
Runbook writing → metric verification → metric wiring.

## 6. Out of scope (deferred to S59+)

### 6.1 S13 Phase 4 production rollout

Plan ready (runbook + ADR-0276). **BLOCKED** on ops approval + Redis HA staging.

### 6.2 Mobile JWT production flip

Plan ready (S57 runbook + OWASP evidence). **BLOCKED** on OWASP sign-off.

### 6.3 Prometheus metric — coverage of additional circuit breaker transitions

S58 W2 wired metrics for OPEN + CLOSED. HALF_OPEN state transition not
directly instrumented (relies on initial state + breaker probe success/fail).
Could be improved but not critical for Grafana dashboards.

## 7. Sprint 59 plan (proposed)

| Week | Focus | Deliverable |
|---|---|---|
| W1 | OWASP team review support | Address feedback + iterate on evidence doc |
| W2 | S13 Phase 4 dev rollout (if ops approves) | Enable flag in dev, monitor 3 days |
| W3 | Mobile JWT production flip (if OWASP signs off) | Production deployment per runbook |
| W4 | S59 retro + cross-sprint S50-S59 analysis | Final sprint summary |

If external approvals pending, W1 → coverage ratchet + refactor improvements.

## 8. Lessons captured

### 8.1 What worked

1. **Verify-first surfaced real gap**: writing runbook → checking metric claims → discovered
   metrics never wired. Closed real production gap (not just docs).
2. **Best-effort metric emission**: `_record_breaker_metric()` never fails caller —
   observability shouldn't break business logic.
3. **State-value mapping**: numeric encoding (0/1/2) is Grafana-friendly, matches
   existing dashboard queries.
4. **Mock app pattern**: `async def mock_app(scope, receive, send)` that sends proper
   response messages — cleaner than mocking return values.

### 8.2 What didn't work

1. **MagicMock for ASGI send**: Starlette JSONResponse calls `await send()` —
   MagicMock returns non-awaitable. Fixed to AsyncMock.
2. **Mocking message["status"] = 200**: wrapper reads status BEFORE my mock can mutate
   it. Fixed by making mock_app send the response itself.

### 8.3 What to do differently in S59

1. **Use AsyncMock for ASGI send/receive from the start** — pattern established.
2. **Verify runbook claims against code BEFORE writing tests** — caught real gap.
3. **Best-effort metric calls** should be a pattern, not exception.

## 9. Reference commit index (S58 complete)

```
(this)    docs(security): S58 W1 — S13 Phase 4 staging rollout runbook
(this)    feat(middlewares): S58 W2 — wire Prometheus metrics for circuit breaker
(this)    test(middlewares): S58 W2 — 7 metric emission tests
```

## 10. S58 handoff to S59

**Open items for S59** (carry-over):
- OWASP team review of mobile JWT evidence (W1, external)
- S13 Phase 4 dev rollout (W2, blocked on ops)
- Mobile JWT production flip (W3, blocked on OWASP sign-off)
- S59 retro (W4)

**Production readiness**: 96% maintained. **S13 Phase 4 staging**: evidence + metrics + runbook ready.

**Real gaps closed in S58**: 1 (Prometheus metric wiring).

**Open questions for product owner**:
1. OWASP team review scheduled?
2. S13 Phase 4 dev rollout approval?
3. Mobile JWT production flip timeline?
4. Redis HA infrastructure planning (gating both S13 + mobile JWT production)?
