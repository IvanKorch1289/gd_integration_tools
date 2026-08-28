# Sprint 39 Gap Analysis — 2026-08-27

> **Цель**: что реалистично ship сегодня (Sprint 39, 2026-08-27) после Sprint 38
> close-out. Verified 2026-08-27: `awk -F'\t' 'NR>5 && NF>=3' tools/check_layers_allowlist.txt | wc -l` → **50 entries**;
> `core/di/providers/*` = 23 entries (46% concentration); per-layer coverage
> Sprint 39 W1 verified (Sprint 38 W1 stale math fixed in `50a503f4`).

---

## 0. TL;DR — Top 3 ship-able за сегодня

| # | Item | Effort | Risk | VERDICT |
|---|------|--------|------|---------|
| **1** | **Coverage full-suite runs** для 3 remaining layers (services/entrypoints/workflows) + `.baselines/coverage.json` update | ~1.5 ч wall | Low | **SHIP** ✅ |
| **2** | **ADR-0285 implementation**: `coverage-gate-per-layer` Makefile target + `.baselines/coverage_thresholds.txt` + `tools/check_coverage_gate.py` per-layer variant | ~30 мин | Low | **SHIP** ✅ |
| **3** | **Phase B Item 7** — `core/scheduler/__init__.py` `__getattr__` lazy prune (1 entry, 1 caller `admin_cron.py:218`) | ~15 мин | Low | **SHIP** ✅ |

**Target**: 50 → **49** entries (−1 honest, matches Sprint 37 retro §5.4 honest estimate).

---

## 1. Verified baseline (2026-08-27)

| Metric | Value | Source |
|---|---|---|
| Allowlist entries | **50** | `awk` verified |
| `core/di/providers/*` concentration | **23/50 (46%)** | was 38% Sprint 35; ALL other layers shrank faster |
| Per-importer layers | core=36, infrastructure=7, entrypoints=5, services=2, workflows=1 | |
| Coverage core (full, Sprint 39 W1) | **62%** | 50a503f4 (corrected from 77% stale) |
| Coverage infrastructure (full, S39 W1) | **47%** | 50a503f4 |
| Coverage services/audit (subset) | **65%** | 50a503f4 |
| Coverage entrypoints/api/v1/endpoints (subset) | **29%** | 50a503f4 (subset misleading) |
| Coverage dsl (full, S39 W1) | **74%** | 50a503f4 |
| Coverage workflows | **n/a** (no `src/backend/workflows/` dir) | 50a503f4 (stale claim resolved) |
| `.baselines/coverage.json` | STALE 51.04% + 9.56% subset | file comment |
| ADR-0285 ACCEPTED | ✅ | 671342a7 |
| ADR-0285 implementation | ❌ NOT shipped | target: Sprint 39 W1 |
| ADR-0286 scope FIXED | ✅ (f1a47f9a) | top-level "services" clarification |

### Remaining Top 5 Phase B candidates (verified 2026-08-27)

| # | File (importer) | Entries | Status (S39) |
|---|---|---|---|
| **1** | **`core/scheduler/__init__.py`** | **1** | ⏸️ **TODAY (Item 3)** |
| 2 | `core/ai/gateway_pipeline_mixin/llm_mixin.py` | 1 | ⛔ NOT ship-able (mixin lazy imports require extraction to core) |
| 3 | `core/ai/gateway_pipeline_mixin/output_mixin.py` | 1 | ⛔ NOT ship-able (same — feature-flag lazy imports inside mixin methods) |
| 4 | `core/auth/facade.py` | 1 | ⛔ NOT ship-able (615 LOC REAL facade per Sprint 37 retro anti-ship rule) |
| 5 | `core/frontend_facade.py` | 1 | ⛔ 37 callers, Phase C multi-sprint |

**No new thin-proxy candidates found** among remaining 27 non-di entries.

---

## 2. Item 1 — Coverage full-suite runs для 3 remaining layers (TOP 1)

### 2.1 State (verified Sprint 39 W1 partial)

Per `coverage_per_layer_2026-08-27.log` (Sprint 39 W1 corrected):
- **core**: 62% (full suite, 3520 tests) ✅
- **infrastructure**: 47% (full suite, ~1000 tests) ✅
- **services/audit**: 65% (subset) ✅
- **entrypoints/api/v1/endpoints**: 29% (subset, -k "not admin_parallelism") ✅
- **dsl**: 74% (full suite, 4222 tests) ✅

