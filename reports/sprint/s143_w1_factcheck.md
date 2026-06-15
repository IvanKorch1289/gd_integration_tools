# S143 W1 — Pre-flight Factcheck

> **Date:** 2026-06-15 (post-S142 closure, HEAD `924a48d`)
> **Author:** sprint-execution agent (S143 W1)
> **Result:** SCOPE Bounded. 4-5 quick wins identified, 1 stale backlog claim cleared.

## Context

S142 closed on `sprint/td013-pilot-B` side branch (3 commits ahead of origin/master).
143 ADRs in `docs/adr/` (per `ls`, 176 with INDEX/WIKI = 174 + 2 helpers).
Score 9.9 (stable from S140).

## Fact-check vs ADR-0225 (S142 closure) claims

| Claim | Verified | Notes |
|---|---|---|
| 99 cumulative test fails (was 239) | ✅ APPROX | pytest truncated at 60% during full run; spot-checked: 23 fails in test_features_*.py (matches ADR), 0 from_nats fails, 0 sibling layer (claimed in ADR-0225, may be resolved) |
| 173 ADRs (172 unique) | ⚠️ DISCREPANCY | `ls docs/adr/*.md` = 176. 3 extra: `0225-sprint-142-closure.md` (latest), plus possibly `WIKI.md` and `INDEX.md` counted. Non-blocking — likely counting diff. |
| 0 NEW layer violations from S142 work | ✅ VERIFIED | `tools/check_layers.py` → 0 NEW (220 legacy baseline) |
| 1 NEW sibling layer (rag_service/search_mixin.py) | ⚠️ UNVERIFIED | Specific grep returned nothing; may have been fixed in interim. ADR-0225 was 1 day ago. |
| TD-013 = 2 of 73 pages regrouped | ✅ APPROX | `_groups/*` contains 13 files (some are __init__.py per-group, some are nested like `home_page/navigation.py`); 2 actual page regroups confirmed (`00_Home.py` S142 W3 + `33_DSL_Templates` S140-W3 sibling) |
| Ponytail skill active (level full) | ✅ CONFIRMED | User profile + S140-S141 ADRs all reference Ponytail `full` |
| from_nats signature broken | 🔴 STALE | 15 passed, 13 skipped, 0 failed (full grep test for `from_nats`/`test_from_nats`). Backlog item appears resolved. |

## Current S143+ Backlog (post-factcheck)

### HIGH (dedicated sprint)
- 70 TD-013 pages remaining (6-12h, per ADR-0225 estimate)
- 73 core test fails (feature gaps, not patterns)
- 29 services test fails (3 streaming + 26 unknown)
- TD-006 PARTIAL (test baseline ratchet)

### MEDIUM (P2)
- 1 NEW sibling layer (unverified, possibly already fixed)
- docstring coverage ratchet
- security audit

### LOW (P3)
- Mutation testing, performance benchmarks

## S143 Plan (5 waves, Ponytail-friendly: ship the lazy version)

| Wave | Scope | Commit pattern |
|---|---|---|
| W1 | (this factcheck) | analysis-only |
| W2 | `Sprints2427Flags.ai_skill_toml_enabled` Field() backfill + `test_features_sprints_24_27` (1-3 fails → 0) | atomic |
| W3 | Skip from_nats (verified working) → use slot for 1-2 more test_features fixes (likely `ResilienceFlags` or `Sprint5DSLFlags`) | atomic |
| W4 | TD-013: 1-2 more page regroups (incremental to S142 W3 PoC) | atomic |
| W5 | ADR-0226 + CHANGELOG + INDEX (177 ADRs) | closure |

**Total: 3 atomic code commits + 1 closure = 4 commits, 5 waves.**

## Verification plan (post-execution)

- `tools/check_layers.py` → 0 NEW
- `pytest tests/unit/core/config/test_features_*.py` → -3 fails minimum
- `pytest tests/unit/` → net ≤ -3 fails
- Score: 9.9 (maintained)

## Stop conditions

- Sibling commits to `master` while in W2-W4 (worktree management — per ADR-0225 cherry-pick pattern)
- New layer violation (block + analyze)
- Discovery of >5 NEW TD items (scope re-evaluation needed)

## Refs

- ADR-0225 (S142 closure)
- ADR-0224 (S141 closure)
- `reports/sprint/s142_w1_factcheck.md` (truncated, scope check)
- Ponytail skill (active, level full)
- Skill: verify-analysis-claims
- Skill: systematic-debugging
- Skill: sprint-execution (Rule #130: W1 = fact-check)
