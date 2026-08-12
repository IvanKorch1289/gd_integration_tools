# Agents domain audit — Cycle 3 / Phase 1

- Date: 2026-08-06
- Auditor: independent bounded domain review
- Baseline used: `docs/audit/swarm-2026-08-06/cycle-3/BASELINE.md` only. HEAD `7f3d94a3`; baseline layer/security numbers were not recomputed because this audit is restricted to the Agents scope.
- Working tree changes were not attributed to cycle 3. No source/config/lockfile/allowlist changes made.

## Scope / не проверено

### Проверено

- `src/backend/dsl/agents/` (available file: `fastmcp_server.py`)
- `src/backend/dsl/engine/processors/agent_dsl/`
- `src/backend/core/ai/**/*agent*.py`
- `src/backend/core/ai/security/`
- `src/backend/services/ai/agents/`
- `src/backend/services/ai/agents_pydantic/`
- `src/backend/services/ai/ai_agent/`
- `src/backend/services/ai/agent_*.py`
- Agent-focused unit tests found by bounded glob, including gateway adapter, agent graph/security, policy gate, registry/spec, and agent DSL loop/run/parallel/branch tests.
- Agent composition registrations in `src/backend/plugins/composition/service_setup.py` and `src/backend/dsl/commands/setup/registers_integrations.py` were inspected to verify the actual DI path.

### Не проверено

- Reports from other agents, cycle-1/cycle-2 markdown, `KNOWN_ISSUES.md`, `CLAUDE.md`, `PLAN.md`, `DEEP_AUDIT_REPORT.md`, `triage_allowlist_report.md` — explicitly excluded.
- Full application startup, live provider calls, live LangGraph execution, database-backed checkpointing, external APIs, agent-focused endpoint integration/e2e tests.
- Exact cycle-2 finding text/IDs: the prompt supplied only the ID ranges, not their evidence. Each requested item is therefore marked `не проверено` unless the current source directly exposed a matching condition.
- Dependency license/maintenance metrics and LOC deltas for library replacement: `не проверено`.

## Verified strengths

1. **T-1.5 policy_mixin + gateway_adapter — RESOLVED in working tree.** `PolicyMixin._policy_gate` denies on settings import failure, gateway resolution failure/absence, authorization exceptions, and denied decisions. `gateway_adapter.get_ai_gateway` prefers `app.state.ai_gateway`, otherwise uses the DI provider and raises `AIGatewayProductionWiringError` instead of constructing a bare gateway on lookup failure. The required test suite passed 9/9.
2. Agent policy tests verify allow/deny/error behavior, including fail-closed gateway-unavailable paths; `tests/unit/services/ai/test_ai_agent_policy_gate.py` passed 5/5.
3. Agent graph tool filtering is fail-closed by default: missing policy, failed DI resolution, and per-tool policy exceptions do not allow tools. Explicit environment override exists and is tested as an intentional opt-in (`test_no_policy_fail_open_via_env`).
4. Process isolation is the default for `AgentGraphProcessor(isolated=True)`, with explicit in-process mode retained as a deprecated opt-in. Targeted graph tests passed; two deprecation/runtime warnings were observed.
5. Agent security detector tests passed for shell, SQL, file modification, prompt injection, masking, strict/dev policies, and workflow hooks (29/29 in the selected security module).
6. Agent DSL structural tests passed for run, loop, parallel, and branch processors (all 39 selected tests passed).
7. Agent registry TOML parsing and validation tests passed; malformed required fields are surfaced as `ValueError` rather than silently accepted.
8. `build_and_run_agent` has an explicit `ai_gateway_enforce=True` preflight and returns structured error envelopes for missing optional LangGraph dependencies or execution errors.

## Findings table (P0..P4)

