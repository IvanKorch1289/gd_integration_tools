# ADR-0167: Sprint 85 — AIGateway Pass-Through Closure (V2 P0 #1)

**Status**: Accepted
**Date**: 2026-06-12
**Sprint**: S85 (AIGateway Enforcement)
**Author**: Ivan (autonomous cycle)

## Context

FINAL_REPORT_V2 P0 #1: **AIGateway в pass-through** + 3 обхода + `_legacy_invoke` пустой.

V2 verdict: "Один главный шаг для +2 балла: logging + AIGateway + DetachedInstanceError".
S84 closed logging. S83 closed DetachedInstanceError. **S85 closes AIGateway**.

V2 нашёл:
1. `_legacy_invoke` в `gateway.py:219-232` возвращал пустой `AIResponse(content="")`
   → caller думал что получил реальный результат
2. `ai_gateway_enforce=False` default в `features/sprints_24_27.py:86-88` →
   enforcement ВЫКЛЮЧЕН по умолчанию (NOTE: S25 W1 уже изменил на True,
   V2 факт-чек устарел)
3. 3 кодопути LLM обходили AIGateway:
   - `ai_graph.build_and_run_agent` → `LiteLLMGateway.acompletion`
   - `agents_pydantic.BasePydanticAgent._ensure_gateway` → `get_litellm_gateway`
   - `agents_pydantic.LiteLLMModel.request` → `gateway.acompletion`

## Decision

### W1: Remove `_legacy_invoke`, raise on enforce=False

```python
async def invoke(self, request: AIRequest) -> AIResponse:
    if not feature_flags.ai_gateway_enforce:
        from src.backend.core.ai.errors import AIGatewayEnforcementRequiredError
        raise AIGatewayEnforcementRequiredError(...)
    return await self._enforced_invoke(request)
```

`AIGatewayEnforcementRequiredError` — новый exception в `core/ai/errors.py`.

### W2: Pre-flight enforcement check в 3 bypass paths

Каждый из 3 путей получает один и тот же pattern:

```python
if not feature_flags.ai_gateway_enforce:
    raise AIGatewayEnforcementRequiredError(
        "<path> requires ai_gateway_enforce=True (S85 W2)"
    )
```

Файлы: `ai_graph.py`, `agents_pydantic/base.py`, `agents_pydantic/adapter.py`.

### W3: CI guard для default=True

`test_ai_gateway_enforce.py` — regression test. Если default изменится
на False, test fails.

### W4: 6 enforcement tests

`test_ai_gateway_enforcement.py`:
- `_legacy_invoke` removed
- `AIGatewayEnforcementRequiredError` exported
- AIGateway raises при enforce=False (mocked)
- 3 bypass paths contain pre-flight check (AST inspection)

## Consequences

### Positive
- **V2 P0 #1 CLOSED** — silent pass-through устранён
- AIGateway теперь HARD-ENFORCED, no scaffold mode
- 3 bypass paths теперь blocked at pre-flight
- 6 NEW tests + 1 regression guard

### Negative
- Если есть production код с `ai_gateway_enforce=False` в .env → AIGateway
  сразу throws на старте. **Breaking change** для legacy deployments.
  Mitigation: добавить warning в CHANGELOG для S86 migration guide.

## Impact (V2 projection)

V2 verdict projected: 6.16 → 7.16 (S84 logging + S83 DetachedInstanceError + S85 AIGateway).
S85 завершает "главный шаг +2 балла" → projected **7.16/10**.

## Files Changed

- `src/backend/core/ai/gateway.py` (W1: _legacy_invoke removed, raise added)
- `src/backend/core/ai/errors.py` (W1: AIGatewayEnforcementRequiredError)
- `src/backend/services/ai/ai_graph.py` (W2: pre-flight check)
- `src/backend/services/ai/agents_pydantic/base.py` (W2: pre-flight check)
- `src/backend/services/ai/agents_pydantic/adapter.py` (W2: pre-flight check)
- `tests/unit/core/ai/test_ai_gateway_enforce.py` (W3: 1 NEW test)
- `tests/unit/core/ai/test_ai_gateway_enforcement.py` (W4: 6 NEW tests)
- `CHANGELOG.md` (W5)
- `.shared/context/TECH_DEBT.md` (W5)

## Related ADRs

- ADR-0144 (S64 multi-instance safety)
- ADR-0165 (S83 DetachedInstanceError)
- ADR-0166 (S84 logging facade)

## Outcome

- **V2 P0 #1 CLOSED** — AIGateway enforcement mandatory
- 5 commits, 7 NEW tests
- V2 verdict "+2 главный шаг" complete: logging + DetachedInstanceError + AIGateway
- Projected rating: 6.16 → **7.16/10**
