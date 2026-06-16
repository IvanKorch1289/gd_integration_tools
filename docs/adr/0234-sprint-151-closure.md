# ADR-0234: Sprint 151 Closure — Cron Dashboard Parser + Patch Source (1 atomic commit, score 9.9 → 9.9, 0 NEW layer violations, 3 fails closed)

- **Status:** Accepted (Sprint 151 closure, 2026-06-16)
- **Wave:** s151-w5-closure
- **Sprint:** 151
- **Depends:** ADR-0233 (S150 closure)

## Context

Sprint 151 picked up **2 related pre-existing** issues in
`services/scheduler/cron_dashboard_service.py` (Rule #124 eligible):
- Production: `cron_expr` parser used `rstrip(']')` which left
  `timezone=...` suffix in cron_expr
- Test: monkeypatch targeted wrong namespace (S148 W2 precedent)

Sprint 151 plan (1 atomic commit + 1 closure, no W2/W3/W4):
- W1 (`dec4b7e`): **CRITICAL** parser fix + patch source location
- W5 (this ADR): closure

## Sprint 151 Final Score (2 waves)

| Wave | Commit | Scope | Fail Δ |
|---|---|---|---|
| W1 | `dec4b7e` | cron_dashboard: parser split + patch source (2 related) | -3 (3→0 in test_cron_dashboard_service) |
| W5 | (this ADR) | Closure | 0 |
| **TOTAL** | **1 atomic code commit + 1 closure** | **0 NEW layer violations** | **-3 fails** |

## Root Cause Analysis

### W1: CRITICAL — `cron_expr` parser + test patch source

**Files:**
- `src/backend/services/scheduler/cron_dashboard_service.py` (production)
- `tests/unit/services/scheduler/test_cron_dashboard_service.py` (test)

**Root cause (2 related bugs in 1 commit per Rule #124):**

1. **Production:** `cron_expr = trigger_str.split("cron[", 1)[1].rstrip("]")`
   fails for `trigger = "cron[0 9 * * 1-5] timezone=Europe/Moscow"`:
   - After split: `"0 9 * * 1-5] timezone=Europe/Moscow"`
   - After rstrip("]"): no `]` at end, so rstrip does nothing
   - Result: `cron_expr = "0 9 * * 1-5] timezone=Europe/Moscow"` (BROKEN)
   - The `]` is in the middle, not at the end.
   - **Fix:** `cron_expr = trigger_str.split("cron[", 1)[1].split("]", 1)[0]`

2. **Test:** `with patch("...scheduler_manager.get_scheduler_manager", ...)`
   patched `infrastructure.scheduler.scheduler_manager`, but service does
   `from src.backend.core.scheduler import get_scheduler_manager` INSIDE
   the `list_scheduled()` function body. Patch on the re-exported
   function doesn't propagate to the function-local binding.
   - **Fix:** patch source location `core.scheduler.get_scheduler_manager`
     (S146 W3 / S148 W2 precedent — local import → patch source).

## Verification (post-S151)

```
uv run pytest tests/unit/services/scheduler/test_cron_dashboard_service.py -v
→ 10 passed, 0 failed (was 7 passed, 3 failed at S151 start)
→ 3 fails closed (1 parser + 2 patch source)
```

## Sprint 151 Final Test Count

```
uv run pytest tests/unit/services/ --no-header -q
→ 1510 passed, 16 failed, 1 skipped (was 1507 passed, 19 failed at S151 start)
→ 3 fails closed net
```

16 remaining fails (per Rule #124 OUT OF SCOPE):
- `services/ai/prompts/test_langfuse_storage.py` (5)
- `services/ai/test_rag_embedding_version.py` (4)
- `services/ai/test_rag_source_attribution.py` (4)
- `services/integrations/test_dadata.py::test_get_geolocate_wraps_exception_as_service_error` (1, test isolation)
- `services/ops/test_dq_remediation.py::test_remediate_returns_dq_remediation_result` (1, 5x duplicate class — defer)
- `services/schema_registry/test_event_schemas.py::test_skip_on_exception` (1, passes standalone — collection state)

## Pre-existing Failures Defer to S152+

- **5x `DQRemediationResult` class duplication** (S55 W4 decomp) — same
  class defined in 4 mixin files + `__init__.py`. Test imports from
  `__init__.py`, production uses `apply_mixin.DQRemediationResult`.
  Fix requires 5-file refactor (consolidate types) — > 1 commit scope.
  Per Rule #124: classify OUT OF SCOPE, defer to dedicated sprint.

## Test Impact (cumulative S139-S151)

| Test Path | Start (S139 W1) | End (S151 W5) | Net |
|---|---|---|---|
| `tests/unit/` collection errors | 14 | 0 | **-14 (-100%)** |
| `tests/unit/` fails | 239 | ~55 | **-184 (-77%)** |
| `tests/unit/core/config/` | ~10 | 3 | **-7 (-70%)** |
| `tests/unit/core/` | 153 | ~49 | **-104 (-68%)** |
| `tests/unit/services/` | 86 | 22 | **-64 (-74%)** |

## Ponytail Mode Applied (S151)

- **1 atomic commit** (2 related root causes per Rule #124)
- **Production fix 1 line** (split instead of rstrip)
- **Test fix ~6 lines** (constant + 4 patch replacements)
- **No back-compat shim** (Ponytail: deletion over addition)
- **Skipped DQ remediation 5-file refactor** (per Rule #124, > 1 commit
  scope = defer to dedicated sprint)

## S151 Layer Audit

- 0 NEW violations from my work
- 4 pre-existing stale allowlist entries: pre-existing per `git stash`,
  OUT OF SCOPE per Rule #124
- `tools/check_layers.py` baseline: 220 legacy, 0 NEW

## S152+ Backlog

### HIGH (dedicated sprint)
- **5x DQRemediationResult class dedup** (S55 W4 decomp, 5-file refactor)
- 16 services test fails (5 langfuse + 4 rag_emb + 4 rag_src + 1 dq_remediation + 1 dadata isolation + 1 collection)
- 66 TD-013 Streamlit pages remaining (12h)
- ~50 core test fails (feature gaps)

### MEDIUM (P2)
- 3 pre-existing test_features fails (AIFlags×2, Sprints2427Flags×1) — design conflicts OUT OF SCOPE
- docstring coverage ratchet
- security audit
- 4 stale allowlist entries (rag_service/ → logging.factory)

### LOW (P3)
- Mutation testing, performance benchmarks
- master_prompt_for_agent.md update (per ADR-0226)
- Shim removal (circuit_breaker.py + pybreaker_adapter.py)
- `task_registry._on_done` improvement: log `exc_info` so failures
  surface traceback without debug instrumentation

## Decisions

- **S151 = direct fix (no factcheck)** — pre-existing bugs found via
  targeted test sweep
- **W1 grouped 2 related fixes** (Rule #124: same area, both test infra)
- **Skipped W2-W4** (DQ remediation 5x duplication > 1 commit scope, defer)
- **S151 local branch**: `sprint/td013-pilot-B` (carry-over from S142 W3).
  33 ahead of origin/master (3 S142 + 5 S143 + 5 S144 + 4 S145 + 4 S146 + 2 S147 + 3 S148 + 3 S149 + 4 S150 + 1 S151 + 1 S151 W5 closure)

## Commits

```
dec4b7e fix(s151-w1-cron-dashboard): parser split + patch source (3 fails → 0)
```

Pre-S151 HEAD: `ee7045b` (S150 W5 closure). After S151 W5: 33 commits
ahead of origin/master.

## Refs

- ADR-0233 (S150 closure)
- ADR-0232 (S149 closure)
- ADR-0231 (S148 closure + test_validator monkeypatch precedent)
- ADR-0230 (S147 closure + VER-122 lesson)
- ADR-0229 (S146 closure + post-mortem)
- Ponytail skill (active, level full)
- Skill: verify-analysis-claims (VER-122)
- Skill: systematic-debugging (4-phase: understand bugs before fixing)
- Rule #124 (pre-existing failures: classify, verify, fix single root cause)
- Skill: sprint-execution