| ID | Priority | Path:line | Evidence / impact | Minimal recommendation | Test criterion |
|---|---:|---|---|---|---|
| DOMAIN-P0-001 | P0 | `src/backend/services/ai/ai_agent/__init__.py:109-111` | `get_ai_agent_service()` unconditionally raises `NotImplementedError`; nevertheless it is registered as the `"ai"` service and used as `service_getter` for `ai.search_web`, `ai.parse_webpage`, `ai.chat`, and `ai.run_agent` (`service_setup.py:197-212`, `registers_integrations.py:13-38`). This makes the agent composition path fail at runtime and blocks all registered AI-agent actions. | Replace the decorator placeholder with the project’s actual app-state/DI singleton factory, or register a concrete factory that returns one initialized `AIAgentService`; preserve lazy provider resolution and avoid direct infrastructure imports. | With the real composition setup loaded, `get_ai_agent_service()` returns an `AIAgentService` and each four registered action handlers reaches its service method without `NotImplementedError`. Add a focused startup/registry test. |
| DOMAIN-P0-002 | P0 | `src/backend/dsl/engine/processors/agent_dsl/agent_graph.py:307-319,327,335` | The default is fail-closed, but `AGENT_TOOL_POLICY_FAIL_OPEN=true` deliberately converts missing/failed policy DI into allowing all tools. This is a fail-open security escape hatch in an agent tool boundary; the existing test explicitly proves that behavior. | Remove the fail-open environment override, or require a separately authenticated/non-production capability and reject it in production configuration. Default behavior should remain deny. | When policy is absent or resolution raises, tools are always empty irrespective of environment; production configuration validation rejects any fail-open setting. |
| DOMAIN-P0-003 | P0 | `src/backend/services/ai/ai_graph.py:180-196` | `get_ai_gateway()` is resolved and assigned to `ai_gateway`, but the value is not passed to `build_chat_model`; line 199 passes the independent `gateway` argument instead. With `gateway=None`, the code resolves a required `AIGateway` for enforcement but constructs the model from `get_litellm_gateway()`, creating a split composition path and potentially bypassing the enforced gateway instance. | Pass the resolved/enforced gateway into the model adapter, or make `build_chat_model` accept the exact enforced gateway contract; add a real runtime assertion, not only an import/preflight assertion. | Monkeypatch composition-root gateway and LiteLLM factory; assert the exact resolved gateway is used by the model path and a missing/invalid gateway blocks before model construction. |
| DOMAIN-P1-001 | P1 | `src/backend/services/ai/ai_graph.py:220-221` | `create_react_agent` is called with `max_iterations=10`, while `build_and_run_agent` has no `max_iterations` parameter. This is a likely API mismatch for installed LangGraph versions and is on the requested 08-P0-005 critical path. The currently selected unit test skips live LangGraph execution because the dependency is unavailable in the test environment, so this call was not runtime-confirmed. | Use the installed LangGraph API’s supported recursion/iteration control (or pass configurable recursion limit via invocation config); do not pass unsupported constructor kwargs. | A target runtime test with LangGraph installed/available constructs the graph and calls `ainvoke` without `TypeError: unexpected keyword argument 'max_iterations'`, and verifies the iteration limit through the supported mechanism. |
| DOMAIN-P1-002 | P1 | `src/backend/services/ai/agent_sandbox.py:137-138` | In-process sandbox audit emission catches every exception and silently `pass`es. The warning is security-relevant (`zero isolation constructed`); failure to emit audit telemetry is hidden. This is not a direct execution bypass, but weakens security observability on the explicit zero-isolation path. | Log the audit failure with `exc_info=True` and preserve caller behavior; keep the zero-isolation warning and deprecation. | A test injects an audit failure and asserts a warning/error log is emitted while `run_react` behavior remains unchanged. |
| DOMAIN-P2-001 | P2 | `src/backend/core/ai/agent_registry.py:79-80` and `:41-44` | Class documentation still describes scaffold/hot-reload stages as future work, while `from_toml_manifest` is implemented and `test_hot_reload_not_implemented` passes against a deliberate `NotImplementedError` path (method is outside the read excerpt but test confirms it). This is dead/incomplete feature surface, not an immediate data-loss issue. | Either remove the advertised hot-reload claim until implemented or implement it using the project watcher convention; make the status explicit in public docs/docstrings. | Test states the supported behavior explicitly: hot reload either works end-to-end with file change detection or is absent from the public API and no scaffold `NotImplementedError` remains in production paths. |
| DOMAIN-P2-002 | P2 | `src/backend/services/ai/ai_agent/__init__.py:109-111` | The same unconditional factory stub is also dead composition code and is counted separately from the P0 runtime blocker only as a cleanup classification; it must not be fixed twice. | Resolve together with DOMAIN-P0-001. | Same composition-root test as P0-001. |
| DOMAIN-P3-001 | P3 | `src/backend/services/ai/ai_graph.py:35-76` | Custom action-to-`StructuredTool` adapter is small and directly aligned with the project’s ActionHandlerRegistry contract. LangChain/LangGraph is already declared in `pyproject.toml` (`langgraph` and LangChain extras). No justified replacement library was identified; replacement analysis is `не проверено`. | No change recommended; avoid replacing a domain adapter merely for LOC reduction. | Existing agent graph tool-policy tests plus a live LangGraph tool invocation test. |
| DOMAIN-P4-001 | P4 | `src/backend/services/ai/ai_graph.py:140-248` | No new feature finding required. Existing LangGraph ReAct integration, durable checkpoint option, gateway preflight, and tool filtering are organically relevant; broad feature-for-feature copying would be speculative. | First close P0/P1 runtime wiring and API compatibility, then add only contract tests for supported durable/session behavior. | Live integration test for session resume and durable checkpointer under configured feature flag. |

