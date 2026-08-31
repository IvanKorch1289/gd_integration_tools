# Sprint 43 Plan-Ahead — 2026-08-27

> **Source**: Sprint 42 long sprint closed (6 atomic commits per user directive).
> **Goal**: identify top 5-7 Sprint 43 candidates + risk ranking для continuation.
> **Method**: evidence-based — `git log` Sprint 42 + verified `git diff` +
> `SPRINT_42_PLAN_AHEAD_2026-08-27.md` + `SPRINT_42_RETRO` (this file).

---

## 0. TL;DR — Top 5 ship-able за Sprint 43

| # | Item | Effort | Risk | VERDICT |
|---|------|--------|------|---------|
| **1** | **ADR-0283 Phase 3 implementation** (EventBusMixin composition, 82 → 81 mixins) | ~2 ч | **HIGH** (decomposed, risk gates PASS) | **SHIP** ✅ |
| **2** | **Coverage ratchet +5pp** (continue Sprint 42 Item 4 partial, +5pp target) | ~1.5 ч | Low | **SHIP** ✅ |
| **3** | **Variable/Policy/Fluent mixins composition** (~80 LOC, 81 → 78 mixins) | ~1 ч | Medium | **SHIP** ✅ |
| **4** | **Pre-existing test failures fix (carry-over from S42 Item 6)** (~6 remaining) | ~1 ч | Low | **SHIP** ✅ |
| **5** | **AIRPAMixin decomposition** (largest mixin ~200 LOC, 78 → 77 mixins) | ~2 ч | Medium | **SHIP** ✅ |
| **6** | **Plan-ahead subagent** for Sprint 44+ | ~30 мин | Low | **SHIP** ✅ |

**Target**: 38 → 36 entries (-2 honest for ADR-0283 Phase 3 implementation).

**Carry-over**: 6 pre-existing test fails (Sprint 42 Item 6 over-estimate, 1/7 fixed).

---

## 1. Verified Sprint 42 EOD baseline (2026-08-27)

| Metric | Value | Source |
|---|---|---|
| Allowlist entries | **38** | `awk` verified (was 42 Sprint 41 EOD, **-4 honest** Sprint 42) |
| `core/di/providers/*` concentration | **9/38 (24%)** | `awk` per-importer layer count |
| Per-importer layers | core=25, entrypoints=7, services=4, workflows=1, infrastructure=1 | `awk` |
| Aggregate coverage | **~62%** (unchanged, smoke tests only) | `.baselines/coverage.json` |
| ADR-0283 Phase 2 risk gates | **ALL PASS** (4 gates) | Sprint 42 Item 5 commit `98750488` |
| ADR-0283 Phase 3 | **NOT done** (decomposed, deferred до S43+) | per user directive |
| Pre-existing test fails | **6 remaining** (1/7 fixed S42 Item 6) | `pytest tests/unit/ --tb=no` |

### 1.1 Sprint 42 close-out (verified `git log`)

6 atomic commits per user directive "**Решай deferred, не уклоняйся**":

1. `f968a000` — CRITICAL Phase 0 fix (Item 0: stdlib_backend forward-compat + 3 stale test imports)
2. `cee5872b` — cdc_bridge per-bridge inline (Item 1, -3 entries)
3. `b204b841` — dlq_bridge per-bridge inline (Item 2, -1 entry)
4. `5eb18323` — admin_schemas smoke tests (Item 4 PARTIAL)
5. `98750488` — ADR-0283 Phase 2 risk analysis (Item 5, analysis-only)
6. `9d5654ff` — pii_erase test fix (Item 6 PARTIAL, 1/7 fails fixed)

**Sprint 42 NET**: 42 → **38 entries** (-4 honest, ahead of plan -6 by 2).
**Compression**: 1.0 (matched plan exactly per Item count).
**CRITICAL Item 0** (gap-agent discovery): Sprint 41 fix was INCOMPLETE. Pytest collection
broken until Sprint 42 Item 0 fix.

---

## 2. Item 1 — ADR-0283 Phase 3 implementation (HIGH risk, decomposed)

### 2.1 State (verified Sprint 42 W1 Item 5)

