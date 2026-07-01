# Audit: `src/backend/dsl/engine/processors/` (agent_dsl/ + ai_banking/)

## agent_dsl/__init__.py
- Clean barrel file. 14 re-exports. `AIToolDispatchProcessor` and `BindSkillProcessor` exist in the package but are missing from `__all__` — either add them or document the exclusion.

## agent_dsl/_base.py
- Solid template-method design. Feature-flag + capability + audit boilerplate in one place.
- `_resolve_capability_gate` and `_resolve_audit_service` swallow all exceptions with bare `except Exception as _:` — a misconfigured DI silently degrades to no-op security. Log at WARNING.
- `_check_capability` line 187-188: TypeError fallback calls `check(self.required_capability)` with 1 arg, silently bypassing scope-based checks. Should log warning.
- `_plugin_name()` returns hardcoded `"core"` — misleading for DSL route context.

## agent_dsl/agent_branch.py
- Clean verdict-based router. Duplicated dot-path traversal (`_extract_verdict`) — same logic appears in 7+ other files. Extract to shared `dot_path_get(obj, path)` utility.

## agent_dsl/agent_graph.py
- **LAYER VIOLATION (line 59)**: `from src.backend.services.ai.agent_sandbox import AgentSandbox, InProcessAgentSandbox` — DSL layer directly imports `services/`. Must use facade or lazy DI.
- Same violation in lazy imports at lines 186, 157-159 (services.ai.multi_agent.supervisor, services.ai.agent_sandbox).
- `to_spec()` doesn't serialize `sandbox` config — round-trip loses data.
- `make_invoke` closure (line 209) is over-engineered; simpler inline closure works.

## agent_dsl/agent_loop.py
- Solid loop with budget guards. Same dot-path duplication as agent_branch.
- `iteration` variable leaks from `for` loop to `else` clause — confusing. Use explicit `final_iteration`.

## agent_dsl/agent_parallel.py
- Clean fan-out via `asyncio.gather`. No violations.
- Line 123-126: `asyncio.gather(*coros, return_exceptions=self.continue_on_error)` — when `continue_on_error=False`, exceptions propagate but `results` dict is incomplete (no `setdefault` for unprocessed agents). Minor but could confuse callers.

## agent_dsl/agent_run.py
- **LAYER VIOLATION (line 39)**: `from src.backend.services.ai.gateway.exceptions import GatewayUnavailable` — direct `services/` import at module level. Move to lazy import.
- `import tenacity` inside `_invoke_with_retry` (line 185) — lazy OK but consider top-level since it's a declared dependency.
- Line 121: `_ = context` pattern repeated across many processors — dead parameter. If context is reserved for future use, use `_context` or remove the parameter.
- `_resolve_gateway` (line 231-240) catches `(ImportError, AttributeError, RuntimeError)` — overly broad. Should distinguish missing module from broken gateway.

## agent_dsl/ai_tool_dispatch.py
- Not in `__all__` of `__init__.py` — orphaned from public API.
- Line 32: `import json` at top level, then `import json` again at line 302 inside `_parse_tool_selection` — redundant.
- Lines 133-136: Walrus operator `selection_reason := "no_selection"` is a no-op — always evaluates to `"no_selection"`. Dead conditional logic.
- `AIGateway()` instantiated directly (line 250) instead of DI resolve — inconsistent with other processors.
- `tenant_id="default"` and `correlation_id=""` (lines 252-253) — should use exchange.meta values.

## agent_dsl/bind_skill.py
- Not in `__all__` of `__init__.py`.
- Line 40: Logger uses hardcoded string `"workflow.processors.bind_skill"` instead of `__name__` — inconsistent with all other processors.
- `context.get("skill_registry")` / `context.set()` — relies on mutable context dict, but no validation that context supports these methods.
- `pack` from registry is stored as raw dict — no schema validation on the skill pack contents.

## agent_dsl/guardrails_apply.py
- `_resolve_runtime` (line 183-185) returns `None` unconditionally — the entire processor is effectively a no-op stub. Should be documented as scaffold or wired to real LlamaGuardRuntime.
- Otherwise clean design with 3 on_block policies.

## agent_dsl/mcp_tool.py
- **SECURITY**: `tool_uri` is user-supplied (from YAML) and passed directly to `Client(self.tool_uri)` — potential SSRF if tool_uri can point to internal services. No URI validation or allowlist.
- `__aenter__` called without corresponding `__aexit__` (line 156) — connection leak. `close()` method exists but is never called by the pipeline framework automatically.
- `_client` stored as instance state — not thread-safe if processor is shared across exchanges (should be per-invocation or use connection pool).
- Line 41-45: Module-level `Client: Any = None` with try/except import — fine pattern but the `Any` type annotation loses all typing benefits.

## agent_dsl/memory_recall.py
- `_resolve_backend` returns `None` unconditionally — processor is a no-op stub.
- Same dot-path duplication as other files.
- `_resolve_namespace` replaces `${tenant_id}` — no escaping of tenant_id value (low risk but worth noting for injection into namespace strings).

## agent_dsl/memory_store.py
- `_resolve_backend` returns `None` unconditionally — stub.
- Same dot-path duplication.
- `_resolve_key` line 143-144: `head == "property"` path accesses `parts[1]` without checking `len(parts) > 1` first — will raise `IndexError` if path is just `"property"`.

## agent_dsl/pii_mask.py
- `_resolve_tokenizer` returns `None` — stub.
- `_write_target` (lines 157-173) mutates `exchange.in_message.body` directly — side effect that could surprise callers expecting body to be immutable after creation.
- Good fallback extraction logic in `_extract_masked_text`.

