"""Smoke-тесты LiteLLMGateway: default-OFF поведение и lazy-import."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.services.ai.gateway.client import LiteLLMGateway
from src.backend.services.ai.gateway.exceptions import GatewayUnavailable


def test_gateway_disabled_by_default() -> None:
    """Default-OFF: вызов acompletion поднимает GatewayUnavailable."""
    gw = LiteLLMGateway()
    assert gw._enabled is False  # default


@pytest.mark.asyncio
async def test_gateway_raises_when_disabled() -> None:
    gw = LiteLLMGateway()
    with pytest.raises(GatewayUnavailable):
        await gw.acompletion([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_gateway_acompletion_calls_litellm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подменяем litellm в sys.modules, проверяем вызов acompletion."""
    fake_litellm = SimpleNamespace(
        acompletion=AsyncMock(return_value={"choices": [{"message": {"content": "ok"}}]}),
        success_callback=[],
    )
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    gw = LiteLLMGateway()
    gw._enabled = True
    result = await gw.acompletion(
        [{"role": "user", "content": "hi"}], model="openai/gpt-4o-mini"
    )
    assert result["choices"][0]["message"]["content"] == "ok"
    fake_litellm.acompletion.assert_awaited_once()


@pytest.mark.asyncio
async def test_gateway_aembedding_returns_vectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_response = {"data": [{"embedding": [0.1, 0.2, 0.3]}]}
    fake_litellm = SimpleNamespace(
        aembedding=AsyncMock(return_value=fake_response),
        success_callback=[],
    )
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    gw = LiteLLMGateway()
    gw._enabled = True
    vectors = await gw.aembedding(["hello"])
    assert vectors == [[0.1, 0.2, 0.3]]


@pytest.mark.asyncio
async def test_gateway_rate_limited_raises_normalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.backend.services.ai.gateway.exceptions import GatewayRateLimited

    fake_litellm = SimpleNamespace(
        acompletion=AsyncMock(side_effect=RuntimeError("Rate limit exceeded")),
        success_callback=[],
    )
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    gw = LiteLLMGateway()
    gw._enabled = True
    with pytest.raises(GatewayRateLimited):
        await gw.acompletion([{"role": "user", "content": "hi"}])