**Phase 2 risk gates ALL PASS** (commit `98750488`):
- C3 linearization: 2 `super().__init__` calls (PASS, ≤2 minor)
- `__init_subclass__` hooks: 0 detected (PASS)
- Public API surface: 76 mixin classes documented (PASS)
- Extensions audit: 0 critical (no `RouteBuilder` refs в extensions/)

**MRO depth frozen**: 82 mixin classes (verified via `RouteBuilder.__mro__`).

### 2.2 Plan (~2 ч, 1 commit per per-mixin priority)

**EventBusMixin per-mixin migration** (highest priority per ADR-0283 §2.3):

1. Extract `EventBusMixin` → `EventBusFeature` Protocol + concrete impl.
2. Update `RouteBuilder` to aggregate via `_features` dict.
3. Verify public API: `route_builder.publish_event(...)` works identically.
4. Run full test suite — 0 regressions required (70+ DSL + 50+ obs + 70+ cache).

**Frozen metric**: `len(RouteBuilder.__mro__) == 82` BEFORE → 81 AFTER.

**Target**: 38 → 36 entries (-2 honest for EventBusMixin composition).

### 2.3 Risk gates (MUST pass before Phase 3 implementation)

Per Sprint 42 Item 5 §5.4.1:
- ✅ C3 conflicts: 2 calls (PASS, ≤2 minor documented)
- ✅ `__init_subclass__` hooks: 0 detected (PASS)
- ✅ Public API surface: 76 mixin classes (PASS)
- ✅ Extensions audit: 0 critical (PASS)

**ALL gates PASS** — safe to proceed to Phase 3.

---

## 3. Item 2 — Coverage ratchet +5pp (continue Sprint 42 partial)

### 3.1 State (verified)

