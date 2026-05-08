"""Тесты BasePydanticAgent: typed result + lazy ensure_agent."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from src.backend.services.ai.agents_pydantic.base import (
    BasePydanticAgent,
    PydanticAIUnavailable,
)


class _Result(BaseModel):
    text: str
    n: int


def test_agent_requires_result_type() -> None:
    with pytest.raises(TypeError):
        BasePydanticAgent()


def test_agent_accepts_kwarg_result_type() -> None:
    agent = BasePydanticAgent(result_type=_Result, system_prompt="x")
    assert agent.result_type is _Result


@pytest.mark.asyncio
async def test_agent_run_raises_when_pydantic_ai_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pydantic_ai", None)
    agent = BasePydanticAgent(result_type=_Result, gateway=MagicMock())
    with pytest.raises(PydanticAIUnavailable):
        await agent.run("hi")


@pytest.mark.asyncio
async def test_agent_run_uses_mocked_pydantic_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_agent_instance = MagicMock()
    fake_agent_instance.run = AsyncMock(
        return_value=SimpleNamespace(data=_Result(text="ok", n=2))
    )
    fake_module = SimpleNamespace(Agent=MagicMock(return_value=fake_agent_instance))
    monkeypatch.setitem(sys.modules, "pydantic_ai", fake_module)

    gateway = MagicMock()
    agent = BasePydanticAgent(result_type=_Result, gateway=gateway)
    result = await agent.run("test")
    assert isinstance(result, _Result)
    assert result.text == "ok" and result.n == 2