## agent_dsl/pii_unmask.py
- `_resolve_tokenizer` returns `None` — stub.
- Same dot-path duplication and body mutation pattern as pii_mask.
- Lines 53, 176: `noqa: S107` comments acknowledge the false positive on `token_map_property` — appropriate.

## agent_dsl/plan_execute.py
- **LAYER VIOLATION (line 36)**: `from src.backend.services.ai.gateway.exceptions import GatewayUnavailable` — direct services import at module level.
- Same violation in `_resolve_gateway` (line 326).
- `tenant_id="unknown"` and `correlation_id="plan-exec"` hardcoded in `_call_workflow` (line 266-267) — should use `exchange.meta`.
- `_build_context` passes full `exchange.in_message.body` to LLM prompt — potential data leak of sensitive fields. No PII filtering.
- `_parse_plan` (line 298) trusts LLM JSON output without schema validation — malformed plan could cause downstream errors.

## agent_dsl/reflection_loop.py
- **LAYER VIOLATION (line 39)**: same `services.ai.gateway.exceptions` import.
- Same `tenant_id="unknown"` hardcoding (line 252).
- `_parse_reflection` returns `{"verdict": "", "critique": ""}` on parse failure — empty verdict doesn't match `stop_verdict` default `"ok"`, so the loop continues. Correct behavior but should log at WARNING.
- Otherwise clean Generate→Reflect→Refine design.

## agent_dsl/skill_invoke.py
- `_resolve_registry` returns `None` — stub.
- Lines 86-91: Sets `_skill_tenant_id` and `_skill_correlation_id` in both context and exchange — pollutes shared state with underscore-prefixed keys. Fragile contract.
- `_extract_params` line 124: `cursor.get(part)` on dict but no None check on `cursor` before next iteration — will raise if intermediate value is None.

## ai_banking/__init__.py
- Clean barrel. 13 re-exports from 4 submodules.
- `_BankingAIProcessor` is re-exported but is a private class (underscore prefix) — intentional for backward compat but unusual.

## ai_banking/_base.py
- **LAYER VIOLATION (line 47)**: `from src.backend.infrastructure.resilience.retry import make_async_retry` — DSL layer directly imports from `infrastructure/`. Must use facade.
- **LAYER VIOLATION (line 50)**: `from src.backend.services.ai.ai_agent import get_ai_agent_service` — direct services import.
- `_call_llm` returns `None` on all failures — callers must check but some paths in credit.py/identity.py don't consistently check.
- `_parse_fallback` extracts JSON by finding first `{` and last `}` — naive approach that fails on nested braces or strings containing braces. Works for typical Pydantic JSON but fragile.
- `COST_PER_1K_TOKENS = 0.02` is a class constant — different models have different pricing. Should be configurable or model-aware.

## ai_banking/credit.py
- **LAYER VIOLATION (line 26)**: `from src.backend.core.audit.facade import emit_banking_audit` — core import is OK, but the function itself may internally violate layers (not audited here).
- `CreditScoringRagProcessor` inherits `_BankingAIProcessor` but overrides `process()` directly instead of using the base `_call_llm` template. Correct — but `_check_capability` instantiates `CapabilityGate()` directly (line 149) instead of using DI, and ignores the `context` parameter entirely.
- `CustomerChatbotProcessor` and `AppealProcessorAI` inherit `BaseProcessor` directly (not `_BankingAIProcessor`) — they are pure stubs that only set properties. No LLM call, no capability check, no audit. Should be documented as scaffolds.
- `_build_prompt` (line 133-141) embeds raw customer JSON directly into prompt — potential prompt injection if customer fields contain adversarial text.

## ai_banking/document.py
- Same module-level docstring as `credit.py` and `identity.py` — all three files share identical 16-line docstring describing all processors, even though each file only contains a subset. Misleading.
- `_check_capability` is copy-pasted identically in `DocumentClassifierProcessor`, `FrancotypingProcessor` — should be in `_base.py`.
- `TransactionCategorizerProcessor` and `FinDocOcrLlmProcessor` inherit `BaseProcessor` — pure stubs, no LLM, no capability, no audit.
- `DocumentClassifierProcessor._build_prompt` (line 119) truncates content to 8000 chars — good, but magic number should be a class constant.
- Same prompt injection risk as credit.py.

## ai_banking/identity.py
- `_T = TypeVar("_T", bound=BaseModel)` at line 36 — unused in this file (only used in `_base.py`). Dead import.
- `KycAmlVerifyProcessor` and `AntiFraudScoreProcessor` have identical `_check_capability` copy-paste — same issue as document.py.
- `AntiFraudScoreProcessor._build_prompt` embeds raw transaction/history/rules JSON — prompt injection risk.
- Same module-level docstring duplication as other ai_banking files.

---

## Totals

| Category | Count |
|---|---|
| Files audited | 23 |
| Layer violations | 9 (agent_graph:3, agent_run:1, plan_execute:2, reflection_loop:1, _base(ai_banking):2) |
| Security issues | 4 (mcp_tool SSRF, prompt injection in 3 banking processors) |
| Stub/no-op processors | 6 (guardrails_apply, memory_recall, memory_store, pii_mask, pii_unmask, skill_invoke — all `_resolve_*` return None) |
| Duplicated dot-path logic | 8 files share identical traversal pattern |
| Copy-pasted `_check_capability` | 4 processors in ai_banking |
| Hardcoded tenant_id/correlation_id | 3 files (plan_execute, reflection_loop, ai_tool_dispatch) |
| Missing from `__all__` | 2 (ai_tool_dispatch, bind_skill) |
| Dead code | 3 (identity.py unused TypeVar, ai_tool_dispatch walrus no-op, duplicate json import) |
| Body mutation side effects | 4 processors (pii_mask, pii_unmask, all ai_banking processors via set_body) |
| Logger inconsistency | 1 (bind_skill uses hardcoded string) |
