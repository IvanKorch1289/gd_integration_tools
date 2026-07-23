# Cycle 2 — Analyst 5 (AI/Agents) — Consolidated

**Status**: success

## P0 (3 findings)

1. `src/backend/dsl/engine/processors/agent_dsl/agent_graph.py:302-313` — **tool-policy fail-open**: при `ImportError`, отсутствии `AgentToolPolicy` в DI или ошибке registry возвращается исходный `tool_actions`; далее передаётся в `_sandbox.run_react()` (L278-281). Security boundary falls back to permissive.

2. `src/backend/dsl/engine/processors/agent_dsl/agent_graph.py:338-348` — **prompt injection в tool execution**: `body.user_input/query/prompt` напрямую интерполируется как `f"{prompt}\n\nContext: {user_input}"` без sanitizer/input guard; результат поступает в ReAct-агент с tools.

3. `src/backend/dsl/engine/processors/agent_dsl/ai_tool_dispatch.py:269-290` — **prompt injection в LLM-controlled tool dispatcher**: `query` из exchange (`ai_tool_dispatch.py:326-332`) напрямую вставляется в selection prompt. LLM формирует `tool_id` и `args`; выбранный callable вызывается с этими аргументами.

## P1 (5 findings)

1. `src/backend/dsl/engine/processors/ai/banking_processors/base.py:49-70,96,118-125` — значения `body.*`/`properties.*` напрямую в prompt через `instructor/litellm`, минуя sanitizer, `InputGuardMixin` и AIGateway pipeline. PII leakage surface.

2. `src/backend/services/ai/memory/langmem/consolidation.py:120-139,162-175` — raw episodic memory (`role`, `content`) объединяется в prompt; извлечённые facts повторно сохраняются без PII masking.

3. `src/backend/dsl/engine/processors/agent_dsl/memory_store.py:99-118` — произвольное значение из body/exchange сохраняется через `backend.save_fact` без PII masking.

4. `src/backend/dsl/engine/processors/ai/guardrails_processor.py:80-99,115-134` — provider guardrails fail-open: ошибка Lakera/NeMo блокирует обработку только при `block_on_failure=True`; `runtime is None` для NeMo → silent return.

5. `src/backend/core/ai/policy/enforcer/input_guard_mixin.py:61-69,109-114` — `nemo:*` и неизвестные input guards возвращают `None`; AIGateway продолжает без результата guard.

6. `src/backend/services/ai/workflow_activities.py:108-134` — `max_tokens=None` без верхней границы передаётся в `gateway.acompletion`, минуя token-budget pipeline AIGateway.

## Проверено чисто
- `core/ai/gateway/orchestrator/enforced_invoke.py:293-378` — AIGateway корректно применяет capability, tool policy, PII sanitization, budget
- `dsl/engine/processors/agent_dsl/agent_run.py:132-160` — AIGateway + timeout + fail-closed
- `services/ai/streaming_service.py:119-141` — cancellation OK
- `core/ai/sandbox.py:81-116`, `infrastructure/ai/e2b_sandbox.py:95-123` — sandbox OK
- Hardcoded API keys в области не найдены

## Cross-cutting finding
Часть AI processors обращается к LLM напрямую, обходя централизованный AIGateway enforcement pipeline. Это та же проблема, что и в P0 Security (tool policy fail-open) — разные обходы одной централизованной проверки.