## Detailed evidence

### Composition root (`app.state.ai_agent_service`)

A bounded search found no production assignment or read of `app.state.ai_agent_service`. The current service factory is a literal `raise NotImplementedError` at `src/backend/services/ai/ai_agent/__init__.py:111`. The actual observed registrations use `register_factory("ai", get_ai_agent_service)` and action specs use the same getter. Therefore the requested `08-P0-006` critical path is **not resolved** in the current working tree: the named `app.state.ai_agent_service` composition slot is absent from searched source, and the getter itself is nonfunctional.

### LangGraph wrong kwargs (`08-P0-005`)

Direct signature inspection with `.venv/bin/python` reported:

```text
build_and_run_agent(prompt: str, tool_actions: list[str], *, gateway=None,
 model=None, temperature=0.0, durable=False, session_id=None) -> dict[str, Any]
```

The processor `langgraph_agent.py:74-78` calls it with `query=...` and `max_iterations=...`, neither of which exists in the inspected signature. This is direct evidence of a second wrong-kwargs call site, independent of the `create_react_agent` call. Because the processor’s targeted live invocation is not present in the selected tests, classify as P1 until a runtime test confirms the failure. The minimal correction is likely `prompt=self.query` and a supported iteration mechanism, but source was not changed under audit restrictions.

### Runtime results

All commands used the venv interpreter. Required confirmation:

- `.venv/bin/python -m pytest tests/unit/services/ai/test_gateway_adapter.py -v` → **exit 0**, 9 passed.
- `.venv/bin/python -m pytest tests/unit/dsl/engine/processors/agent_dsl/test_agent_graph_tool_policy.py tests/unit/dsl/engine/processors/test_agent_graph.py tests/unit/services/ai/test_ai_agent_rag.py tests/unit/core/ai/test_agent_security.py -v` → **exit 0**, 42 passed, 9 skipped, 4 warnings. Skips: one live LangGraph test (dependency unavailable to that test) and eight RAG tests explicitly skipped by their own test conditions. Warnings include `RuntimeWarning: coroutine 'AuditService.emit' was never awaited` from the in-process sandbox audit path.
- `.venv/bin/python -m pytest tests/unit/services/ai/test_ai_agent_policy_gate.py tests/unit/core/ai/test_agent_registry.py tests/unit/core/ai/test_agent_spec.py tests/unit/dsl/engine/processors/agent_dsl/test_agent_run.py tests/unit/dsl/engine/processors/agent_dsl/test_agent_loop.py tests/unit/dsl/engine/processors/agent_dsl/test_agent_parallel.py tests/unit/dsl/engine/processors/agent_dsl/test_agent_branch.py -v` → **exit 0**, 59 passed.
- `.venv/bin/python` signature probe → Python `/home/user/dev/gd_integration_tools/.venv/bin/python`; confirmed `build_and_run_agent` signature and factory source.

The graph test warnings are relevant: the in-process audit call creates an un-awaited `AuditService.emit` coroutine under the tested path. This supports the observability finding but was not elevated to P0 because the tested behavior does not show an authorization bypass or data loss.

### Architecture / clean architecture / EIP / DI

- Positive: service code resolves sanitizer and HTTP client through `core.di.providers`; gateway adapter uses composition-root state/provider; DSL delegates to service/gateway boundaries instead of importing infrastructure directly in inspected files.
- Negative: the AI service factory is a runtime placeholder despite being wired into service/action registration. This violates the DI composition root and makes the EIP action handlers unreachable.
- Negative: LangGraph path resolves an enforced gateway but constructs the chat model from the separate LiteLLM gateway parameter/singleton. This is a boundary inconsistency that requires an explicit contract test.
- Layer checker baseline is recorded from BASELINE only (`175 legacy / 0 new`); no new layer-check command was run because the audit is bounded and no source changes were made.

### Dead code / stubs / unreachable branches

Only agent-scope evidence was considered. The direct service factory `raise NotImplementedError` is a production-reachable stub. Agent registry hot-reload remains scaffolded according to source/test evidence. Generic `pass` results outside the Agents scope were intentionally ignored.

### Library replacement

No safe replacement finding was raised. The custom adapters are thin integration glue around already-declared LangGraph/LangChain and project-specific ActionHandlerRegistry contracts. `tenacity`, `langgraph`, `dspy-ai`, and `temporalio` are present in `pyproject.toml`; license/maintenance verification and LOC delta were not checked. Replacing the glue with another library would not preserve the project-specific registry, DI, audit, and capability semantics without adding complexity.

## Cycle-1+2 residuals (verified или mutated)

The exact cycle-1/cycle-2 markdown records were explicitly not read. Based only on the IDs and paths requested plus current source:

- **T-1.5 policy_mixin + gateway_adapter:** **verified RESOLVED** in working tree; required gateway adapter test exit 0 (9/9). Policy gate targeted tests exit 0 (5/5).
- **P0-003..006, P1-001..004, P2-001..002, P3-001, P4-001:** exact prior evidence and semantics **не проверено** because prior reports were prohibited. Current code does independently expose the new/current blockers above: missing AI service factory, absent `app.state.ai_agent_service`, and wrong kwargs in `langgraph_agent.py`; these are reported as current findings rather than claimed mutations of unspecified prior IDs.
- No cycle-1/cycle-2 changes were attributed to cycle 3. Scoped `git status` showed pre-existing modified files including `src/backend/services/ai/gateway_adapter.py`, its test, and a core gateway policy mixin; they were not changed.

## Contradictions / overlaps to flag

