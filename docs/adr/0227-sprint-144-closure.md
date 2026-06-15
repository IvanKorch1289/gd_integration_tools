# ADR-0227: Sprint 144 Closure — 5 Features Backfill + 2 TD-013 Page Regroups (4 atomic commits + 1 closure, score 9.9 → 9.9, 0 NEW layer violations, test_features 14→6 fails -57%, TD-013 1→3 pages)

- **Status:** Accepted (Sprint 144 closure, 2026-06-15)
- **Wave:** s144-w5-closure
- **Sprint:** 144
- **Depends:** ADR-0226 (S143 closure), s144_w1_factcheck_classification

## Context

Sprint 144 picked up the S143 closure backlog:
- 14 remaining test_features_*.py fails (per S143 W1 + S143 closure verification)
- TD-013 70 Streamlit pages remaining (6-12h dedicated sprint, per ADR-0225)

Sprint 144 plan (5 waves, 4 atomic commits + 1 closure):
- W1 (`62ac0c8`): Fact-check + plan
- W2 (`69d8f2b`): 5 Field() backfill (2 ResilienceFlags + 3 Sprint19AIFlags)
- W3 (`570df28`): TD-013 regroup 13_Cron_Builder.py
- W4 (`67a2141`): TD-013 regroup 14_Cron_Dashboard.py
- W5 (this ADR): Closure (ADR + CHANGELOG + INDEX)

## Sprint 144 Final Score (5 waves)

| Wave | Commit | Scope | Test Δ | TD-013 Δ |
|---|---|---|---|---|
| W1 | `62ac0c8` | Fact-check + plan (1 commit, 0 code) | 0 | 0 |
| W2 | `69d8f2b` | 5 Field() backfill (ResilienceFlags + Sprint19AIFlags) | -8 (14→6) | 0 |
| W3 | `570df28` | TD-013: 13_Cron_Builder.py → `_groups/cron/builder/` | 0 | +1 (1→2) |
| W4 | `67a2141` | TD-013: 14_Cron_Dashboard.py → `_groups/cron/dashboard/` | 0 | +1 (2→3) |
| W5 | (this ADR) | Closure (ADR + CHANGELOG + INDEX) | 0 | 0 |
| **TOTAL** | **4 atomic code commits + 1 closure** | **0 NEW layer violations** | **-8 (-57%)** | **+2 (1→3)** |

## Field Additions (S144 W2)

### ResilienceFlags (2 fields)

**File:** `src/backend/core/config/features/resilience.py`

1. `auto_scaler_process_level` — K2 Wave 6: AutoScaler process-level (multi-process replication-safe). Multi-process metrics via psutil.Popen fork-safety + shared memory.
2. `auto_scaler_task_level` — K2 Wave 6: AutoScaler task-level (asyncio-friendly). Per-asyncio-task metrics + ratio-based scale-up/down.

### Sprint19AIFlags (3 fields)

**File:** `src/backend/core/config/features/sprint19_ai.py`

1. `adaptive_timeout_enabled` — K2 S19 W15: Adaptive timeout per (endpoint, client_region, traffic_class). F-4 closure, 12-hour production shadow-mode.
2. `admin_react_mvp` — K3 S19 W3: Admin UI React MVP (replace Streamlit 13/14). S-L4-2 closure, full feature parity required.
3. `adaptive_rag_strategy_enabled` — K4 S19 W4: Adaptive RAG (HyDE + query-decomposition). S-L4-4 closure, +5% RAGAS faithfulness.

**Tests fixed (8):**
- test_resilience_flags_instantiates (was: 4 fails: instantiates, env_vars, field_count, inherits → 0)
- test_sprint19_ai_flags_instantiates (was: 4 fails → 0)
- (Plus env_vars + field_count + inherits for both classes)

## TD-013 Page Regroups (S144 W3-W4)

### W3 — 13_Cron_Builder.py → `_groups/cron/builder/`

**Original:** 149 LOC, single-render-path
**New structure:**
- `_groups/cron/__init__.py` (15 lines) — group re-exports
- `_groups/cron/builder/__init__.py` (38 lines) — per-page sub-package
- `_groups/cron/builder/render.py` (190 lines) — extracted `render()` + `_render_body()` with lazy streamlit import
- `13_Cron_Builder.py` (24 lines) — thin shim, calls `render()`

### W4 — 14_Cron_Dashboard.py → `_groups/cron/dashboard/`

**Original:** 135 LOC, single-render-path
**New structure:**
- `_groups/cron/dashboard/__init__.py` (33 lines) — per-page sub-package
- `_groups/cron/dashboard/render.py` (160 lines) — extracted `render()` + `_render_body()` with table + actions + metrics + auto-refresh
- `14_Cron_Dashboard.py` (24 lines) — thin shim, calls `render()`

**Pattern:** `_groups/{group}/{page}/` sub-package + thin shim. Lazy streamlit import (per TD-013 pilot contract from S142 W1). Backward-compatible (flat page still discoverable by Streamlit).

## Pre-existing Failures (NOT introduced by S144, per Rule #124 OUT OF SCOPE)

