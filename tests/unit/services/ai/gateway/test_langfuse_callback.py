"""Тесты LangFuseCostCallback (Wave D.5)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_callback_noop_when_client_unavailable() -> None:
    from src.backend.services.ai.gateway.langfuse_callback import LangFuseCostCallback

    cb = LangFuseCostCallback()
    cb(kwargs={"model": "gpt-4o-mini"}, response_obj={"choices": []})
    # без исключения — OK


@pytest.mark.asyncio
async def test_callback_invokes_trace_generation() -> None:
    from src.backend.services.ai.gateway.langfuse_callback import LangFuseCostCallback

    cb = LangFuseCostCallback()
    fake_generation = MagicMock()
    fake_trace = MagicMock()
    fake_trace.generation = fake_generation
    client = MagicMock()
    client.trace.return_value = fake_trace
    cb._lf = client
    cb._inited = True

    response: dict[str, Any] = {
        "choices": [{"message": {"content": "Hello"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        "response_cost": 0.0012,
    }
    cb(
        kwargs={"model": "openai/gpt-4o-mini", "messages": [], "metadata": {"tenant": "t1"}},
        response_obj=response,
    )

    client.trace.assert_called_once()
    fake_generation.assert_called_once()
    args, kwargs = fake_generation.call_args
    assert kwargs["model"] == "openai/gpt-4o-mini"
    assert kwargs["usage"]["total_tokens"] == 3