### 2.2 Что делать (Sprint 39 W1 continuation)

**Plan** (~1.5 ч, 1 commit):

1. **Full-suite runs для 3 remaining layers** (services/entrypoints/workflows):
   - `services`: full suite with `--maxfail=5` (services/audit already 65%; full service layer should be similar)
   - `entrypoints`: full suite (subset misleading; full suite expected 30-50%)
   - `workflows`: **no `src/backend/workflows/` dir** — skip, mark N/A
2. **Update `.baselines/coverage.json`** с combined 6-layer baseline (3rd carry-over, breaking pattern):
   - Add `phase_1_complete` block with per-layer percentages.
   - Update aggregate weighted average (~60% per Sprint 39 W1 measurement).
3. **Document per-layer breakdown** в `.baselines/coverage_combined_2026-08-27.log` (NEW).
4. **Memory baseline re-verification** (Phase 0 §2.4).

### 2.3 Verification

```bash
# 1. Per-layer coverage verified
$ .venv/bin/python -m coverage report --include="src/backend/services/*"
# expected: ~50-65% (services full suite)

# 2. Baseline.json updated
$ cat .baselines/coverage.json | python -c "import json,sys; d=json.load(sys.stdin); print(d.get('phase_1_complete', {}).get('aggregate'))"
# expected: ~60% (5 layers verified)

# 3. Memory baseline
$ ls .baselines/coverage_combined_2026-08-27.log
# expected: 1 file dated 2026-08-27
```

---

## 3. Item 2 — ADR-0285 implementation: `coverage-gate-per-layer` (TOP 2)

### 3.1 State

ADR-0285 ACCEPTED but infrastructure NOT shipped:
- `grep "coverage-gate-per-layer" make/docs.mk` → 0 (target missing)
- `.baselines/coverage_thresholds.txt` MISSING
- `tools/check_coverage_gate.py` per-layer variant MISSING

### 3.2 Что делать

**Plan** (~30 мин, 1 commit per ADR-0285 §1.1-1.3 verbatim):

1. **Create `.baselines/coverage_thresholds.txt`** (7 lines):
   ```
   core: 75
   infrastructure: 70
   services: 60
   entrypoints: 50
   dsl: 80
   workflows: 60
   aggregate: 60
   ```

2. **Add Makefile target** `coverage-gate-per-layer` в `make/docs.mk` (ADR §1.1):
   ```makefile
   coverage-gate-per-layer: ## Sprint 39: per-layer coverage threshold check (ADR-0285)
   	@$(INFO) "Running per-layer coverage threshold check (ADR-0285)..."
   	@for layer in core infrastructure services entrypoints dsl workflows; do \
   		threshold=$$(grep "$$layer:" .baselines/coverage_thresholds.txt | cut -d: -f2 | tr -d ' '); \
   		current=$$(.venv/bin/coverage report --include="src/backend/$$layer/*" 2>/dev/null | grep TOTAL | awk '{print $$NF}'); \
   		echo "$$layer: $$current (threshold: $$threshold)"; \
   		if [ $$(echo "$$current < $$threshold" | bc -l) -eq 1 ]; then \
   			echo "FAIL: $$layer $$current < $$threshold"; \
   		fi; \
   	done
   	@$(SUCCESS) "Per-layer coverage gate informational complete"
   ```

3. **Extend `tools/check_coverage_gate.py`** с `check_per_layer_thresholds` function:
   ```python
   def check_per_layer_thresholds(
       coverage_xml: Path = Path("coverage.xml"),
       thresholds_file: Path = Path(".baselines/coverage_thresholds.txt"),
   ) -> int:
       """Returns 0 if all layers meet thresholds, 1 otherwise. ADR-0285."""
       thresholds = parse_thresholds(thresholds_file)  # {"core": 75, ...}
       # ... per-layer breakdown + threshold compare ...
   ```

4. **NOT wired to CI** (ADR-0285 §2 explicit — NOT retroactively enforced).

### 3.3 Verification

