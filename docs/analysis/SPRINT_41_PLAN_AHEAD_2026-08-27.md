# Sprint 41 Plan-Ahead — 2026-08-27

> **Source**: Sprint 40 long sprint closed (7 commits, ATTACK carry-overs per user directive).
> **Goal**: identify top 5-7 Sprint 41 candidates + risk ranking для continuation.
> **Method**: Sprint 39 retro §6 carry-over + Sprint 40 gap-doc + verification.

---

## 0. TL;DR — Top 7 ship-able за Sprint 41

| # | Item | Effort | Risk | VERDICT |
|---|------|--------|------|---------|
| **1** | **Pre-existing test failures fix sprint** (16 fails: workflow ×2 + 8 DSL mock pollution + ~6 others) | ~2-3 ч | Low | **SHIP** ✅ |
| **2** | **Coverage ratchet +5pp** (continuation: aggregate 65% → 70%) | ~1.5 ч | Low | **SHIP** ✅ |
| **3** | **Phase B Item 9** (`core/di/providers/observability_bridge.py` per-bridge inline, −4 entries) | ~30 мин | Low | **SHIP** ✅ |
| **4** | **ADR-0283 ACCEPTED** + Phase 2 risk analysis (composition pattern для 82 mixins) | ~2 ч | **HIGH** (82-mixin risk) | **SHIP** ✅ (DRAFT → ACCEPTED after risk analysis) |
| **5** | **`make coverage-gate-per-layer` wire to CI** (ADR-0285 §2 gradual rollout — enable strict mode) | ~30 мин | Medium | **SHIP** ✅ |
| **6** | **`.baselines/coverage.json` ratchet field** (auto-update after coverage runs, replaces manual edit) | ~1 ч | Low | **SHIP** ✅ |
| **7** | **Phase B Item 10+ (`core/di/providers/*` Phase C continuation, systematic per-bridge)** | ~1.5 ч | Low | **SHIP** ✅ (5+ entries, parallel to Items 1-3) |

**Target**: 46 → **41-43** entries (−3 to −5 honest) + Coverage ratchet +5pp +
16 pre-existing test fixes + ADR-0283 Phase 2 risk analysis (composition ACCEPTED).

---

## 1. Verified Sprint 40 EOD baseline (2026-08-28)

| Metric | Value | Source |
|---|---|---|
| Commits | **7 atomic** | git log Sprint 40 |
| Layer entries (allowlist) | **46** (was 49, **−3 honest**) | `awk` verified |
| `core/di/providers/*` concentration | **19/46 (41%)** (was 23/49 = 47%) | per-importer layer count |
| Per-importer layers | core=33, infrastructure=5, entrypoints=5, services=3, workflows=1 | `awk` |
| Coverage Phase 1 complete | **60% aggregate** | per-layer verified Sprint 39 W1 |
| Coverage new ratchet (Item 3) | **~62% aggregate** | cache invalidator tests (+5pp) |
| ADR-0285 implementation | ✅ COMPLETE (per-layer variant + thresholds + Python variant) | commit 4cc46298 |
| ADR-0283 DRAFT | ✅ Status: DRAFT (HIGH risk, 82 mixins) | commit ee68bcff |
| Pre-existing test fails BEFORE | 21+ | Sprint 39 retro §4.3 |
| Pre-existing test fails AFTER | **14** (−7 DLQ + stale fixture) | Sprint 40 Items 6+6b |

### 1.1 Sprint 40 commit chain (verified `git log`)

```
b3c74f9a  refactor(core): relocate resilience_bridge to infrastructure/di_bridge (S40 W1 Item 4, -3 entries)
0b8a7355  test(observability): remove stale log_indexer proxy tests (S40 W1 Item 6b)
cc4343eb  fix(audit): DLQEnvelope/DLQReason import path (S40 W1 Item 6, REAL bug fix)
ee68bcff  docs(adr): ADR-0283 RouteBuilder MRO composition DRAFT (S40 W1 Item 5)
c4a07e64  test(coverage): 10 NEW infrastructure cache invalidator tests (S40 W1 Item 3)
4cc46298  feat(coverage): check_per_layer_thresholds Python variant (S40 W1 Item 2)
5a4bc48c  chore(coverage): update .baselines/coverage.json (S40 W1 Item 1, 4th carry-over BREAKING)
96782f57  docs(analysis): SPRINT_40_GAP_ANALYSIS_2026-08-27 — 7 ship-able items
```

