# Swarm Cycle 3 — Final Report (2026-07-23)

## Fixes applied (commit cdc7c41e)

**17 files changed, +90 / -187 LOC. 0 compile errors. All fixes instrumentally verified via `py_compile.compile(..., doraise=True)`.**

| # | File(s) | Bug class | Fix |
|---|---------|-----------|-----|
| 1 | `infrastructure/database/database/initializer.py:222` | Module-breaking: `@resilient` used without import → `NameError` on module import, database core bootstrap broken | Added `from src.backend.core.resilience.connector_resilience import resilient` |
| 2 | `entrypoints/api/v1/endpoints/dsl_console.py:148,195,212` | 3× data leak: `str(exc)` returned to public client on `POST /dsl/execute-inline`, `/dsl/execute-registered`, `/dsl/dry-run` (no auth on these endpoints) | Replaced with `{type(exc).__name__}: internal error (see server logs)` + `logger.exception(...)` server-side trace |
| 3 | `dsl/engine/processors/agent_dsl/agent_graph.py:302-313` | Silent fail-open: 3× tool-policy paths (ImportError, `has_service` False, `get_service` Exception) returned full tool list without logging | Added `logger.warning(...)` for each path; behavior preserved (still fail-open for backwards-compat) |
| 4 | 8 workflow files: `infrastructure/workflow/pg_runner_internals/{instance,event_store,state,rows}.py` + `dsl/workflow/spec/{workflow,advanced_declarations,activity_declarations,policies}.py` | Dead code: real docstring (L1-5) + `from __future__` (L7/8) + imports + second orphan `"""..."""` block (bare expression, no semantic effect, shadowed `__doc__`) | Removed orphan block (18-20 lines per file) |
| 5 | 6 security files: `core/security/capabilities/{vocabulary/{models,defaults},gate/{audit,cache,check,declaration}_mixin}.py` | Dead code: `from __future__` on L1, imports L2-5, docstring as bare expression L7+ (placed after non-docstring imports, so `__doc__=None`) | Moved docstring to L1 (before `from __future__`) so `__doc__` is actually set |

## Cross-references
- **D417** (misplaced-docstring): now closed in 14 files (8 workflow + 6 security)
- **D418** (declare-without-invoke): partially closed — only tool_policy path in `agent_graph.py` is now LOGGED. The 20+ other `agent_dsl/` processors declaring `required_capability` without invoking `self.auth_check()` are still open (not fixed in this cycle, but the pattern is now documented).
- **D415** (py_compile verification): applied as the primary verification tool.

## Still open from Cycle 2 backlog
- D418 in `agent_dsl/` 20+ processors (`required_capability` declared but `self.auth_check()` never invoked)
- DSL Console auth + rate limit (deferred — user-confirmed public by design; only sanitization fixed)
- Saga compensators dead contract (8 workflow templates)
- 5 AI pipeline bypasses (`ai_tool_dispatch`, `banking_processors/base`, `memory_store`, `guardrails_processor`, `workflow_activities`)
- MCP namespace authz gap (only `ai` has it, `analytics`/`credit`/`system` don't)
- 100 layer-violation imports (DSL → services/entrypoints)
- 290 `Optional[X] = <wrong default>` type mismatches
- 30+ hardcoded timeouts / 15+ magic numbers
- 4+ retry policy types inconsistency + `max_attempts` vs `maximum_attempts` field mismatch
- 2 test rot (stale imports)