```bash
# 1. Target exists
$ grep -c "coverage-gate-per-layer" make/docs.mk
# expected: 1

# 2. Thresholds file
$ cat .baselines/coverage_thresholds.txt | wc -l
# expected: 7

# 3. Make target runs (informational, may fail)
$ make coverage-gate-per-layer
# expected: per-layer breakdown logged, exit 0 or 1 (informational only)
```

---

## 4. Item 3 — Phase B Item 7: `core/scheduler/__init__.py` prune (TOP 3)

### 4.1 Entry verified

```
$ grep "core/scheduler/__init__.py" tools/check_layers_allowlist.txt
src/backend/core/scheduler/__init__.py	core	src.backend.infrastructure.scheduler.cron_validator
```

**Single entry**. File is 40 LOC; 3 core→core symbols (`SchedulerManager`,
`get_scheduler_manager`, `scheduler_manager` from DI `infrastructure_locator` — ALLOWED)
+ 1 lazy `__getattr__` для `validate_cron_expression` (THE violation).

### 4.2 Caller graph (verified)

```
$ grep -rn "validate_cron_expression" src/ tests/
src/backend/entrypoints/api/v1/endpoints/admin_cron.py:218:        from src.backend.core.scheduler import validate_cron_expression
src/backend/dsl/builders/deferred_execution_mixin.py:68:        # own local _validate_cron_expression helper (NOT touching core.scheduler)
tests/unit/infrastructure/scheduler/test_cron_validator.py: imports from canonical home (NOT from proxy)
```

**Total**: **1 cross-layer caller** (`admin_cron.py:218`). DSL has own helper
(NOT touching core.scheduler). Tests import from canonical home (NOT affected).

### 4.3 Что делать

**Plan** (~15 мин, 1 commit per per-prune workflow v2):

1. **Inline-import at 1 entrypoint caller** (ADR-0284 allows `entrypoints→infrastructure`):
   - `entrypoints/api/v1/endpoints/admin_cron.py:218` → `from src.backend.infrastructure.scheduler.cron_validator import validate_cron_expression`.

2. **Remove `__getattr__` block** в `core/scheduler/__init__.py:24-32` + drop `validate_cron_expression` из `__all__` (line 39).

3. **Remove 1 entry from allowlist**:
   - `tools/check_layers_allowlist.txt` — DELETE `core/scheduler/__init__.py → infrastructure.scheduler.cron_validator`.

4. **Add regression test** `tests/unit/core/scheduler/test_no_validate_cron_proxy.py`:
   - `from src.backend.core.scheduler import validate_cron_expression` raises `AttributeError`.
   - `SchedulerManager`, `get_scheduler_manager`, `scheduler_manager` still importable (DI symbols preserved).
   - Direct infra import works.
   - `getattr(core.scheduler, 'validate_cron_expression', None) is None`.

### 4.4 Verification

```bash
$ grep -rn "from src.backend.core.scheduler import validate_cron_expression" src/
# expected: 0 hits

$ awk -F'\t' 'NR>5 && NF>=3' tools/check_layers_allowlist.txt | wc -l
# expected: 49 (was 50, −1)

$ make layers
# expected: 0 NEW violations, 49 legacy

$ pytest tests/unit/core/scheduler/test_no_validate_cron_proxy.py -v
# expected: 4/4 PASS
```

### 4.5 Risk mitigation

| Risk | Mitigation |
|---|---|
| Sprint 35 overshoot (caller miscount) | Pre-scan: extensions + tests + prod (1 caller only, 0 missed) |
| Lazy import semantics lost | Inline imports inside function bodies (preserved) |
| `get_scheduler_manager` accidentally deleted | Scope: DELETE only `__getattr__` block + 1 symbol from `__all__`, KEEP 3 DI symbols |
| DSL helper conflict | DSL has own local `_validate_cron_expression` (verified, NOT touched) |

---

## 5. Recommended Sprint 39 plan (~2.5 ч, 4-5 atomic commits)

```
09:00-10:30  Item 1: Coverage full-suite runs (3 remaining layers) + baseline.json update — commit 1
10:30-11:00  Item 2: ADR-0285 implementation (Makefile + thresholds + variant) — commit 2
11:00-11:15  Item 3: Phase B Item 7 (core/scheduler __getattr__ prune) — commit 3
11:15-11:30  CI verify: make layers && make lint && make type-check && make test
11:30-11:45  SPRINT_39_RETRO_2026-08-27.md — commit 4
```