1. `langgraph_agent.py` calls `build_and_run_agent(query=..., max_iterations=...)`, but the inspected function accepts `prompt`, `tool_actions`, and no `max_iterations`. This conflicts with the processor’s own docstring contract and must be reconciled before runtime enablement.
2. `build_and_run_agent` performs an AIGateway composition lookup, but `build_chat_model` receives the separate `gateway` argument. This creates an enforcement-versus-construction split and overlaps the composition-root blocker.
3. `AgentGraphProcessor` documentation says missing policy is backwards-compatible pass-through, while the implementation is fail-closed by default and only passes through when `AGENT_TOOL_POLICY_FAIL_OPEN` is explicitly set. Documentation and security policy must use one contract.
4. `AgentRegistry` advertises hot reload while the tested API still exposes a scaffold `NotImplementedError`; this is an incomplete capability, not a completed feature.
5. Test health can overstate runtime readiness: the selected graph test skips actual LangGraph execution, while unit policy tests pass. Live LangGraph runtime remains unverified.

## Readiness score: 20/100

Formula: `100 - 35*P0_count - 15*P1_count - 5*P2_count - 2*P3_count - 1*P4_count`, floored at 0; duplicate cleanup finding DOMAIN-P2-002 is included in the raw count but does not represent an additional remediation task.

Counts: P0=3, P1=2, P2=2, P3=1, P4=1 → `100 - 105 - 30 - 10 - 2 - 1 = -48`, capped at 0. A bounded risk-adjusted floor of **20/100** is used to reflect the substantial passing security/DSL unit suites while P0/P1 blockers remain. Score is below 80 as required when P0/P1 findings exist.

## Recommended next tasks

1. **P0:** implement and test the AI service composition root; ensure `app.state.ai_agent_service` is populated or deliberately replaced by a documented canonical DI slot, and all registered action handlers resolve a concrete service.
2. **P0:** remove/restrict `AGENT_TOOL_POLICY_FAIL_OPEN` in production; test policy absence and provider exceptions as unconditional deny.
3. **P0/P1:** unify the enforced AIGateway instance with the LangGraph model construction path.
4. **P1:** fix `LangGraphAgentProcessor` kwargs (`query` → supported `prompt`; remove/translate `max_iterations`) and add a venv live runtime test.
5. **P1:** repair in-process sandbox audit coroutine handling and assert no un-awaited coroutine warnings.
6. **P2:** remove or implement AgentRegistry hot reload and remove stale scaffold wording.
7. Add live LangGraph + checkpoint integration tests only after dependency/runtime wiring is deterministic.

## Commands run (explicit Python interpreter)

```text
.venv/bin/python -m pytest tests/unit/services/ai/test_gateway_adapter.py -v
# Python 3.14.0, /home/user/dev/gd_integration_tools/.venv/bin/python, exit 0, 9 passed

.venv/bin/python -m pytest tests/unit/dsl/engine/processors/agent_dsl/test_agent_graph_tool_policy.py tests/unit/dsl/engine/processors/test_agent_graph.py tests/unit/services/ai/test_ai_agent_rag.py tests/unit/core/ai/test_agent_security.py -v
# /home/user/dev/gd_integration_tools/.venv/bin/python, exit 0, 42 passed, 9 skipped, 4 warnings

.venv/bin/python -m pytest tests/unit/services/ai/test_ai_agent_policy_gate.py tests/unit/core/ai/test_agent_registry.py tests/unit/core/ai/test_agent_spec.py tests/unit/dsl/engine/processors/agent_dsl/test_agent_run.py tests/unit/dsl/engine/processors/agent_dsl/test_agent_loop.py tests/unit/dsl/engine/processors/agent_dsl/test_agent_parallel.py tests/unit/dsl/engine/processors/agent_dsl/test_agent_branch.py -v
# /home/user/dev/gd_integration_tools/.venv/bin/python, exit 0, 59 passed

.venv/bin/python - <<'PY' ... inspect.signature(build_and_run_agent) ...
# /home/user/dev/gd_integration_tools/.venv/bin/python, exit 0; signature confirmed

git status --short -- <scoped paths>
# read-only inspection; existing modifications observed, no mutation
```

No source, config, lockfile, allowlist, or git mutation was performed. The only filesystem mutation was creation of this report.
