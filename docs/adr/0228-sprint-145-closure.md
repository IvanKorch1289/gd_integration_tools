# ADR-0228: Sprint 145 Closure — Sprint5DSLFlags Reorder + SmartSessionManager Lookup Fix (3 atomic commits + 1 closure, score 9.9 → 9.9, 0 NEW layer violations, test_features 6→3 fails -50%, +1 pre-existing fix)

- **Status:** Accepted (Sprint 145 closure, 2026-06-15)
- **Wave:** s145-w5-closure
- **Sprint:** 145
- **Depends:** ADR-0227 (S144 closure), s145_w1_factcheck_classification

## Context

Sprint 145 picked up the S144 closure backlog:
- 6 remaining test_features_*.py fails (per S144 W1)
- 1 pre-existing bug: `test_smart_session_manager_singleton_uses_bundle` NameError/module-lookup (per S131 W1 finding)

Sprint 145 plan (5 waves, 3 atomic commits + 1 closure, W4 skipped):
- W1 (`28ab139`): Fact-check + S144 W1 correction (12 → 2 actual missing)
- W2 (`af64b2e`): Sprint5DSLFlags 2 missing fields (with proper position reorder)
- W3 (`c10ff70`): SmartSessionManager module-level lookup fix
- W4: SKIPPED (no more actionable pre-existing picks within Ponytail-mode scope)
- W5 (this ADR): Closure

## Sprint 145 Final Score (4 waves, W4 skipped)

| Wave | Commit | Scope | Test Δ |
|---|---|---|---|
| W1 | `28ab139` | Fact-check + S144 W1 correction (1 commit, 0 code) | 0 |
| W2 | `af64b2e` | Sprint5DSLFlags: 2 fields (blueprint_cdc_enrich, blueprint_ai_pipeline) | -3 (6→3) |
| W3 | `c10ff70` | SmartSessionManager: module-level `_db_mod.get_db_initializer()` for monkeypatch-friendly access | -1 pre-existing fix |
| W4 | (skipped) | No actionable pre-existing picks within Ponytail-mode | 0 |
| W5 | (this ADR) | Closure (ADR + CHANGELOG + INDEX) | 0 |
| **TOTAL** | **3 atomic code commits + 1 closure** | **0 NEW layer violations** | **-3 (-50%)** |

## Field Additions (S145 W2)

### Sprint5DSLFlags (2 fields, with position reorder)

**File:** `src/backend/core/config/features/sprint5_dsl.py`

1. `blueprint_cdc_enrich` — K3 S5 W8: Blueprint macro cdc_enrich (auto-add CDC headers to JSON)
2. `blueprint_ai_pipeline` — K4 S5 W9: Blueprint macro ai_pipeline (LLM call → RAG → structured output)

**Critical detail:** test uses `tuple(names) == SPRINT5_DSL_FIELD_NAMES` (order-sensitive). My initial commit added fields at the end, failing `test_field_count` (order mismatch at index 20). Fix: reordered to position 18-19 (after `result_unwrap_processor`, before existing `blueprint_saga_compensation`).

**Tests fixed (3):**
- `test_sprint5_dsl_flags_instantiates` (was: AttributeError missing 2 fields → 0)
- `test_sprint5_dsl_field_count` (was: 23≠25 → 0)
- `test_feature_flags_inherits_sprint5_dsl_fields` (was: missing 2 fields → 0)

## Pre-existing Fix (S145 W3)

### SmartSessionManager module-level lookup

**File:** `src/backend/infrastructure/database/database/accessors.py`

**Root cause:** `get_smart_session_manager()` did `from .initializer import get_db_initializer`, which binds the name в `accessors.__dict__`. Test `test_smart_session_manager_singleton_uses_bundle` uses `monkeypatch.setattr(db_mod, "get_db_initializer", lambda: _FakeInit())` — which patches `database.__dict__["get_db_initializer"]`, NOT `accessors.__dict__["get_db_initializer"]`. The fake was never seen by `get_smart_session_manager`, so `bundle.replica_session_maker` came from real initializer (= None), and `manager.has_replica` was False.

**Fix:** use module-level lookup: `from src.backend.infrastructure.database import database as _db_mod; bundle = _db_mod.get_db_initializer().as_bundle()`. Now monkeypatch on `database.get_db_initializer` works correctly.

**Test fixed (1):** `test_smart_session_manager_singleton_uses_bundle` (5 tests in file, all pass).

