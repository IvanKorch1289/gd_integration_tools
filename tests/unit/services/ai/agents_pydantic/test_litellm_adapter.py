"""Тесты LiteLLMModel adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.services.ai.agents_pydantic.adapter import LiteLLMModel

# pydantic_ai imports — graceful degradation if not installed
try:
    from pydantic_ai.models import ModelRequestParameters
except ImportError:
    ModelRequestParameters = None  # type: ignore[assignment, misc]


@pytest.mark.asyncio
async def test_adapter_forwards_to_gateway() -> None:
    gw = type("G", (), {})()
    gw.acompletion = AsyncMock(return_value={"id": "x"})
    model = LiteLLMModel(gateway=gw, model_name="openai/gpt-4o-mini")
    model_request_params = ModelRequestParameters() if ModelRequestParameters else None
    result = await model.request(
        [{"role": "user", "content": "hi"}],
        model_settings=None,
        model_request_parameters=model_request_params,  # type: ignore[arg-type]
    )
    assert result == {"id": "x"}
    gw.acompletion.assert_awaited_once()


def test_adapter_model_name_default() -> None:
    model = LiteLLMModel(gateway=object())
    assert model.model_name == "litellm-default"


def test_adapter_uses_explicit_model_name() -> None:
    model = LiteLLMModel(gateway=object(), model_name="anthropic/claude-3-5-sonnet")
    assert model.model_name == "anthropic/claude-3-5-sonnet"
