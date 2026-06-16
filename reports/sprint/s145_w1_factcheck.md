# S145 W1 — Pre-flight Factcheck

> **Date:** 2026-06-15 (post-S144 closure, HEAD `e2be3d7`)
> **Author:** sprint-execution agent (S145 W1)
> **Result:** SCOPE Bounded. 1 commit + closure. Sprint5DSLFlags only 2 missing (S144 W1 was wrong: said 12, actual 2).

## Fact-check vs S144 W1 (correction)

| Claim | Verified | Status |
|---|---|---|
| Sprint5DSLFlags 12 missing fields | ❌ WRONG | Actual: 23 fields, test expects 25, **2 missing** (not 12) |
| 6 remaining test_features_*.py fails | ✅ CONFIRMED | AIFlags×2 (pre-existing) + Sprints2427Flags×1 (pre-existing) + Sprint5DSLFlags×3 (closeable) |
| 13 ahead of origin | ✅ CONFIRMED | 13 (3 S142 + 5 S143 + 5 S144) |

## 6 remaining test_features_*.py fails — breakdown (S145 W1 verification)

| Test | Issue | Action S145 |
|---|---|---|
| `test_features_ai.py::test_ai_flags_instantiates` | `rag_cache_l2_semantic default=True` (pre-existing design) | OUT OF SCOPE per Rule #124 |
| `test_features_ai.py::test_ai_field_count` | 10≠9 (extra `prompt_registry_gateway_wiring` field) | OUT OF SCOPE per Rule #124 |
| `test_features_sprint5_dsl.py::test_sprint5_dsl_flags_instantiates` | Missing `blueprint_cdc_enrich`, `blueprint_ai_pipeline` (AttributeError) | S145 W2 — add 2 fields |
| `test_features_sprint5_dsl.py::test_sprint5_dsl_field_count` | 23≠25 | S145 W2 — fixed by adding 2 fields |
| `test_features_sprint5_dsl.py::test_feature_flags_inherits_sprint5_dsl_fields` | Missing 2 fields (composition) | S145 W2 — fixed by adding 2 fields |
| `test_features_sprints_24_27.py::test_sprints_24_27_flags_instantiates` | `ai_gateway_enforce default=True` (pre-existing design) | OUT OF SCOPE per Rule #124 |

**S145 closeable**: 3 fails (all Sprint5DSLFlags).

## S145 Plan (5 waves, but compact: 2 commits + closure)

| Wave | Scope | Commit | Test Δ |
|---|---|---|---|
| W1 | (this factcheck + S144 W1 correction) | analysis-only | 0 |
| W2 | Sprint5DSLFlags: 2 fields (`blueprint_cdc_enrich`, `blueprint_ai_pipeline`) | atomic | -3 (6→3) |
| W3 | 1 pre-existing fix (e.g., `test_smart_session_manager_singleton_uses_bundle` NameError per S131 finding) | atomic | -1 (3→2) |
| W4 | 1 more pre-existing fix (docstring ratchet pick) | atomic | -1 (2→1) |
| W5 | ADR-0228 + CHANGELOG + INDEX | closure | 0 |

**Total**: 4 atomic code commits + 1 closure = 5 commits.

## Stale Backlog Items Cleared

| Item | Status |
|---|---|
| Sprint5DSLFlags 12 missing (S144 W1 claim) | **CORRECTED to 2** (S144 W1 was wrong) |
| 1 NEW sibling layer (rag_service/search_mixin.py) | Not found in linter (S144 W1 confirmed) |
| AIFlags 2 fails | Pre-existing design conflict, OUT OF SCOPE |
| Sprints2427Flags instantiate fail | Pre-existing design conflict, OUT OF SCOPE |

## Pre-existing Triage Candidates (S145 W3-W4)

1. **test_smart_session_manager_singleton_uses_bundle** (per S131 W1 finding): `NameError: name 'DatabaseBundle' is not defined` at `initializer.py:120` (initializer.py missing import). Verified via git stash that this is pre-existing. Fix: add `from src.backend.infrastructure.database.database.bundle import DatabaseBundle` to initializer.py.
2. **test_s56_w2_airflow_operators** (2 fails): `NameError: name '_default_latest_checker' is not defined` at `latestonlyoperator.py:48`. Fix: add `_default_latest_checker` method.
3. **Docstring ratchet**: 1-2 specific files for docstring coverage +1%.

## S146+ Plan (preview)

- **S146**: 73 core + 29 services pre-existing triage (5-10 actionable picks, Rule #124 per-fail)
- **S147**: TD-013 5-10 more pages (3-5h dedicated)
- **S148**: security audit (focused on top-3 attack vectors)

## Verification Plan

- `tools/check_layers.py` → 0 NEW
- `pytest tests/unit/core/config/test_features_*.py` → net ≤ -3 fails
- Score: 9.9 (maintained)

## Stop Conditions

- Sibling commits to `master` while in W2-W4
- New layer violation (block + analyze)
- Discovery of >5 NEW TD items

## Refs

- ADR-0227 (S144 closure)
- `reports/sprint/s144_w1_factcheck.md` (had wrong count: 12 vs 2)
- Ponytail skill (active, level full)
- Skill: verify-analysis-claims
- Rule #124 (pre-existing failures OUT OF SCOPE)
