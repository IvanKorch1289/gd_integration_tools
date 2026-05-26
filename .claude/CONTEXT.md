# CONTEXT.md

## Текущее состояние (2026-05-26 18:30, S28 closure / S29 start)

**HEAD**: `163be9c9` (fix Cron_Builder.py except tuple syntax)
**Мой коммит**: `e95c75c0` (layer violations fix)
**Session summary**: `vault/session-2026-05-26-1830-summary.md`

### S28 closure ✅

**Версия**: 0.20.0 (d98290bf)

**Последние коммиты S28**:
- `163be9c9` — Cron_Builder.py Python 3 except tuple syntax fix
- `1b4f1204` — [wave:s29/k4-w0-syntax-fix] 82 Python 2 except clauses + 3 Protocol errors
- `e95c75c0` — [fix(core/audit)] 2 layer violations в ai_unified_sink.py
- `75af9fcd` — Fix F821 undefined AIInvocationEvent + S110 silent exception
- `d98290bf` — release: bump version to 0.20.0

### Layer violations — ИСПРАВЛЕНЫ ✅

**Было**: 2 violations в `core/audit/sinks/ai_unified_sink.py` (core → services.audit + services.ai.gateway)
**Стало**: 0 новых нарушений (`make layers`)

**Решение**: Registry pattern
- `core/audit/interfaces.py` — Protocol definitions (TYPE_CHECKING)
- `services/audit/unified_sink_factory.py` — единая точка создания UnifiedAISink
- `core/audit/sinks/ai_unified_sink.py` — register_emit_ai_invocation_event() + emit_ai_invocation_event()
- `core/ai/gateway.py` — импортирует из core/audit/sinks (registry), не напрямую из services/

### Открытые вопросы

1. **Pre-existing layer violation**: `infrastructure/clients/external/langfuse_client.py` → `services.ai.gateway.langfuse_pii_callback` (существовало до S28, не исправлено)
2. **PLAN.md не содержит S28/S29**: Sprint 28 закрыт но не в плане; Sprint 29 не существует в документе
3. **8 uncommitted файлов**: параллельная сессия изменила `auto_scaler.py`, `integration.py`, `langfuse_client.py`, `browser_pool.py`, `desktop_session_pool.py`, `reactive_dispatcher.py`, схемы docs

### Следующий шаг

1. Определить текущий спринт (S28 closed, нужен ли S29 или это carryover сессия)
2. Исправить pre-existing layer violation в `langfuse_client.py` или внести в backlog
3. Согласовать план — какие S28 carryover waves реализовать

| Компонент | Файл | Коммит | Изменение |
|----------|------|--------|-----------|
| PolicyEnforcer guard_input/list[GuardResult] | `core/ai/policy/enforcer.py` | `d0da0998` | guard_input/guard_output → list[GuardResult] |
| GuardResult dataclass | `core/ai/errors.py` | `d0da0998` | GuardResult(guard_name, verdict, categories) |
| AIGateway cascade | `core/ai/gateway.py` | `6631163b` | _apply_input/output_guards → list[GuardResult] |
| Audit schema ADR-0071 | `core/audit/schema/ai_invocation.py` | `4d874eb9` | 10 AIInvocationEventType events |
| Audit sink | `core/audit/sinks/ai_unified_sink__.py` | `4d874eb9` | UnifiedAISink + emit_ai_invocation_event() |
| TaskRegistry leak fix | `core/audit/sinks/ai_unified_sink.py` | `2eea1cf2` | asyncio.create_task → TaskRegistry.create_task() |
| DLQ truncation fix | `core/ai/policy/enforcer.py` | `2eea1cf2` | content[:200] в DLQ envelope |
| **S27 W6 invoke_agent** | `dsl/workflow/spec.py` + `builder.py` + `step_compilers.py` | `a740fc76` + `3be9fc89` | `AgentInvokeDeclaration` + `invoke_agent()` + `compile_agent_invoke_step` |
| **invoke_agent fix** | `dsl/workflow/compiler/step_compilers.py` + tests | `d94b984e` | AIRequest prompt_inline not messages; test assertion fix |

**Верификация**:
```bash
uv run pytest tests/unit/core/ai/policy/test_enforcer.py -v           # 14/14 ✅
uv run pytest tests/unit/core/ai/test_gateway_pipeline.py -v            # 11/11 ✅
uv run pytest tests/unit/core/ai/policy/test_enforcer.py tests/unit/core/ai/test_gateway_pipeline.py -v  # 25/25 ✅
```

### Открытые риски / carryover

1. **(HIGH) AIGateway 9-event audit sequence** — `_enforced_invoke()` нужна обёртка `_AuditContext` + emit_sequence() calls после каждого pipeline step
2. **(MEDIUM) MCP namespace per-tool authz tests** — namespace capability gate
3. **(MEDIUM) S24 W3 LangGraph Checkpointer** — durable mode в invoke_agent требует интеграции checkpointer (carryover)
4. **(LOW) LiteLLM Proxy Wave** — deferred, GGUF runtime уже есть
5. **(LOW) DoD-8 chaos-test** — integration test restore state ≥ 2 turn (carryover)

### Следующий шаг

**Cascade guard_result extraction**: дополнить `_enforced_invoke()` с emit_ai_invocation_event() вызовами → 9-event sequence (requested → policy_resolved → sanitized → guarded.input → guarded.output → completed/denied/failed + pii.mask/pii.unmask)

### Параллельные сессии note
- S28/W2/W3/W4/W5 parallel session land → `6631163b` absorbed GuardResult, `d94b984e` absorbed W6 fixes
- pathspec-commit (`git commit -- <pathspec>`) — обязателен при параллельной активности

## S27 closure — DoD verification

| DoD | Критерий | Статус |
|-----|----------|--------|
| 1 | `WorkflowBuilder.invoke_agent()` exists | ✅ |
| 2 | `AgentInvokeDeclaration` in `WorkflowStep` union | ✅ |
| 3 | `compile_agent_invoke_step` registered in dispatch | ✅ |
| 4 | `input_context` dot-path resolution | ✅ `prompt_inline` |
| 5 | `output_key` writes to `ctx._outputs` | ✅ |
| 6 | durable mode → checkpointer unavailable → fallback stateless | ✅ |
| 7 | 4 unit tests passing | ✅ 20/20 step_compilers |
| 8 | chaos-test restore state ≥ 2 turn | ⚠️ NOT TESTED (integration) |

## Верификация S27 closure

```bash
uv run pytest tests/unit/dsl/workflow/compiler/test_step_compilers.py -v  # 20/20 ✅
```