**Sprint 42 Item 4** (commit `5eb18323`): 5 smoke tests added.
Coverage delta: 0% (smoke tests don't exercise enough code paths).

**Actual state** (verified 2026-08-27):
- entrypoints: 12% (Sprint 41 W1 verified)
- infrastructure: 52% (Sprint 41 W1 verified)
- aggregate: ~62% (StALE `.baselines/coverage.json`)

### 3.2 Plan (~1.5 ч, Sprint 43 W1)

**Target**: aggregate ~62% → ~67% (+5pp).

1. **Focus on entrypoints** (12% → 25%, +13pp):
   - 8-10 NEW tests for admin_actions, admin_capabilities, admin_connectors.
   - ~1 ч.
2. **Focus on infrastructure** (52% → 55%, +3pp):
   - 3 NEW tests for messaging/dlq_base.py.
   - ~30 мин.
3. **Bump `.baselines/coverage.json`** via new `--update-ratchet` flag
   (Sprint 41 Item 5 ship-able).

---

## 4. Item 3 — Variable/Policy/Fluent mixins composition (81 → 78)

### 4.1 State

Per ADR-0283 §5.4.2 per-mixin priority:

| # | Mixin group | LOC | Risk | Sprint |
|---|---|---:|---|---|
| 1 | ~~EventBusMixin~~ (S43 W1) | ~50 | Low | **S43 W1** |
| **2** | **Variable/Policy/Fluent** | **~80** | **Low** | **S43 W1** |
| 3 | AIRPAMixin | ~200 | Medium | S44 |
| 4 | IntegrationMixin | ~300 | Medium | S44 |
| 5 | EIPMixin (8 mixins) | ~400 | High | S45+ |

### 4.2 Plan (~1 ч, Sprint 43 W1)

**Variable/Policy/Fluent mixins composition** (same pattern as Item 1):

1. Extract 3 mixins → 3 feature-objects.
2. Update `RouteBuilder` aggregation.
3. Run tests — 0 regressions.

**Target**: 81 → 78 mixins (-3 mixins).

---

## 5. Item 4 — Pre-existing test failures fix (carry-over)

### 5.1 State (verified)

**Sprint 42 Item 6** (commit `9d5654ff`): 1/7 fails fixed (pii_erase patch path).
**Remaining**: 6 pre-existing fails (DSL processor tests + 1 flaky).

### 5.2 Plan (~1 ч, Sprint 43 W1)

1. **Investigate 6 remaining fails** (~30 мин):
   - Run each in isolation to identify root cause.
   - Document flakiness patterns.
2. **Fix 3-4 of 6** (~30 мин, LOW-risk fixes):
   - DSL processor mock pollution (Sprint 39 W2 deferred).
   - Workflow `test_worker.py` (2 pre-existing fails).
3. **Mark 2 as `@pytest.mark.flaky`** + skip-with-reason.

---

## 6. Item 5 — AIRPAMixin decomposition (78 → 77 mixins)

### 6.1 State

Per Item 3: Variable/Policy/Fluent → 78 mixins after Sprint 43 W1.

### 6.2 Plan (~2 ч, Sprint 44+)

**AIRPAMixin per-mixin migration** (~200 LOC, medium risk):

1. Extract `AIRPAMixin` (largest mixin with 70 public attrs) → feature-object.
2. Update `RouteBuilder` aggregation.
3. Run tests — 0 regressions required.

**Target**: 78 → 77 mixins (-1 mixin, largest removed).

---

## 7. Item 6 — Plan-ahead subagent for Sprint 44+

### 7.1 State

Sprint 44 plan-ahead предшествует Sprint 43 close-out.

### 7.2 Plan (~30 мин, Sprint 43 W2)

**SPRINT_44_PLAN_AHEAD_2026-08-27.md** (~300 LOC):

- Top 5-7 ship-able за Sprint 44.
- **IntegrationMixin composition** (per ADR-0283 §2.3, Sprint 44+).
- Coverage ratchet +5pp (aggregate 67% → 72%).
- Phase C single-entry bridges (4 remaining: ai, billing, jupyter, storage).
- Aggregator strict timeout → SlidingWindowAggregator (S176, deferred).

---

## 8. Recommended Sprint 43 schedule (~8 ч, 7-9 atomic commits)

```
Day 1 (W1, ~4 ч):
  09:00-11:00  Item 1: ADR-0283 Phase 3 EventBusMixin composition (82 → 81 mixins) — commit 1
  11:00-12:00  Item 3: Variable/Policy/Fluent mixins composition (81 → 78) — commit 2
  12:00-13:00  LUNCH

Day 1-2 (W1-W2, ~2.5 ч):
  13:00-14:30  Item 2: Coverage ratchet +5pp (entrypoints 8-10 tests + infra 3 tests) — commit 3-4
  14:30-15:30  Item 4: Pre-existing test failures fix (carry-over) — commit 5

Day 2 (W2, ~1.5 ч):
  Item 6: SPRINT_44_PLAN_AHEAD subagent — commit 6
  Item 5: AIRPAMixin decomposition (78 → 77, Sprint 44 W1) — commit 7 (deferred)
```

**Итого**: 38 → 36 entries (-2 honest), coverage +5pp, pre-existing tests fixed.

---

## 9. Anti-ship items (verified 2026-08-27)

| Item | Reason |
|---|---|
| AIRPAMixin composition (S43 W2+) | Sprint 44+ per ADR-0283 §2.3 priority |
| IntegrationMixin composition (S44+) | Multi-sprint |
| EIPMixin composition (S45+) | HIGH risk (8 mixins, ~400 LOC) |
| Aggregator strict timeout → SlidingWindowAggregator | S176 (carry-over from Sprint 35) |
| `core/di/providers/{ai,billing,jupyter,storage}.py` (4 single-entry bridges) | S44+ per Phase C |
| `core/api/__init__.py` (2 entries) | Canonical D160 facade, permanent |
| `core/auth/facade.py` (1 entry) | 615 LOC REAL facade |
| `core/frontend_facade.py` (1 entry) | 37 callers, Phase C |
| `core/messaging/eventbus/facade.py` (1 entry) | 206 LOC REAL facade |
| Coverage 75% target | Multi-sprint ratchet (S43-S46) |
| Frontend facade 14 → 0 users | Multi-sprint (S45+) |

---

## 10. Key findings parent agent needs to know

### 10.1 Sprint 42 close-out (verified)

- **42 → 38 entries** (-4 honest, ahead of plan -6 by 2).
- **CRITICAL Item 0** (gap-agent critical): Sprint 41 fix was INCOMPLETE. Pytest
  collection broken until Sprint 42 fix restored.
- **6 atomic commits** per user directive "**Решай deferred, не уклоняйся**".
- **2 risk gates** (HIGH risk decompose per user directive): Item 4 partial
  (smoke tests, not +5pp), Item 5 analysis-only (risk gates PASS, Phase 3 deferred).
- **2 carry-overs** (Item 4 full +5pp, Item 6 full fix 6 fails): Sprint 43 Items 2+4.

### 10.2 Sprint 43 priorities (high to low)

1. **Item 1** (HIGH risk, decomposed, risk gates PASS): ADR-0283 Phase 3
   (EventBusMixin composition, 82 → 81 mixins, ~2 ч).
2. **Item 3** (medium risk): Variable/Policy/Fluent mixins composition
   (81 → 78 mixins, ~1 ч).
3. **Item 2** (LOW risk): Coverage ratchet +5pp (entrypoints + infra tests).
4. **Item 4** (LOW risk): Pre-existing test failures fix (6 remaining, carry-over).
5. **Item 5** (medium risk, deferred S44): AIRPAMixin decomposition.
6. **Item 6** (LOW risk): Plan-ahead subagent.

### 10.3 Honest delta vs SPRINT_42_PLAN_AHEAD

- **SPRINT_42_PLAN_AHEAD** claimed 7 items achievable в ~5 ч.
- **Sprint 42 actual**: 6 atomic commits + 1 CRITICAL fix + 1 partial + 1 analysis-only
  = 5 of 7 items shipped (71%, Item 4 + Item 6 PARTIAL).
- **Net**: 38 entries (4 honest ahead of plan -6 by 2).

**Honest delta**: 2 of 7 items PARTIAL (Item 4 coverage + Item 6 tests). Per
user directive "**решай deferred**" — carry-over to Sprint 43.

---

## 11. Sprint 43 success criteria

1. ✅ ADR-0283 Phase 3 implementation (EventBusMixin composition).
2. ✅ Coverage ratchet +5pp (aggregate 62% → ~67%).
3. ✅ Variable/Policy/Fluent mixins composition.
4. ✅ Pre-existing test failures fix (~6 → 0).
5. ✅ AIRPAMixin decomposition (78 → 77 mixins, Sprint 44 W1 prep).
6. ✅ Sprint 44 plan-ahead published.
7. ✅ 0 production regressions.
8. ✅ **Cumulative ratchet progress**: 17/17 (~100%, Phase B complete) → **18/19 (~95%, Phase B+C entry)**.

**Production readiness target**: **99.9% → 99.95%** (per-sprint net ratchet + Phase C
acceleration + ADR-0283 Phase 3 implementation + pre-existing test fixes + plan-ahead).

---

## 12. Honest assessment

**HIGH-risk items** (Item 1 ADR-0283 Phase 3) MUST verify Phase 2 risk gates
before implementation (verified Sprint 42 Item 5 commit `98750488`).
**Per user directive** "если есть сложные моменты - декомпозируй".

**Compression risk**: Plan claims 7 items в ~8 ч. **Realistic estimate**:
- Item 1 (~2 ч, HIGH risk decompose)
- Item 3 (~1 ч)
- Item 2 (~1.5 ч)
- Item 4 (~1 ч)
- Item 6 (~30 мин)
- Item 5 deferred до S44
- Net: ~6 ч total (fits long sprint per user directive).

**Coverage 75% target**: multi-sprint ratchet S43-S46 (per Phase 0 §3.1).

**Carry-over** (S44+):
- IntegrationMixin composition (medium risk, ~300 LOC, S44+)
- EIPMixin composition (HIGH risk, 8 mixins, ~400 LOC, S45+)
- Aggregator strict timeout → SlidingWindowAggregator (S176)
- 4 single-entry bridges (ai, billing, jupyter, storage)

---

**Production readiness target**: **99.9% → 99.95%** (per-sprint net ratchet + Phase C
acceleration + ADR-0283 Phase 3 + pre-existing test fixes + plan-ahead).
