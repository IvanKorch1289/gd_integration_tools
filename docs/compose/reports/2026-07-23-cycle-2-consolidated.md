# Cycle 2 — Consolidated Analyst Report (2026-07-23)

**8 Analysts dispatched in parallel (1 timed out). 7 reports received + synthesized.**

## Coverage Map
- ✅ #1 Security (143 files) — `2026-07-23-cycle-2-analyst-1-security.md`
- ✅ #2 DSL processors (401 files) — `2026-07-23-cycle-2-analyst-2-dsl.md`
- ✅ #3 Workflow/orchestration — `2026-07-23-cycle-2-analyst-3-workflow.md`
- ✅ #4 Infrastructure — `2026-07-23-cycle-2-analyst-4-infra.md`
- ✅ #5 AI/Agents — `2026-07-23-cycle-2-analyst-5-ai.md`
- ⏱️ #6 Services — **timed out** (no report)
- ✅ #7 Entrypoints/middlewares — `2026-07-23-cycle-2-analyst-7-entrypoints.md`
- ✅ #8 Config/Tests/Docs/Frontend — `2026-07-23-cycle-2-analyst-8-config.md`

## Cross-Cutting P0 Findings (tool-verified)

### 1. `from __future__` ordering pattern (project-wide)
- **Cycle 1 fixed 4 files in infrastructure/** (elasticsearch, mongodb, redis_coordinator, event_bus)
- **Cycle 2 found 8 workflow files with copy-paste pattern** (real docstring L1, `from __future__` L7/8, second `"""..."""` L9+ before imports — orphan string-Expr, `__doc__=None`):
  - `infrastructure/workflow/pg_runner_internals/{instance_store,event_store,state,rows}.py:9`
  - `dsl/workflow/spec/{workflow,advanced_declarations,activity_declarations,policies}.py:10`
- **Cycle 2 found 6 security files with same pattern** (P0 security):
  - `core/security/capabilities/{vocabulary/{models,defaults},gate/{audit,cache,check,declaration}_mixin}.py:7,16`

**Pattern**: The misplaced-module-docstring is **a copy-paste anti-pattern** that reproduces in 18+ files across 3+ domains (workflow, security, dsl/spec). Cheap detector: `ast.parse` + check `Expr(Constant(str))` position in `tree.body`.

### 2. Module-breaking import in database bootstrap
- `src/backend/infrastructure/database/database/initializer.py:222` — `@resilient` decorator referenced but **NOT imported**. Confirmed: `NameError: name 'resilient' is not defined`. Database bootstrap **BROKEN on import**. **Affects 4+ test collection** (transitive).

### 3. Massive auth-capability gap in `agent_dsl/` (20+ files)
- `agent_branch.py`, `agent_loop.py`, `agent_parallel.py`, `agent_security_check.py`, `guardrails_apply.py`, `optimize_prompt.py` — no `required_capability` attribute
- `agent_pii_mask.py`, `agent_graph.py`, `agent_run.py`, `ai_tool_dispatch.py`, `bind_skill.py`, `langgraph_agent.py`, `mcp_tool.py`, `memory_recall.py`, `memory_store.py`, `pii_mask.py`, `pii_unmask.py`, `plan_execute.py`, `reflection_loop.py`, `skill_invoke.py` — declare `required_capability` but **never invoke `self.auth_check()`**
- **Cross-confirmation with Analyst 5**: `agent_graph.py:302-313` tool-policy fail-open bypasses this gap

### 4. DSL Console endpoints are PUBLIC (no auth, no rate limit)
- `entrypoints/api/v1/endpoints/dsl_console.py:131-262` — 3 endpoints (`/dsl/execute-inline`, `/dsl/execute-registered`, `/dsl/dry-run`)
- Returns `str(exc)` on error → **public endpoint leaks raw exception strings** (stack traces, paths)
- Arbitrary DSL execution + arbitrary YAML accepted → potential RCE/DoS surface

### 5. Saga compensation is DEAD CONTRACT
- `WorkflowSpec.compensators` declared, never invoked (cross-cited by Analyst 3 + Analyst 4)
- 8 workflow templates with external side-effects (PagerDuty, email, MLflow, S3) have **NO compensation**
- `kyc_aml_check` workflow: 3 forward / 1 compensate → **silent no-op on 2/3 forward**

### 6. AI pipeline has 6 critical bypass surfaces
- `agent_graph.py:338-348` — prompt injection → tools (no sanitizer)
- `ai_tool_dispatch.py:269-290` — LLM-controlled tool dispatcher with `query` from exchange directly in prompt
- `banking_processors/base.py:49-70,96,118-125` — values from body/properties directly in LLM prompt, **bypassing AIGateway pipeline**
- `memory_store.py:99-118` — arbitrary value saved to persistent memory without PII masking
- `guardrails_processor.py:80-99,115-134` — `block_on_failure=False` default → Lakera/NeMo errors **silently pass**
- `workflow_activities.py:108-134` — `max_tokens=None` without upper bound

### 7. MCP tool whitelist exists in only 1 of 4+ namespaces
- `ai_mcp.py:78-100` — implements per-tool authz
- `analytics_mcp.py`, `credit_mcp.py`, `system_mcp.py` — **no whitelist filter**; expose all registered actions

### 8. WorkflowBuilder dual NOT found
- Analyst 3 verified 0 duals — s213 unification is complete

## Cross-Cutting P1 Findings

### 1. docstring-outside-docstring pattern
18 files across 3 domains (security: 6, workflow: 8, dsl/spec: 4)

### 2. Duplicate banking AI processors (P1)
- `ai_banking/` (1284 LOC) vs `ai/banking_processors/` (615 LOC) with **6 identical class names** (CustomerSegmentation, RiskAssessment, LoanEligibility + their Result dataclasses). Both imported in `__init__.py`. Import ambiguity risk.

### 3. Dead code (4 services + 4 DSL)
- `sla_alerting.py:195` SlaTracker, `:83,91` SlaAlertDispatcher — zero production instantiation
- `reactive_dispatcher.py:33,50` ReactiveTrigger/Dispatcher — zero production callers
- `hitl_pubsub_consumer.py:56` HitlPubSubConsumer — self-only instantiation
- `eip/reliability/_legacy.py:39-44` — 4 classes in `__all__` but not defined
- `dsl/builders/base/__init__.py:69` `get_route_builder` listed but undefined

### 4. Retry policy inconsistency (4+ parallel types)
- `core/ai/retry_policy.py:29-60` (Pydantic)
- `core/resilience/retry.py:67-120` (different fields)
- `core/resilience/connector_retry.py:68-69`
- `core/resilience/connector_resilience.py:42-43`
- 8 sinks have different retry defaults (file_sink=2, s3_sink=5, etc.)
- `ml_training_pipeline.workflow.yaml:6-11` uses `maximum_attempts` but Pydantic model uses `max_attempts` → **silently ignored**

### 5. Field-name mismatch
- `ml_training_pipeline.workflow.yaml:6-11` `maximum_attempts` not on Pydantic model
- 30+ `[[tool.mypy.overrides]]` blocks all set `ignore_missing_imports = true` in pyproject.toml
- Items like `"st_aggrid"`, `"xxhash"`, `"hdrh"` are not on PyPI

### 6. Hardcoded timeouts everywhere
- `_default_timeout_s = 300.0` in 5 places
- 30+ files with `timeout=2.0/5.0/10.0/30.0/60.0/3600.0` literals
- `request_body_cache.py:38-58` 10MB default with warning-only enforcement

### 7. Layer violation imports (100 files)
- DSL → services/entrypoints (worst: `dsl/orchestration/triggers.py:301` direct entrypoint import)
- Infrastructure → DSL (4 violations)
- DSL → services (multiple)

### 8. Magic numbers (15+ instances)
- 10000, 100000, 1048576, 4096, 300.0 in critical processors

### 9. Error response leaks (Analyst 7)
- 5+ admin endpoints leak exception messages in `detail=`
- `auth_login.py:185` mock-jwt fallback

### 10. OpenAPI drift
- 8+ admin endpoints have `response_model=None` or wrong

## Cross-Cutting P2 Findings

### 1. Test rot (Analyst 8)
- `tests/unit/ai/rag/test_docs_indexer.py:20` — `ImportError: cannot import name 'DocsIndexer'`
- `tests/unit/core/ai/policy/test_nemo_guard_fallback.py:17` — `ImportError: cannot import name '_NEMO_TO_LLM_GUARD_FALLBACK'`

### 2. Naming inconsistency
- `rpa/operations/` 17 files: lowercase without underscores
- `components/` 8 files: same
- `ai/` 10+ files: mixed naming (`cachewrite_processor.py` vs `cache_processor.py` vs `rag_search.py`)

### 3. pyproject.toml metadata
- `[project]` lacks `classifiers`, `keywords`, `urls`, `license`
- `[tool.semantic_release] branch = "master"` out of sync with `main` convention

## Verified Clean (negative findings)
- ✅ 0 hardcoded secrets in security domain
- ✅ 0 shell injection in security domain
- ✅ 0 PII logging in security/workflow domains
- ✅ 0 unsafe deserialization in security domain
- ✅ 0 bare `except:` in security/DSL/infrastructure
- ✅ 0 Capability bypass in security domain
- ✅ 0 WorkflowBuilder duals (s213 unification complete)
- ✅ 0 SQL injection in entrypoints
- ✅ 0 infra→entrypoints/services layer violations
- ✅ 0 insecure random (all `random.X` are non-crypto with `# noqa: S311`)

## Trend Metrics (vs Cycle 1)

| Metric | Before Cycle 1 | After Cycle 1 | After Cycle 2 (estimated) |
|--------|----------------|---------------|--------------------------|
| SyntaxErrors in src/backend | 7 | 0 | 0 |
| Module docstring orphans (P0) | unknown | unknown | **18 files (3 domains)** |
| Auth-capability gaps (P0) | unknown | unknown | **20+ files in agent_dsl** |
| Dead contracts | unknown | unknown | **4 components in services + 4 in DSL** |
| Layer violations (P1) | 100+ | 100+ | 100+ (unchanged) |
| Public-without-auth endpoints (P0) | unknown | unknown | **3 in dsl_console** |

## Recommended Backlog for Cycle 3

### Must-fix P0 (Cycle 3, in priority order)
1. `initializer.py:222` — add `from src.backend.core.resilience.connector_resilience import resilient` import
2. `dsl_console.py:131-262` — add auth guard + rate limit + exception sanitization
3. `agent_dsl/*.py` 20+ files — add `self.auth_check(exchange, action=...)` calls
4. `ai/banking_processors/` ↔ `ai_banking/` — resolve duplicate (move to one, alias the other or deprecate)
5. WorkflowBuilder is unified but `compensators` is dead contract — fix the field or implement

### Should-fix P0 (Cycle 3, in priority order)
6. 18 docstring orphan fixes (single sweep using AST detection script)
7. 3 AI pipeline bypasses (agent_graph, ai_tool_dispatch, banking_processors/base)
8. MCP namespace authz in analytics/credit/system

### Cycle 4+
- 100 layer-violation imports cleanup
- 30+ hardcoded timeout centralization
- 15+ magic numbers → named constants
- 4 retry policy classes consolidation
- 290 Optional + default type mismatches

## Detected Patterns Worth Promoting
- **misplaced-module-docstring** is a copy-paste anti-pattern — easy AST-based check + tool
- **declare without invoke** for `required_capability` — same pattern as s209 fix, needs enforcement
- **DSL Console public** — same anti-pattern as s205 admin_plugins (admin guard required)
- **saga compensators** — declared but unused (dead contract, not "just unused")
- **mock-jwt fallback** — same anti-pattern as s202 fallbacks, should be removed