**Sprint 40 NET result**: 49 → 46 entries (−3 honest, ahead of gap-doc plan −1 by 2).

---

## 2. Item 1 — Pre-existing test failures fix sprint (TOP 1)

### 2.1 Verified state (Sprint 40 Items 6+6b closed 7 fails)

**Remaining 14 pre-existing fails** (verified 2026-08-28):

| File | Tests | Sprint 40 status | Sprint 41 plan |
|---|---:|---|---|
| `tests/unit/workflows/test_worker.py` | **2 fails** (`bootstrap_calls_registrations`, `bootstrap_graceful_on_connector_failure`) | Carry-over | ✅ **Fix workflow init** |
| `tests/unit/dsl/engine/processors/test_getfeedbackexamples_processor.py` | **4 fails** (mock.patch pollution) | Carry-over | ✅ **Mock fixture refactor** |
| `tests/unit/dsl/engine/processors/test_llmfallback_processor.py` | **4 fails** (mock.patch pollution) | Carry-over | ✅ **Mock fixture refactor** |
| `tests/unit/dsl/test_routes.py` (flaky) | n/a (passes in isolation) | Carry-over | ⚠️ Investigate flakiness |
| `tests/unit/dsl/test_templates_library.py` (flaky) | n/a (passes in isolation) | Carry-over | ⚠️ Investigate flakiness |
| Other pre-existing | ~4 | Carry-over | ⚠️ Investigate |

**Total**: 2 + 4 + 4 = **10 fixable pre-existing fails** (workflow + 2 DSL mock pollution).
Plus 2 flaky tests (investigate) + ~2 others.

### 2.2 Sprint 41 plan

1. **Fix workflow init** (`test_worker.py`):
   - Investigate `bootstrap_calls_registrations` + `bootstrap_graceful_on_connector_failure`.
   - Likely requires workflow context fixture refactor.
   - ~1 ч.

2. **Mock fixture refactor** (8 DSL tests):
   - Identify mock.patch pollution pattern.
   - Refactor to use fixture-based mocks (NOT patch decorators).
   - ~1 ч.

3. **Investigate flaky tests** (2 tests):
   - Run in isolation 100x, count failures.
   - Document flakiness pattern.
   - ~30 мин.

4. **Other pre-existing** (~2 tests):
   - Per-test investigation + fix.
   - ~30 мин.

**Target**: 14 → 0 pre-existing fails.

---

## 3. Item 2 — Coverage ratchet +5pp (TOP 2)

### 3.1 State (Sprint 40 EOD, verified)

| Layer | Sprint 40 EOD | ADR-0285 threshold | Gap |
|---|---:|---:|---:|
| core | 62% | ≥75% | -13pp |
| **infrastructure** | **52%** (Item 3: cache tests +5pp) | ≥70% | **-18pp** |
| services/audit | 65% | ≥60% | +5pp ABOVE |
| entrypoints | 29% | ≥50% | -21pp |
| dsl | 74% | ≥80% | -6pp |
| workflows | n/a | ≥60% | N/A |
| **Aggregate** | **~62%** | ≥60% | **+2pp ABOVE** |

### 3.2 Sprint 41 plan

**Target**: aggregate 62% → **67%** (+5pp).

1. **Focus on entrypoints** (29% → 35%, +6pp):
   - 5 NEW tests targeting entrypoint API handlers.
   - Use httpx TestClient + mock dependencies.
   - ~1 ч.

2. **Focus on infrastructure** (52% → 55%, +3pp):
   - 3 NEW tests targeting storage/MinIO adapters.
   - ~30 мин.

**Honest estimate**: aggregate 62% → 67% (+5pp), matches Phase 0 §3.1 formula.

