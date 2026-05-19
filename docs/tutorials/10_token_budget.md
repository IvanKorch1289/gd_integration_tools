# Tutorial 10 — Per-tenant token budget setup

> **Prerequisites:** Redis запущен. ~30 минут.

## Цель

Настроить per-tenant LLM token budget с hard/soft limits, обработать
429 в endpoint.

## Шаги

### 1. Конфигурация в composition root

```python
# src/backend/plugins/composition/lifecycle.py
from src.backend.core.tenancy.token_budget import (
    TokenBudget, TokenBudgetConfig, BudgetPeriod,
)

token_budget = TokenBudget(
    backend=RedisTokenBudgetBackend(redis_client=redis),
    default_config=TokenBudgetConfig(
        soft_limit=100_000,
        hard_limit=1_000_000,
        period=BudgetPeriod.DAILY,
        fail_mode="open",
    ),
    configs={
        "bank-corp-enterprise": TokenBudgetConfig(
            soft_limit=10_000_000,
            hard_limit=100_000_000,
            period=BudgetPeriod.DAILY,
        ),
    },
)
```

### 2. Wire в LiteLLM facade

```python
from src.backend.services.ai.gateway.budget_facade import LiteLLMBudgetFacade

llm_facade = LiteLLMBudgetFacade(
    gateway=litellm_gateway,
    budget=token_budget,
    enabled=feature_flags.tenant_token_budget_enabled,
)
```

### 3. Вызов из endpoint

```python
@router.post("/ai/chat")
async def ai_chat(request: ChatRequest, tenant: TenantContext = Depends(...)):
    try:
        response, usage = await llm_facade.acompletion(
            tenant_id=tenant.tenant_id,
            messages=request.messages,
        )
    except BudgetEnforcementError as exc:
        raise HTTPException(429, exc.body)
    return {"text": response.choices[0].message.content, "usage": usage}
```

### 4. Snapshot per tenant

```bash
curl http://localhost:8000/api/v1/admin/budget/<tenant_id>/snapshot
# {"used": 50000, "soft_limit": 100000, "hard_limit": 1000000, ...}
```

### 5. Reset

```bash
curl -X POST http://localhost:8000/api/v1/admin/budget/<tenant_id>/reset
```

### 6. Тестирование

```python
import pytest

@pytest.mark.asyncio
async def test_429_on_overage():
    await budget.reserve(tenant_id="t-test", tokens=999_999)
    with pytest.raises(BudgetExceeded):
        await budget.reserve(tenant_id="t-test", tokens=1_000_001)
```

## What's next?

* Runbook `token-budget-overage.md` — admin escalation.
* SAML handoff: `tenant_from_saml_attributes` (K1 W2).
* DoD-5 (Sprint 9) — token budget complete.
