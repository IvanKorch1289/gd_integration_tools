# ADR-0231: Sprint 148 Closure — Pre-existing Triage Burst (2 atomic commits + 1 closure, score 9.9 → 9.9, 0 NEW layer violations, 4 fails closed: 2 outbox + 2 validator)

- **Status:** Accepted (Sprint 148 closure, 2026-06-15)
- **Wave:** s148-w5-closure
- **Sprint:** 148
- **Depends:** ADR-0230 (S147 closure)

## Context

Sprint 148 picked up **pre-existing** test infrastructure issues from
`tests/unit/core/config/` (Rule #124 eligible):
- 2 test_outbox.py fails (test/code drift — `use_redis_dedupe` field added
  in S64 W4 but tests never updated to expect 7 fields)
- 2 test_validator.py fails (`monkeypatch.setattr` on wrong module —
  `from _helpers import` creates local binding in `infrastructure_checks`)

Both are test infrastructure bugs (not production code bugs), pre-existing
per git history (touched only in S113 closure for unrelated reasons).

Sprint 148 plan (2 atomic commits + 1 closure, no W1 factcheck):
- W1 (`c23f7af`): add `use_redis_dedupe` to expected fields in test_outbox.py
- W2 (`0dc38a7`): patch `infrastructure_checks` namespace (importer's
  binding) in test_validator.py
- W5 (this ADR): closure

## Sprint 148 Final Score (2 waves)

| Wave | Commit | Scope | Fail Δ |
|---|---|---|---|
| W1 | `c23f7af` | Add `use_redis_dedupe` to 2 expected sets in test_outbox.py | -2 (2→0 in test_outbox.py) |
| W2 | `0dc38a7` | Patch infrastructure_checks namespace in 2 tests | -2 (2→0 in test_validator.py) |
| W5 | (this ADR) | Closure | 0 |
| **TOTAL** | **2 atomic code commits + 1 closure** | **0 NEW layer violations** | **-4 fails** |

## Root Cause Analysis

### W1: test_outbox.py field drift

**File:** `tests/unit/core/config/services/test_outbox.py`

**Root cause:** `OutboxSettings` (in `core/config/services/outbox.py`)
added `use_redis_dedupe: bool = Field(default=False, ...)` in S64 W4
(cross-instance dedup store feature). Two tests still assumed 6 fields:
- `test_model_dump_is_json_safe`: expected set missed `use_redis_dedupe`
- `test_field_count`: asserted `len(model_fields) == 6`, code has 7

**Fix:** Add `use_redis_dedupe` to both expected sets. Ponytail mode:
test-only change, no code modification.

### W2: test_validator.py monkeypatch namespace

**File:** `tests/unit/core/config/test_validator.py`

**Root cause:** `infrastructure_checks.py` does
`from src.backend.core.config.validator._helpers import _FEATURE_FLAG_DEPENDENCIES`
which creates a local binding in `infrastructure_checks` namespace,
NOT an attribute on the `validator` package. Test attempted
`monkeypatch.setattr(validator_module, "_FEATURE_FLAG_DEPENDENCIES", ...)`
which fails with `AttributeError: <module '...validator'> has no attribute '_FEATURE_FLAG_DEPENDENCIES'`.

**Fix:** Patch the importer's binding directly:
`monkeypatch.setattr(infrastructure_checks, "_FEATURE_FLAG_DEPENDENCIES", ...)`.
Standard Python monkeypatch pattern (same as S146 W2 mcp_settings fix).
After the test's import `from validator import infrastructure_checks`,
the name is re-bound to the submodule object, so `setattr` on it mutates
the binding visible to `_check_feature_flag_dependency_unmet`.

## Verification (post-S148)

```
uv run pytest tests/unit/core/config/ --tb=no -q
→ 340 passed, 3 failed (was 336 passed, 7 failed)
→ 4 fails closed (2 outbox + 2 validator)
```

3 remaining fails (per Rule #124 OUT OF SCOPE):
- `test_features_ai.py::test_ai_flags_instantiates` — design conflict
  (rag_cache_l2_semantic has default=True per design, test assumes all False)
- `test_features_ai.py::test_ai_field_count` — test/code drift
  (extra `prompt_registry_gateway_wiring` field not in test list)
- `test_features_sprints_24_27.py::test_sprints_24_27_flags_instantiates`
  — design conflict (ai_gateway_enforce default=True per ADR-NEW-19)

## Pre-existing Failures Still Open (per Rule #124 OUT OF SCOPE)

- 3 test_features fails (AIFlags×2, Sprints2427Flags×1) — design conflicts
- 29 services test fails (3 streaming + 26 unknown) — bulk sweep needed
  (dedicated sprint, not S148 scope)
- 4 stale allowlist entries (rag_service/ → logging.factory) — pre-existing
- 73 core test fails (feature gaps, not patterns) — pre-existing

## Test Impact (cumulative S139-S148)

| Test Path | Start (S139 W1) | End (S148 W2) | Net |
|---|---|---|---|
| `tests/unit/` collection errors | 14 | 0 | **-14 (-100%)** |
| `tests/unit/core/config/` fails | ~10 | 3 | **-7 (-70%)** |
| `tests/unit/core/` (overall) | 153 failed | ~49 failed | **-104 (-68%)** |
| `tests/unit/services/` | 86 failed | 29 failed | **-57 (-66%)** |
| `tests/unit/` TOTAL | 239 failed | ~60 failed | **-179 (-75%)** |

## Ponytail Mode Applied (S148)

- **2 atomic commits** (test-only changes, 0 production code modifications)
- **Smallest possible fixes** (1 field added to 2 expected sets for W1;
  2 import + 2 setattr changes for W2)
- **No refactoring** (Ponytail "ship the lazy version")
- **No back-compat shim** (Ponytail: deletion over addition)
- **Each commit verified pre-existing** via `git log -- <test_file>`
  (last touched S113 closure for unrelated reasons)

## Sprint 148 Layer Audit

- 0 NEW violations from my work (test-only changes)
- 4 pre-existing stale allowlist entries: pre-existing per `git stash`,
  OUT OF SCOPE per Rule #124
- `tools/check_layers.py` baseline: 220 legacy, 0 NEW

## S149+ Backlog

### HIGH (dedicated sprint)
- 66 TD-013 Streamlit pages remaining (12h)
- 29 services test fails (3 streaming + 26 unknown)
- 73 core test fails (feature gaps, not patterns)
- TD-006 PARTIAL (test baseline ratchet)

### MEDIUM (P2)
- 3 pre-existing test_features fails (AIFlags×2, Sprints2427Flags×1) — design conflicts OUT OF SCOPE
- docstring coverage ratchet
- security audit
- 4 stale allowlist entries (rag_service/ → logging.factory)

### LOW (P3)
- Mutation testing, performance benchmarks
- master_prompt_for_agent.md update (per ADR-0226)
- Shim removal (circuit_breaker.py + pybreaker_adapter.py)

## Decisions

- **S148 = direct fix (no factcheck)** — pre-existing test drift already
  known from S143-S145 (same pattern: test assumes N fields, code has N+1)
- **2 atomic commits** — minimal blast radius (1 file each, 2-9 LOC)
- **No back-compat shim** (Ponytail)
- **Test-only changes** (no production code modification = 0 risk)
- **S148 local branch**: `sprint/td013-pilot-B` (carry-over from S142 W3).
  25 ahead of origin/master (3 S142 + 5 S143 + 5 S144 + 4 S145 + 4 S146 + 2 S147 + 2 S148 + 1 S148 W5 closure)

## Commits

```
0dc38a7 fix(s148-w2-validator-tests): patch infrastructure_checks namespace (2 fails → 0)
c23f7af fix(s148-w1-outbox-tests): add use_redis_dedupe to expected fields (2 fails → 0)
```

Pre-S148 HEAD: `f9da51d` (S147 W5 closure). After S148 W5: 25 commits
ahead of origin/master.

## Refs

- ADR-0230 (S147 closure + VER-122 lesson)
- ADR-0229 (S146 closure + post-mortem)
- Ponytail skill (active, level full)
- Skill: verify-analysis-claims (VER-122)
- Rule #124 (pre-existing failures: classify, verify, fix single root cause)
- Skill: sprint-execution
