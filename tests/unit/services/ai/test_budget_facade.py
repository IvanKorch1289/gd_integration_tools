"""Unit-тесты LiteLLMBudgetFacade (Sprint 9 K4 W2)."""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.tenancy.token_budget import (
    BudgetPeriod,
    InMemoryTokenBudgetBackend,
    TokenBudget,
    TokenBudgetConfig,
)
from src.backend.services.ai.gateway.budget_facade import (
    BudgetEnforcementError,
    LiteLLMBudgetFacade,
)
from src.backend.services.ai.usage_meter import (
    estimate_tokens,
    extract_usage,
)


class _FakeGateway:
    def __init__(self, *, usage: dict[str, int]) -> None:
        self._usage = usage
        self.last_messages: list[dict[str, Any]] | None = None

    async def acompletion(
        self, messages: list[dict[str, Any]], **_: Any
    ) -> dict[str, Any]:
        self.last_messages = messages
        return {
            "choices": [{"message": {"content": "stub"}}],
            "usage": self._usage,
        }


@pytest.fixture
def budget() -> TokenBudget:
    return TokenBudget(
        backend=InMemoryTokenBudgetBackend(),
        default_config=TokenBudgetConfig(
            soft_limit=100,
            hard_limit=200,
            period=BudgetPeriod.DAILY,
        ),
    )


def test_extract_usage_from_dict() -> None:
    response = {"usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    usage = extract_usage(response)
    assert usage.prompt_tokens == 10
    assert usage.completion_tokens == 5
    assert usage.total_tokens == 15


def test_extract_usage_missing() -> None:
    response = {"choices": []}
    usage = extract_usage(response)
    assert usage.total_tokens == 0


def test_estimate_tokens_returns_positive() -> None:
    tokens = estimate_tokens([{"content": "hello world this is a test message"}])
    assert tokens > 1


def test_estimate_tokens_handles_list_content() -> None:
    tokens = estimate_tokens(
        [
            {
                "content": [
                    {"type": "text", "text": "hello"},
                    {"type": "text", "text": "world"},
                ]
            }
        ]
    )
    assert tokens > 1


@pytest.mark.asyncio
async def test_facade_passthrough_when_disabled(budget: TokenBudget) -> None:
    gateway = _FakeGateway(usage={"prompt_tokens": 50, "completion_tokens": 30})
    facade = LiteLLMBudgetFacade(gateway=gateway, budget=budget, enabled=False)
    _, usage = await facade.acompletion(
        tenant_id="t-1",
        messages=[{"role": "user", "content": "ping"}],
    )
    assert usage.total_tokens == 80
    snap = await budget.snapshot(tenant_id="t-1")
    assert snap.used == 0  # budget не вызывался


@pytest.mark.asyncio
async def test_facade_records_usage_when_enabled(budget: TokenBudget) -> None:
    gateway = _FakeGateway(usage={"prompt_tokens": 20, "completion_tokens": 30})
    facade = LiteLLMBudgetFacade(gateway=gateway, budget=budget, enabled=True)
    _, usage = await facade.acompletion(
        tenant_id="t-2",
        messages=[{"role": "user", "content": "ping pong message stub"}],
    )
    assert usage.total_tokens == 50
    snap = await budget.snapshot(tenant_id="t-2")
    # estimate + correction если actual > estimated
    assert snap.used >= 50


@pytest.mark.asyncio
async def test_facade_raises_429_on_hard_limit(budget: TokenBudget) -> None:
    # Пред-заполняем счётчик до hard_limit-1 (200 уже бросило бы)
    await budget.reserve(tenant_id="t-3", tokens=199)
    gateway = _FakeGateway(usage={"prompt_tokens": 1, "completion_tokens": 1})
    facade = LiteLLMBudgetFacade(gateway=gateway, budget=budget, enabled=True)
    with pytest.raises(BudgetEnforcementError) as ctx:
        await facade.acompletion(
            tenant_id="t-3",
            messages=[{"role": "user", "content": "hello"}],
        )
    assert ctx.value.body["error"] == "token_budget_exceeded"
    assert ctx.value.body["tenant_id"] == "t-3"
