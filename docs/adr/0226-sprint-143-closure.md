# ADR-0226: Sprint 143 Closure — Feature Flags Field() Backfill (4 atomic commits + 1 closure, score 9.9 → 9.9, 0 NEW layer violations, test_features 23→14 fails -39%)

- **Status:** Accepted (Sprint 143 closure, 2026-06-15)
- **Wave:** s143-w5-closure
- **Sprint:** 143
- **Depends:** ADR-0225 (S142 closure), s143_w1_factcheck_classification

## Context

Sprint 143 picked up the S142 W1 factcheck finding: 26 features_* tests failing due to missing `Field()` declarations in feature flag classes. Per S143 W1 factcheck (`reports/sprint/s143_w1_factcheck.md`):

- ADR-0225 (S142 closure) claim: "26 fails in test_features_* are missing Field() decls, scope too big for 1 sprint"
- W1 fact-check refined: 23 fails actually missing Field() across 6 flag classes
- Ponytail-mode decision: 3 small waves (1-4 fields each) + 1 closure, not multi-day bulk fix

Also: from_nats signature concern (claimed broken in backlog) was verified PASSING in W1 fact-check (15 tests pass, 0 fail). Backlog item stale — removed from S143 plan.

## Sprint 143 Final Score (5 waves)

| Wave | Commit | Scope | Test Δ |
|---|---|---|---|
| W1 | `39bb462` | Fact-check + plan (1 commit, 0 code) | 0 |
| W2 | `62527b1` | `Sprints2427Flags.ai_skill_toml_enabled` Field() (S26 W5) | -2 (23→21) |
| W3 | `1f35d9e` | `Sprint19DXFlags.banking_ai_processors_impl` Field() | -3 (21→18) |
| W4 | `f8e7a55` | `Sprints1517Flags`: 4 fields (`arch_map_llm_search_enabled`, `ai_pr_review_enabled`, `audit_correlation_required`, `apscheduler_metrics`) | -4 (18→14) |
| W5 | (this ADR) | Closure (ADR + CHANGELOG + INDEX) | 0 |
| **TOTAL** | **4 atomic code commits + 1 closure** | **0 NEW layer violations** | **-9 (23→14) -39%** |

## Field Additions (S143 W2-W4)

### W2 — `Sprints2427Flags.ai_skill_toml_enabled`

**File:** `src/backend/core/config/features/sprints_24_27.py`
**Title:** K4 S26 W5: Skills Registry TOML frontmatter (ADR-NEW-22)
**Default:** `False`
**Tests fixed:** `test_sprints_24_27_field_count` (12→13 fields), `test_feature_flags_inherits_sprints_24_27_fields`

### W3 — `Sprint19DXFlags.banking_ai_processors_impl`

**File:** `src/backend/core/config/features/sprint19_dx.py`
**Title:** K4 S19 W3: Banking AI processors - implementation layer (impl vs interface)
**Default:** `False`
**Sibling to:** `banking_ai_processors_enabled` (interface flag)
**Tests fixed:** 3 in `test_features_sprint19_dx.py`

### W4 — `Sprints1517Flags`: 4 fields

**File:** `src/backend/core/config/features/sprints_15_17.py`

1. `arch_map_llm_search_enabled` — K5 S15 W4: Architecture map LLM-search (semantic code navigation)
2. `ai_pr_review_enabled` — K4 S15 W6: AI PR-review (CI gate, code-suggestion diff comments)
3. `audit_correlation_required` — K3 S17 W3: audit_correlation_id required for all write-events (D12)
4. `apscheduler_metrics` — K2 S17 W4: APScheduler Prometheus metrics (D13b)

All default `False`. Tests fixed: 4 in `test_features_sprints_15_17.py`.

## Pre-existing Failures (NOT introduced by S143, per Rule #124 OUT OF SCOPE)

| Test | Symptom | Root cause |
|---|---|---|
| `test_sprints_24_27_flags_instantiates` | `ai_gateway_enforce default != False` | Field has `default=True` per ADR-NEW-19 design (test assumes all False, contradicts design) |
| `test_sprint5_dsl_flags_inherits_sprint5_dsl_fields` | (one of) inheritance assertion | Per S133 W1 classification, this is a per-fail issue requiring deeper investigation |

Verified via `git stash` BEFORE my changes — both fail in pre-S143 state.

## Test Impact (cumulative S139-S143)

