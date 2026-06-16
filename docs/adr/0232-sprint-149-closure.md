# ADR-0232: Sprint 149 Closure — Pre-existing Triage Burst (2 atomic commits + 1 closure, score 9.9 → 9.9, 0 NEW layer violations, 4 fails closed: 2 dedupe_store + 2 streaming)

- **Status:** Accepted (Sprint 149 closure, 2026-06-15)
- **Wave:** s149-w5-closure
- **Sprint:** 149
- **Depends:** ADR-0231 (S148 closure)

## Context

Sprint 149 picked up **pre-existing** bugs from `services/sources/` and
`services/execution/invoker/` (Rule #124 eligible):
- 2 dedupe_store_factory fails (test patch wrong path + RedisClient
  `__slots__ = ()` regression from S43-45 refactor)
- 2 streaming invoker fails (`_is_async_iterator` import lost during
  S68 W3 decomp)

Both are real bugs (one test infra, one production regression for
streaming invocations), pre-existing per git history.

Sprint 149 plan (2 atomic commits + 1 closure, no W1 factcheck):
- W1 (`d89a546`): RedisClient `__slots__` declaration + test_dedupe_store
  patch path fix (1 commit, 2 related root causes per Rule #124)
- W2 (`e8165f4`): add missing `_is_async_iterator` import in run_mixin.py
- W5 (this ADR): closure

## Sprint 149 Final Score (2 waves)

| Wave | Commit | Scope | Fail Δ |
|---|---|---|---|
| W1 | `d89a546` | RedisClient slots + dedupe_store patch path | -2 (2→0 in test_dedupe_store_factory) |
| W2 | `e8165f4` | Add missing `_is_async_iterator` import in run_mixin | -2 (2→0 in test_invoker streaming) |
| W5 | (this ADR) | Closure | 0 |
| **TOTAL** | **2 atomic code commits + 1 closure** | **0 NEW layer violations** | **-4 fails** |

## Root Cause Analysis

### W1: RedisClient `__slots__ = ()` regression + test patch path

**File:** `src/backend/infrastructure/clients/storage/redis/__init__.py`
+ `tests/unit/services/sources/test_dedupe_store_factory.py`

**Root cause (2 related bugs in 1 commit per Rule #124):**

1. `RedisClient.__slots__ = ()` declared in S43-45 refactor (commit
   `58f4d73`) — empty tuple means NO slot names AND NO `__dict__`.
   Result: `__init__` raised `AttributeError: 'RedisClient' object has
   no attribute 'settings' and no __dict__ for setting new attributes`
   on the very first attribute assignment. Bug masked by tests that
   either stubbed `__init__` or never exercised `RedisClient()`.

2. `test_dedupe_store_factory.py` patched
   `src.backend.infrastructure.clients.storage.redis.get_redis_client`
   but `lifecycle.py` imports `get_redis_client` from
   `src.backend.core.storage.redis` (compat shim). Patching the
   canonical infra path didn't take effect because the shim re-exports
   create a separate namespace.

**Fix:**
- W1a: declare actual slot names matching `__init__` instance attrs:
  `__slots__ = ("settings", "logger", "_clients", "_locks", "_breakers")`
- W1b: patch the source path the production code actually uses
  (`src.backend.core.storage.redis.get_redis_client`)

### W2: Missing `_is_async_iterator` import in run_mixin

**File:** `src/backend/services/execution/invoker/run_mixin.py`

**Root cause:** S68 W3 decomp (commit refactored invoker/ into 4 mixins)
lost the import of `_is_async_iterator` from `helpers.py` in `run_mixin.py`.
The function `_run_and_stream` uses `_is_async_iterator()` at line 157
to detect async generators. Without the import, every streaming
invocation raised `NameError: name '_is_async_iterator' is not defined`
inside the background task, which silently failed (test infrastructure
only logs a warning via task_registry, not a traceback).

**Discovery process (helpful for future sprints):**
1. Initial symptom: `ws.sent = []` after `_drain_pending()`,
   `task_registry.task_failed` warning in logs.
2. `task_registry._on_done` only logs `error=repr(exc)` without
   `exc_info` — the actual traceback is hidden.
3. Temporarily added `print()` + `traceback.print_exception()` in
   `_on_done` to surface the actual exception.
4. Found `NameError: name '_is_async_iterator' is not defined` —
   root cause: missing import.

**Fix:** Add 1-line import:
`from src.backend.services.execution.invoker.helpers import _is_async_iterator`

## Verification (post-S149)

```
uv run pytest tests/unit/services/ tests/unit/test_main.py tests/unit/cache/backends/test_redis.py --tb=line -q
→ 1525 passed, 24 failed, 1 skipped (was 1523 passed, 26 failed)
→ 4 fails closed (2 dedupe_store + 2 streaming)
→ 24 remaining fails = separate pre-existing issues (OUT OF SCOPE per Rule #124)
```

24 remaining fails by file:
- `services/ai/prompts/test_langfuse_storage.py` (5)
- `services/ai/test_rag_embedding_version.py` (4)
- `services/ai/test_rag_source_attribution.py` (4)
- `services/integrations/test_dadata.py` (? collection)
- `services/jupyter/execution_service/test_papermill_factory_heartbeat.py` (?)
- `services/ops/test_data_quality.py` (?)
- `services/ops/test_dq_remediation.py` (?)
- `services/scheduler/test_cron_dashboard_service.py` (3)
- `services/schema_registry/test_event_schemas.py` (1)
- (TBD exact breakdown for remaining files)

## Pre-existing Failures Still Open (per Rule #124 OUT OF SCOPE)

- 24 services test fails (separate issues, dedicated sprint for bulk sweep)
- 3 test_features fails (AIFlags×2, Sprints2427Flags×1) — design conflicts
- 73 core test fails (feature gaps, not patterns) — pre-existing
- 4 stale allowlist entries (rag_service/ → logging.factory) — pre-existing
- 66 TD-013 Streamlit pages remaining (12h)
- 1 test_dadata.py collection error (need separate triage)

## Test Impact (cumulative S139-S149)

| Test Path | Start (S139 W1) | End (S149 W2) | Net |
|---|---|---|---|
| `tests/unit/` collection errors | 14 | 0 | **-14 (-100%)** |
| `tests/unit/` fails | 239 | ~60 | **-179 (-75%)** |
| `tests/unit/core/config/` | ~10 | 3 | **-7 (-70%)** |
| `tests/unit/core/` | 153 | ~49 | **-104 (-68%)** |
| `tests/unit/services/` | 86 | 27 | **-59 (-69%)** |
| `tests/unit/services/execution/invoker.py` | 4 fails | 21 pass | **streaming + others fixed** |

## Ponytail Mode Applied (S149)

- **2 atomic commits** (minimal blast radius)
- **W1 grouped 2 related root causes** (per Rule #124: same area, both
  pre-existing S43-45 era issues — 1 commit = 1 logical fix)
- **W2 1-line import** (Ponytail: shortest working diff)
- **No refactoring** (Ponytail "ship the lazy version")
- **No back-compat shim** (Ponytail: deletion over addition)
- **Each commit verified pre-existing** via git history + live test
- **Debug instrumentation reverted** after root cause found (no debug
  code committed to production)

## Sprint 149 Layer Audit

- 0 NEW violations from my work
- 4 pre-existing stale allowlist entries: pre-existing per `git stash`,
  OUT OF SCOPE per Rule #124
- `tools/check_layers.py` baseline: 220 legacy, 0 NEW

## S150+ Backlog

### HIGH (dedicated sprint)
- 66 TD-013 Streamlit pages remaining (12h)
- 24 services test fails (separate issues, NOT 1-pattern sweep)
- 73 core test fails (feature gaps, not patterns)
- TD-006 PARTIAL (test baseline ratchet)
- 1 test_dadata.py collection error

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

- **S149 = direct fix (no factcheck)** — pre-existing bugs found via
  targeted test sweep, root-caused individually
- **W1 grouped 2 related fixes** (Rule #124: same area, both S43-45 era)
- **W2 isolated 1-line import** (cleaner atomic commit)
- **Debug instrumentation reverted** (Ponytail: no debug code in prod)
- **S149 local branch**: `sprint/td013-pilot-B` (carry-over from S142 W3).
  28 ahead of origin/master (3 S142 + 5 S143 + 5 S144 + 4 S145 + 4 S146 + 2 S147 + 3 S148 + 2 S149 + 1 S149 W5 closure)

## Commits

```
e8165f4 fix(s149-w2-invoker-mixin): add missing _is_async_iterator import (2 streaming fails → 0)
d89a546 fix(s149-w1-redis-slots): fix __slots__ + patch source path (3 fixes in 1 commit)
```

Pre-S149 HEAD: `6c8f4c8` (S148 W5 closure). After S149 W5: 28 commits
ahead of origin/master.

## Refs

- ADR-0231 (S148 closure)
- ADR-0230 (S147 closure + VER-122 lesson)
- ADR-0229 (S146 closure + post-mortem)
- Ponytail skill (active, level full)
- Skill: verify-analysis-claims (VER-122)
- Skill: systematic-debugging (4-phase: understand bugs before fixing)
- Rule #124 (pre-existing failures: classify, verify, fix single root cause)
- Skill: sprint-execution