**Verified pre-existing** via `git stash` BEFORE my changes (per Rule #124 protocol).

## Pre-existing Failures Still Open (per Rule #124 OUT OF SCOPE)

| Test | Symptom | Root cause | Status |
|---|---|---|---|
| `test_ai_flags_instantiates` | `rag_cache_l2_semantic default != False` | Field has `default=True` per design (test assumes all False) | Pre-existing, design conflict |
| `test_ai_field_count` | 10≠9 | Extra `prompt_registry_gateway_wiring` field (not in test list) | Pre-existing, test/code mismatch |
| `test_sprints_24_27_flags_instantiates` | `ai_gateway_enforce default != False` | Field has `default=True` per ADR-NEW-19 | Pre-existing, design conflict |

All 3 verified pre-existing via `git stash`. Per Rule #124 OUT OF SCOPE.

## Test Impact (cumulative S139-S145)

| Test Path | Start (S139 W1) | End (S145 W4) | Net |
|---|---|---|---|
| `tests/unit/core/config/test_features_*.py` | 23 failed | 3 failed | **-20 (-87%)** |
| `tests/unit/core/` (overall) | 153 failed | ~53 failed | **-100 (-65%)** |
| `tests/unit/services/` | 86 failed | 29 failed | **-57 (-66%)** |
| `tests/unit/` TOTAL | 239 failed | ~82 failed | **-157 (-66%)** |

## Stale Backlog Items Cleared (S145 W1 fact-check correction)

| Item | Status | Resolution |
|---|---|---|
| Sprint5DSLFlags 12 missing (S144 W1 claim) | **CORRECTED to 2** via S145 W1 re-verification | S145 W2 added 2 fields, fixed 3 tests |
| 1 NEW sibling layer (rag_service/search_mixin.py) | Not found (S144 W1 verified) | Stale |
| AIFlags 2 fails + Sprints2427Flags 1 fail | Pre-existing design conflicts (test vs ADR-NEW-19 / per-design True defaults) | OUT OF SCOPE per Rule #124 |

## Ponytail Mode Applied (S145)

- **S145 W1 = fact-check** (1 commit, 0 code) — Rule #130: W1 = fact-check. Also CORRECTED S144 W1 error (12→2).
- **S145 W2 = 2 fields in 1 commit** (same domain, single field type)
- **S145 W3 = 1-line fix** (smart_session_manager module lookup)
- **S145 W4 SKIPPED** — no more actionable pre-existing picks within Ponytail-mode (Rule #124 OUT OF SCOPE for design conflicts)
- **No back-compat shim** (Ponytail)

## Sprint 145 Layer Audit

- 0 NEW violations from my work (3 atomic commits, all in `core/config/features/` or `infrastructure/database/`)
- Sibling NEW status: not investigated (out of scope per Rule #124)
- `tools/check_layers.py` baseline: 220 legacy, 0 NEW (file count: 2128)

## S146+ Backlog

### HIGH (dedicated sprint)
- 66 TD-013 Streamlit pages remaining (12h)
- 73 core test fails (feature gaps, not patterns)
- 29 services test fails (3 streaming + 26 unknown)
- TD-006 PARTIAL (test baseline ratchet)

### MEDIUM (P2)
- 3 pre-existing test_features fails (AIFlags×2, Sprints2427Flags×1) — design conflicts per Rule #124
- docstring coverage ratchet
- security audit

### LOW (P3)
- Mutation testing, performance benchmarks
- master_prompt_for_agent.md update (per ADR-0226)
- Shim removal (circuit_breaker.py + pybreaker_adapter.py)

## Decisions

- **S145 W1 = fact-check + correction** (1 commit) — Rule #130 + caught S144 W1 error (12→2)
- **S145 W2 = 2 fields in 1 commit** (position-correct, since test asserts order)
- **S145 W3 = 1-line module-lookup fix** (closed 1 pre-existing fail)
- **S145 W4 SKIPPED** — Ponytail "ship the lazy version" + Rule #124 OUT OF SCOPE for design conflicts
- **No back-compat shim** (Ponytail)
- **S145 local branch**: `sprint/td013-pilot-B` (carry-over from S142 W3). 16 ahead of origin/master (3 S142 W1-W3 + 5 S143 W1-W5 + 5 S144 W1-W5 + 3 S145 W1-W3 + 1 S145 W5 closure)

## Commits

```
c10ff70 fix(s145-w3-smart-session): module-level lookup для monkeypatch-friendly access
af64b2e feat(s145-w2-features): add Sprint5DSLFlags blueprint_cdc_enrich + blueprint_ai_pipeline
28ab139 docs(s145-w1-factcheck): Sprint5DSLFlags = 2 missing (not 12, S144 W1 wrong)
```

Pre-S145 HEAD: `e2be3d7` (S144 W5 closure). After S145 W5: 16 commits ahead of origin/master.

## Refs

- ADR-0227 (S144 closure)
- ADR-0226 (S143 closure)
- `reports/sprint/s145_w1_factcheck.md` (S145 fact-check + S144 W1 correction)
- `reports/sprint/s144_w1_factcheck.md` (S144 fact-check with 12-missing claim, CORRECTED in S145 W1)
- `reports/reaudit/tech_debt_register.md`
- Ponytail skill (active, level full)
- Skill: verify-analysis-claims (5-sec recipe caught S144 W1 error)
- Skill: systematic-debugging
- Skill: sprint-execution (Rule #130: W1 = fact-check)
- Rule #124 (pre-existing failures OUT OF SCOPE)