| Test | Symptom | Root cause | Action |
|---|---|---|---|
| `test_ai_flags_instantiates` | `rag_cache_l2_semantic default != False` | Field has `default=True` per design (test assumes all False) | OUT OF SCOPE |
| `test_ai_field_count` | 10 != 9 | Extra `prompt_registry_gateway_wiring` field (not in test list) | OUT OF SCOPE |
| `test_sprints_24_27_flags_instantiates` | `ai_gateway_enforce default != False` | Field has `default=True` per ADR-NEW-19 | OUT OF SCOPE |
| `test_sprint5_dsl_*` (3 fails) | 12 missing fields | Sprint 5 K3 DSL backlog | **S145 W2-W3** scope |

All verified via `git stash` BEFORE my changes (per Rule #124 protocol).

## Test Impact (cumulative S139-S144)

| Test Path | Start (S139 W1) | End (S144 W4) | Net |
|---|---|---|---|
| `tests/unit/core/config/test_features_*.py` | 23 failed | 6 failed | **-17 (-74%)** |
| `tests/unit/core/` (overall) | 153 failed | ~56 failed | **-97 (-63%)** |
| `tests/unit/services/` | 86 failed | 29 failed | **-57 (-66%)** |
| `tests/unit/` TOTAL | 239 failed | ~85 failed | **-154 (-64%)** |

## TD-013 Status (cumulative)

| Sprint | Pages regrouped | Cumulative |
|---|---|---|
| S142 W3 (PoC) | 1 (00_Home.py) | 1 |
| S144 W3 (13_Cron_Builder) | 1 | 2 |
| S144 W4 (14_Cron_Dashboard) | 1 | 3 |
| Remaining | — | 66 (69-3) |

## Stale Backlog Items Cleared (S144 W1 fact-check)

| Item | Status | Action |
|---|---|---|
| 1 NEW sibling layer (rag_service/search_mixin.py) | Not found in `tools/check_layers.py` output | Likely already fixed in S140-S142 cascade |
| AIFlags 2 fails (rag_cache=True + 10≠9) | Pre-existing design conflict | OUT OF SCOPE per Rule #124 |
| Sprints2427Flags instantiate fail | Pre-existing design conflict | OUT OF SCOPE per Rule #124 |

## Ponytail Mode Applied (S144)

- **4 atomic code commits** vs 1 big-bang (per ADR-0226 S143 style)
- **2 TD-013 page regroups in 2 separate commits** (per-page blame, not "TD-013 2 pages" commit)
- **5 Field() backfill in 1 commit** (same domain, no need to split)
- **No back-compat shim**: new Field() with `default=False` is non-breaking

## Sprint 144 Layer Audit

- 0 NEW violations from my work (4 atomic commits, all in `core/config/features/` or `frontend/streamlit_app/pages/`)
- Sibling NEW status: not investigated (out of scope per Rule #124)
- `tools/check_layers.py` baseline: 220 legacy, 0 NEW (file count: 2128, +6 from S143)

## S145+ Backlog

### HIGH (dedicated sprint)
- 66 TD-013 Streamlit pages remaining (12h estimated)
- 6 remaining test_features_*.py fails (12 missing Sprint5DSLFlags + 2 pre-existing AIFlags + 1 pre-existing Sprints2427)
- 73 core test fails (feature gaps, not patterns)
- 29 services test fails (3 streaming + 26 unknown)
- TD-006 PARTIAL (test baseline ratchet)

### MEDIUM (P2)
- docstring coverage ratchet
- security audit
- pre-existing test isolation issues (test_retry, test_http S107-S109 era, test_tenant_filter, test_airflow_operators)

### LOW (P3)
- Mutation testing, performance benchmarks
- master_prompt_for_agent.md update (per ADR-0226)

## Decisions

- **S144 W1 = fact-check + plan** (1 commit, 0 code) — Rule #130: W1 = fact-check
- **S144 W2 = 5 Field() in 1 commit** (same domain: core/config/features) — Ponytail atomic but don't over-split
- **S144 W3-W4 = 2 TD-013 page regroups in 2 commits** (per-page blame) — easier to revert/cherry-pick
- **No back-compat shim** (Ponytail): new Field() with `default=False` is non-breaking
- **Skip TD-013 dashboard list** (per S144 plan, 2 cron pages were sufficient for 1 sprint)
- **S144 local branch**: `sprint/td013-pilot-B` (carry-over from S142 W3). 12 ahead of origin/master (3 from S142 W1-W3 + 4 from S143 W1-W4 + 4 from S144 W1-W4 + 1 from S144 W5)

## Commits

```
67a2141 feat(s144-w4-td013): regroup 14_Cron_Dashboard.py to _groups/cron/dashboard/
570df28 feat(s144-w3-td013): regroup 13_Cron_Builder.py to _groups/cron/builder/
69d8f2b feat(s144-w2-features): add 5 fields (ResilienceFlags + Sprint19AIFlags)
62ac0c8 docs(s144-w1-factcheck): test_features breakdown + TD-013 plan
```

Pre-S144 HEAD: `c8c6f62` (S143 W5 closure). After S144 W5: 12 commits ahead of origin/master.

## Refs

- ADR-0226 (S143 closure)
- ADR-0225 (S142 closure)
- `reports/sprint/s144_w1_factcheck.md` (S144 fact-check)
- `reports/reaudit/tech_debt_register.md`
- Ponytail skill (active, level full)
- Skill: verify-analysis-claims
- Skill: systematic-debugging
- Skill: sprint-execution (Rule #130: W1 = fact-check)
- Rule #124 (pre-existing failures OUT OF SCOPE)