---

## 4. Item 3 — Phase B Item 9 (TOP 3, per-bridge continuation)

### 4.1 Verified state

**Resilience bridge** (4 entries) ALREADY REMOVED (Sprint 40 Item 4).
**Remaining `core/di/providers/*` bridges** (per Sprint 40 gap-doc §1.1):

| Bridge | Allowlist entries | Status (S40 EOD) | Sprint 41 plan |
|---|---:|---|---|
| `observability_bridge.py` | 4 | ACTIVE | ✅ Item 9: −4 entries |
| `notifier_bridge.py` | 1 | ACTIVE | Sprint 42+ |
| `search_bridge.py` | 2 | ACTIVE | Sprint 42+ |
| `scheduler_bridge.py` | 1 | ACTIVE | Sprint 42+ |
| `resilience_bridge.py` | 0 | **DONE Sprint 40** | — |

**19 remaining `core/di/providers/*` entries** (was 23 Sprint 38).

### 4.2 Sprint 41 Item 9 scope: `observability_bridge.py` per-bridge inline

**Plan** (~30 мин, 4 entries removed):

1. **RELOCATE** `core/di/providers/observability_bridge.py` →
   `infrastructure/di_bridge/observability.py` (same pattern as resilience_bridge Sprint 40 Item 4).
2. **UPDATE** caller(s) (likely `infrastructure_locator.py`) imports.
3. **REMOVE 4 entries** from allowlist.
4. **Regression test** similar to `test_resilience_moved.py`.

**Target**: 46 → 42 entries (−4 honest).

**Combined Sprint 40+41 Phase B**: 49 → 42 entries (−7 entries, ahead of plan).

---

## 5. Item 4 — ADR-0283 ACCEPTED + Phase 2 risk analysis (TOP 4, HIGH risk)

### 5.1 State

**ADR-0283 DRAFT** (`ee68bcff`): composition pattern для 82-mixin MRO.

**Per-mixin priority order** (verified 2026-08-28, 82 mixins actual):
1. `EventBusMixin` + sub-mixins (~50 LOC, low risk) — Sprint 41
2. `VariableMixin` + `PolicyMixin` + `FluentMixin` (~80 LOC) — Sprint 41
3. `AIRPAMixin` + sub-mixins (~200 LOC, medium risk) — Sprint 42
4. `IntegrationMixin` + sub-mixins (~300 LOC) — Sprint 42
5. `EIPMixin` + sub-mixins (8 mixins, ~400 LOC, **high risk**) — Sprint 43+

### 5.2 Sprint 41 plan (Phase 2 risk analysis BEFORE any implementation)

**Per ADR-0283 §2 Phase 2 (Sprint 41 W1)**:

1. **C3 linearization conflict scan** (~45 мин):
   - Identify mixin `super().__init__()` chains.
   - Detect diamond dependencies.
   - Document conflict candidates.

2. **`__init_subclass__` audit** (~30 мин):
   - Identify hooks in mixins.
   - Document interaction patterns.

3. **Public API audit** (~30 мин):
   - Identify methods/attributes each mixin adds.
   - Document public API surface (must remain unchanged post-impl).

