# CONTEXT.md

## Текущее состояние (2026-05-26 16:25, S27/28 AI Hardening continuation)

**HEAD**: `d94b984e` (S28/W5 skill-registry-toml-impl)
**Session summary**: `vault/session-2026-05-26-1625-summary.md`

### S27/28 P0 AI Hardening — GuardResult foundation + Audit schema ✅

**Коммиты** (5 wave commits + parallel session absorbs):

| Компонент | Файл | Коммит | Изменение |
|----------|------|--------|-----------|
| PolicyEnforcer guard_input/list[GuardResult] | `core/ai/policy/enforcer.py` | `d0da0998` | guard_input/guard_output → list[GuardResult] |
| GuardResult dataclass | `core/ai/errors.py` | `d0da0998` | GuardResult(guard_name, verdict, categories) |
| AIGateway cascade | `core/ai/gateway.py` | `6631163b` | _apply_input/output_guards → list[GuardResult] |
| Audit schema ADR-0071 | `core/audit/schema/ai_invocation.py` | `4d874eb9` | 10 AIInvocationEventType events |
| Audit sink | `core/audit/sinks/ai_unified_sink__.py` | `4d874eb9` | UnifiedAISink + emit_ai_invocation_event() |
| TaskRegistry leak fix | `core/audit/sinks/ai_unified_sink.py` | `2eea1cf2` | asyncio.create_task → TaskRegistry.create_task() |
| DLQ truncation fix | `core/ai/policy/enforcer.py` | `2eea1cf2` | content[:200] в DLQ envelope |

**Верификация**:
```bash
uv run pytest tests/unit/core/ai/policy/test_enforcer.py -v           # 14/14 ✅
uv run pytest tests/unit/core/ai/test_gateway_pipeline.py -v            # 11/11 ✅
uv run pytest tests/unit/core/ai/policy/test_enforcer.py tests/unit/core/ai/test_gateway_pipeline.py -v  # 25/25 ✅
```

### Открытые риски / carryover

1. **(HIGH) AIGateway 9-event audit sequence** — `_enforced_invoke()` нужна обёртка `_AuditContext` + emit_sequence() calls после каждого pipeline step
2. **(MEDIUM) MCP namespace per-tool authz tests** — namespace capability gate
3. **(LOW) LiteLLM Proxy Wave** — deferred, GGUF runtime уже есть

### Следующий шаг

**Cascade guard_result extraction**: дополнить `_enforced_invoke()` с emit_ai_invocation_event() вызовами → 9-event sequence (requested → policy_resolved → sanitized → guarded.input → guarded.output → completed/denied/failed + pii.mask/pii.unmask)

### Параллельные сессии note
- S28/W2/W3/W4 parallel session land → `6631163b` absorbed GuardResult foundation без конфликтов
- pathspec-commit (`git commit -- <pathspec>`) — обязателен при параллельной активности