| Test Path | Start (S139 W1) | End (S143 W4) | Net |
|---|---|---|---|
| `tests/unit/core/config/test_features_*.py` | 23 failed | 14 failed | **-9 (-39%)** |
| `tests/unit/core/` (overall) | 153 failed | ~64 failed | **-89 (-58%)** |
| `tests/unit/services/` | 86 failed | 29 failed | **-57 (-66%)** |
| `tests/unit/` TOTAL | 239 failed | ~93 failed | **-146 (-61%)** |

## Stale Backlog Items Cleared (S143 W1 fact-check)

| Backlog item | Verified | Action |
|---|---|---|
| from_nats signature | 15 pass, 0 fail (full grep `test_from_nats`) | Removed from S143 plan |
| 1 NEW sibling layer (rag_service/search_mixin.py) | Not found in `tools/check_layers.py` output | Likely already fixed in S140-S142 cascade |
| ADR count discrepancy (176 vs 173) | ls confirms 176; ADR-0225 was off by 3 (1 from S142 W4 + 2 from INDEX helpers) | Non-blocking |

## Sprint 143 Layer Audit

- 0 NEW violations from my work (4 atomic commits, all in `core/config/features/`)
- Sibling NEW status: not investigated (out of scope per Rule #124)
- `tools/check_layers.py` baseline: 220 legacy, 0 NEW

## Ponytail Mode Applied (S143)

Per user preference (Ponytail skill active, level `full`):
- W2-W4 = minimal "ship the lazy version" (3 separate small commits vs 1 big bang)
- No backward-compat shims, no per-call-site migration, no deprecation warnings
- Each new Field() = `default=False` + title + description (Sprint+Wave+Owner+ADR ref pattern)
- Comment style matches existing 100+ Field() definitions in same files

## S144+ Backlog (after S143 closure)

### HIGH (dedicated sprint)
- 70 TD-013 Streamlit pages remaining (6-12h, per ADR-0225 estimate)
- 14 remaining test_features_*.py fails (Sprint5DSLFlags 12 missing + 1 instantiate + 1 inheritance)
- 73 core test fails (feature gaps, not patterns)
- 29 services test fails (3 streaming + 26 unknown)
- TD-006 PARTIAL (test baseline ratchet)

### MEDIUM (P2)
- docstring coverage ratchet
- security audit
- pre-existing test_sprints_24_27_flags_instantiates design conflict (test vs ADR-NEW-19)

### LOW (P3)
- Mutation testing, performance benchmarks

## Decisions

- **S143 W2-W4 = 3 small commits vs 1 big-bang fix** (Ponytail mode). Easier to review, fewer layer violations risk, faster to identify which Field() fixes which test
- **No back-compat shim** (Ponytail): new Field() with `default=False` is non-breaking; old code reading `FeatureFlags.<new_field>` gets `False` (same as old behavior)
- **Skip from_nats** (verified working): backlog stale, removed from S143 plan
- **S143 local branch**: `sprint/td013-pilot-B` (carry-over from S142 W3). 3 ahead of origin/master (S142 W1+W2+W3). S143 W1-W5 added 4 more commits (7 total ahead of origin after closure).
- **No destructive operations** (deny-list): branch cleanup requires explicit user consent

## Commits

```
f8e7a55 feat(s143-w4-features): add 4 Sprints1517Flags fields (S15-S17 K-bridge)
1f35d9e feat(s143-w3-features): add Sprint19DXFlags.banking_ai_processors_impl
62527b1 feat(s143-w2-features): add Sprints2427Flags.ai_skill_toml_enabled (S26 W5)
39bb462 docs(s143-w1-factcheck): verify S142 claims + scope bounded plan
```

Pre-S143 HEAD: `924a48d` (S142 W4 closure). After S143 W5: 7 commits ahead of origin/master.

## Refs

- ADR-0225 (S142 closure)
- ADR-0224 (S141 closure)
- `reports/sprint/s142_w1_factcheck.md` (truncated, 26 features fail)
- `reports/sprint/s143_w1_factcheck.md` (S143 factcheck)
- `reports/reaudit/tech_debt_register.md` (TD-006 PARTIAL, TD-013 PARTIAL)
- Ponytail skill (active, level full)
- Skill: verify-analysis-claims
- Skill: systematic-debugging
- Skill: sprint-execution (Rule #130: W1 = fact-check)
- Rule #124 (pre-existing failures OUT OF SCOPE)