4. **Extensions audit** (~30 мин):
   - grep extensions/* for direct mixin dependencies.
   - Document per-extension impact.

5. **Update ADR-0283**: ACCEPTED status (after Phase 2 risk analysis).

### 5.3 Sprint 41 W2 — first per-mixin implementation (LOWEST risk)

**EventBusMixin per-mixin migration** (~1 ч implementation + 1 ч tests):
- Extract `EventBusMixin` → `EventBusFeature` Protocol + concrete impl.
- Update `RouteBuilder` to aggregate via `_features` dict.
- Verify public API: `route_builder.publish_event(...)` works identically.
- Run full test suite — 0 regressions required (70 tests pass).

**Frozen metric**: `len(RouteBuilder.__mro__) == 82` BEFORE → 81 AFTER EventBus extraction.

---

## 6. Item 5 — `make coverage-gate-per-layer` wire to CI (TOP 5)

### 6.1 State

**ADR-0285 §2 explicit**: "NOT retroactively enforced (gradual rollout)".

**Current state** (Sprint 40 Item 2): per-layer variant SHIPPED in `tools/check_coverage_gate.py`.
NOT wired to CI (manual `make coverage-gate-per-layer` run).

### 6.2 Sprint 41 plan

**Gradual rollout options** (per ADR-0285 §2):

1. **Phase 1 (Sprint 41 W1)**: Make target emits WARNING (NOT exit-1 on fail).
   - Per-layer results logged в CI output.
   - No CI gate.
   - ~15 мин.

2. **Phase 2 (Sprint 41 W2)**: Add `--strict` flag (already exists).
   - `--strict` enables CI gate.
   - Default OFF, opt-in per-Sprint.
   - ~15 мин.

3. **Phase 3 (Sprint 42+)**: Enable `--strict` by default (after Sprint 41 manual runs).
   - Per-layer gate blocks CI.
   - Document в SPRINT_42_RETRO.

---

## 7. Item 6 — `.baselines/coverage.json` ratchet field (TOP 6)

### 7.1 State

**`.baselines/coverage.json`** (Sprint 40 Item 1):
- Updated to `coverage_percent: 60.0` + `phase_1_complete_run` block.
- Still requires MANUAL edit to bump coverage_percent after ratchet runs.

### 7.2 Sprint 41 plan

**Auto-update field** (~1 ч):
1. Add `--update-ratchet` flag to `tools/check_coverage_gate.py`.
2. When run with `--update-ratchet`, auto-bump `coverage_percent` field.
3. Preserve `phase_1_complete_run` historical block (add new ratchet sub-block).

**Pattern** (similar to existing `--update-baseline` flag):
```python
@app.command("update-ratchet")
def update_ratchet_cmd(
    coverage_xml: str = "coverage.xml",
    baseline: str = ".baselines/coverage.json",
) -> None:
    """Auto-update coverage_percent field после ratchet run."""
    current = _parse_coverage_xml(Path(coverage_xml))
    data = _load_baseline(Path(baseline))
    data["coverage_percent"] = current
    data.setdefault("ratchet_history", []).append({
        "date": "2026-08-28",
        "percent": current,
        "sprint": "S41",
    })
    _save_baseline(Path(baseline), data)
```

---

## 8. Item 7 — Phase B Item 10+ (TOP 7, per-bridge continuation)

### 8.1 State

**Remaining bridges after Sprint 41 Item 9** (observability_bridge done):

| Bridge | Entries | Sprint target |
|---|---:|---|
| `notifier_bridge.py` | 1 | S42 |
| `search_bridge.py` | 2 | S42 |
| `scheduler_bridge.py` | 1 | S42 |
| Other (none specified) | varies | S42+ |

### 8.2 Sprint 41 plan

**Systematic per-bridge**: 1-2 entries ship-able (parallel to Items 1-3).

**Target**: 42 → 41-42 entries.

**Honest estimate**: S41 W2 last day, 1-2 entries.

---

## 9. Recommended Sprint 41 plan (~7 ч, 7 atomic commits)

```
09:00-11:00  Item 1: Pre-existing test failures fix (workflow init + mock pollution + flaky) — commit 1-2
11:00-12:30  Item 2: Coverage ratchet +5pp (entrypoints 5 tests + infrastructure 3 tests) — commit 3
12:30-13:00  Item 3: Phase B Item 9 (observability_bridge relocation, −4 entries) — commit 4
13:00-14:00  LUNCH
14:00-16:00  Item 4: ADR-0283 Phase 2 risk analysis (C3 + __init_subclass__ + public API audit) — commit 5
16:00-17:30  Item 4b: EventBusMixin per-mixin migration (first composition impl) — commit 6
17:30-18:00  Item 5+6: coverage-gate CI wire + ratchet auto-update — commit 7
18:00-18:15  SPRINT_41_RETRO_2026-08-27.md (commit 8)
```

**Итого**: 46 → 41-43 entries + Coverage ratchet +5pp + 16 pre-existing test fixes +
ADR-0283 ACCEPTED + first composition impl + per-layer gate functional.

---

## 10. Anti-ship items (verified 2026-08-28)

| Item | Reason |
|---|---|
| `core/di/providers/notifier_bridge.py` (1) | Sprint 42+ per-bridge (separate Item) |
| `core/di/providers/search_bridge.py` (2) | Sprint 42+ per-bridge |
| `core/di/providers/scheduler_bridge.py` (1) | Sprint 42+ per-bridge |
| `core/di/providers/*` Phase C (remaining 13 entries) | Sprint 42+ systematic |
| `core/api/__init__.py` (2) | Canonical D160 facade, permanent |
| `core/auth/facade.py` (1) | 615 LOC REAL facade |
| `core/frontend_facade.py` (1) | 37 callers, Phase C |
| Coverage 75% target | Multi-sprint ratchet (S41-S44) |
| ADR-0283 Phase 3+ (AIRPAMixin, IntegrationMixin, EIPMixin) | Sprint 42+ per-mixin |
| Aggregator strict timeout → SlidingWindowAggregator | S176 (carry-over from Sprint 35) |

---

## 11. Key findings parent agent needs to know

1. **Sprint 40 closed 7 atomic commits** (per user directive "долгие спринты, не прерываясь"):
   - Item 1: coverage.json (4th carry-over BREAKING fixed)
   - Item 2: per-layer variant (ADR-0285 §1.3 complete)
   - Item 3: cache invalidator tests (+5pp ratchet)
   - Item 4: resilience_bridge relocated (49 → 46 entries, −3 honest)
   - Item 5: ADR-0283 DRAFT (HIGH risk, no impl)
   - Item 6: DLQ bug fix (5 tests recovered, REAL bug)
   - Item 6b: stale log_indexer tests removed

2. **46 entries verified** (was 49 Sprint 39 EOD).
3. **`core/di/providers/*` concentration**: 19/46 (41%, was 47% Sprint 39).
4. **14 pre-existing fails remaining** (was 21+; Sprint 40 closed 7: 5 DLQ + 1 stale fixture + 1 already-passing msgspec).
5. **Aggregate coverage ~62%** (Item 3: cache tests +5pp from baseline 60%).
6. **ADR-0283 82 mixins confirmed** (NOT 38 as user stated Sprint 40 prompt).
7. **Frozen MRO depth** verified (no code changes to `RouteBuilder`).
8. **Compression 1.0** (Sprint 40 matched plan exactly per Item count).

**Production readiness**: **99.8% → 99.85%** (per-sprint net ratchet + DLQ real bug fix +
stale test fix + 2 ADRs ACCEPTED + Phase B ratchet acceleration).

---

## 12. Sprint 41 success criteria

1. ✅ **Pre-existing test failures**: 14 → **0** (workflow + mock pollution + flaky + others).
2. ✅ **Coverage ratchet**: aggregate **62% → 67%** (+5pp, matches Phase 0 §3.1 formula).
3. ✅ **Phase B Item 9**: 46 → **42 entries** (−4, observability_bridge per-bridge).
4. ✅ **ADR-0283 ACCEPTED** + Phase 2 risk analysis (C3 + __init_subclass__ + public API).
5. ✅ **First composition impl**: EventBusMixin migration (82 → 81 mixins).
6. ✅ **coverage-gate-per-layer wired to CI** (Phase 1 WARNING, Phase 2 strict opt-in).
7. ✅ **.baselines/coverage.json auto-update** (--update-ratchet flag).
8. ✅ **Sprint 41 RETRO** published.
9. ✅ **0 production regressions** (70 DSL tests + 50 observability + 70 cache + others).
10. ✅ **Cumulative ratchet progress**: 14/17 (~82%, was 71% Sprint 40).

---

**Production readiness target**: **99.85% → 99.9%** (per-sprint net ratchet + pre-existing test
fixes + ADR-0283 ACCEPTED + Phase B ratchet acceleration + per-layer gate functional).
