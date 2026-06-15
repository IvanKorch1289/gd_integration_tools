# S144 W1 — Pre-flight Factcheck

> **Date:** 2026-06-15 (post-S143 closure, HEAD `c8c6f62`)
> **Author:** sprint-execution agent (S144 W1)
> **Result:** SCOPE Bounded. 5 test_fails closeable + 2 TD-013 page regroups.

## Context

S143 closed on `sprint/td013-pilot-B` side branch (8 ahead of origin/master).
176 ADRs, score 9.9 (stable).

## 14 test_features_*.py fails — breakdown (S143 W1 + S143 closure verification)

| Test | Expected | Current | Missing/Issue | Action S144 |
|---|---|---|---|---|
| `test_features_ai.py` | 9 fields | 10 | `rag_cache_l2_semantic` defaults to True (pre-existing design); 10≠9 (extra `prompt_registry_gateway_wiring`) | OUT OF SCOPE per Rule #124 |
| `test_features_resilience.py` | 6 fields | 4 | 2 missing: `auto_scaler_process_level`, `auto_scaler_task_level` | S144 W2 — add 2 fields |
| `test_features_sprint19_ai.py` | 11 fields | 8 | 3 missing: `adaptive_timeout_enabled`, `admin_react_mvp`, `adaptive_rag_strategy_enabled` | S144 W2 — add 3 fields |
| `test_features_sprint5_dsl.py` | 25 fields | 13 | 12 missing (biggest blocker) | S145 W2-W3 — split into 2 commits |
| `test_features_sprints_24_27.py` | 13 fields | 13 | `ai_gateway_enforce` defaults True (pre-existing design) | OUT OF SCOPE per Rule #124 |

**S144 closeable**: 5 fails (2 ResilienceFlags + 3 Sprint19AIFlags + Sprint19AIFlags inherits test).

## TD-013 Status

- 69 top-level Streamlit pages
- 4 group structure files (`_groups/admin/`, `_groups/ai/`, `_groups/dsl/`, `_groups/home/`, `_groups/ops/`, `_groups/workflow/`)
- 1 page regrouped (S142 W3 PoC: `00_Home.py` → `_groups/home/home_page/`)
- 68 pages remaining to regroup

S144 candidates (small, well-bounded):
- `13_Cron_Builder.py` (K3 W2 cron UI)
- `14_Cron_Dashboard.py` (cron dashboard)
- `11_Routes.py` (K3 routes)
- `10_Orders.py` (K1 orders)

## S144 Plan (5 waves, Ponytail-mode atomic)

| Wave | Scope | Commit | Test Δ |
|---|---|---|---|
| W1 | (this factcheck) | analysis-only | 0 |
| W2 | ResilienceFlags (2 fields) + Sprint19AIFlags (3 fields) | atomic | -5 (14→9) |
| W3 | TD-013: `13_Cron_Builder.py` → `_groups/cron/builder/` | atomic | 0 |
| W4 | TD-013: `14_Cron_Dashboard.py` → `_groups/cron/dashboard/` | atomic | 0 |
| W5 | ADR-0227 + CHANGELOG + INDEX | closure | 0 |

**Total**: 4 atomic code commits + 1 closure = 5 commits.

## Stale Backlog Items Cleared

| Item | Status | Action |
|---|---|---|
| 1 NEW sibling layer (rag_service/search_mixin.py) | Not found in `tools/check_layers.py` output | Likely already fixed S140-S142 |
| AIFlags fails | 2 pre-existing (rag_cache_l2_semantic=True, 10≠9) | OUT OF SCOPE per Rule #124 |
| Sprints2427Flags instantiate fail | Pre-existing (ai_gateway_enforce=True) | OUT OF SCOPE per Rule #124 |

## S145+ Plan (preview)

- **S145**: Sprint5DSLFlags 12 missing fields (W2 = 6, W3 = 6) + 1 pre-existing fix (W4)
- **S146**: 73 core + 29 services pre-existing triage (5-10 actionable picks)

## Verification Plan (post-execution)

- `tools/check_layers.py` → 0 NEW
- `pytest tests/unit/core/config/test_features_*.py` → net ≤ -5 fails
- Score: 9.9 (maintained)
- TD-013: 1 → 3 pages regrouped (cumulative)

## Stop Conditions

- Sibling commits to `master` while in W2-W4 (worktree management)
- New layer violation (block + analyze)
- Discovery of >5 NEW TD items (scope re-evaluation)

## Refs

- ADR-0226 (S143 closure)
- `reports/sprint/s143_w1_factcheck.md`
- Ponytail skill (active, level full)
- Skill: verify-analysis-claims
- Skill: systematic-debugging
- Skill: sprint-execution (Rule #130: W1 = fact-check)