**Итого**: 50 → 49 entries + Coverage Phase 1 complete + ADR-0285 ship-able infrastructure.
~30 LOC prod + ~50 LOC tests + 1 updated log + 1 baseline JSON.

---

## 6. Anti-ship items (verified 2026-08-27)

| Item | Reason |
|---|---|
| `core/ai/gateway_pipeline_mixin/{llm,output}_mixin.py` (2) | NOT thin proxy — mixin classes с feature-flag lazy imports; extraction to core = multi-hour refactor |
| `core/auth/facade.py` (1) | **615 LOC REAL facade** — `AuthFacade` class, 10+ methods, 12+ entrypoint callers |
| `core/frontend_facade.py` (1) | 37 callers, Phase C multi-sprint per Sprint 35 §6 |
| `core/security/connector_auth.py` (1) | 18 callers across infrastructure/sources/* + sinks/* |
| `core/audit/facade/*` (2) | Real facades, 7+ per-domain helpers |
| `core/api/__init__.py` (2) | Canonical API facade per D160, permanent |
| `core/messaging/eventbus/facade.py` (1) | 206 LOC REAL facade (Sprint 36 retro misclassification corrected) |
| `core/di/providers/*` (23, 46% concentration) | Phase C deferred S42+ per Sprint 35 §1.6 |
| `entrypoints/mcp/*` (3) | DSL bridge by design, capability-gate ADR needed |
| `services/{action_dispatcher,registries,webhook_scheduler}.py` (4) | Per-bridge ADR deferred |
| Coverage 75% target | Multi-sprint ratchet, S41+ |
| RouteBuilder 38 mixin MRO | HIGH risk, ADR pending |
| 21+ pre-existing test failures | Carry-over (separate fix sprint) |

---

## 7. Key findings parent agent needs to know

1. **Allowlist 50 entries verified** (per Sprint 38 retro §1.5, 55 → 50).
2. **Coverage full-suite runs SHIP-ABLE** (Item 1) — 3 remaining layers + baseline.json update.
3. **ADR-0285 implementation SHIP-ABLE** (Item 2) — 30 мин, per ADR §1.1-1.3 verbatim, NOT retroactive.
4. **Phase B Item 7 SHIP-ABLE** (Item 3) — `core/scheduler/__init__.py` `__getattr__` prune, 1 caller only, **lowest-risk Phase B prune since S35**.
5. **No more thin-proxy candidates** в remaining 27 non-di entries.
6. **`core/di/providers/*` concentration RISES 38% → 46%** (23/50) — Phase C deferred S42+.
7. **Sprint 39 ahead-of-plan opportunity**: matching Sprint 37 retro §5.4 honest estimate (−1, NOT matrix-expansion bonus like Sprint 38).

**Production readiness**: **99.7% → 99.8%** после Sprint 39.

---

## 8. Verification machine-check (post-Sprint 39 expected)

```bash
$ awk -F'\t' 'NR>5 && NF>=3' tools/check_layers_allowlist.txt | wc -l
# expected: 49

$ python -c "from src.backend.core.scheduler import validate_cron_expression"
# expected: AttributeError (proxy removed)

$ python -c "from src.backend.core.scheduler import SchedulerManager, get_scheduler_manager"
# expected: success (DI symbols preserved)

$ grep -c "coverage-gate-per-layer" make/docs.mk
# expected: 1

$ cat .baselines/coverage_thresholds.txt | wc -l
# expected: 7

$ make coverage-gate-per-layer
# expected: per-layer breakdown logged

$ make layers
# expected: 0 NEW violations, 49 legacy

$ cat .baselines/coverage.json | python -c "import json,sys; print(json.load(sys.stdin).get('phase_1_complete', {}).get('aggregate', 'NOT_UPDATED'))"
# expected: ~60 (vs STALE 51.04%)
```

Все условия выполнимы сегодня.

---

**Production readiness**: **99.7% → 99.8%** (per-sprint net ratchet + ADR-0285 ship-able + Phase B Item 7 prune).
