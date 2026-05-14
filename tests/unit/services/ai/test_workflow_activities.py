"""Тесты LLM-activity wrapper для Temporal (Sprint 4 Wave C)."""
# ruff: noqa: S101

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.services.ai.workflow_activities import (
    LLMActivityInput,
    LLMActivityOutput,
    _execute_llm_call,
    register_llm_activity,
)


class _FakeResponse:
    """Fake LiteLLM response для unit-тестов."""

    def __init__(
        self,
        *,
        content: str = "hello",
        prompt_tokens: int = 5,
        completion_tokens: int = 10,
        model: str = "gpt-4",
    ) -> None:
        self.choices = [{"message": {"content": content}}]
        self.usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }
        self.model = model


def _make_gateway(
    *,
    response: Any = None,
    cost: float = 0.0042,
) -> Any:
    """Сконструировать mock-gateway с acompletion + acost_estimate."""
    gateway = MagicMock()
    gateway.acompletion = AsyncMock(return_value=response or _FakeResponse())
    gateway.acost_estimate = AsyncMock(return_value=cost)
    return gateway


def test_llm_activity_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Успешный LLM-вызов возвращает корректный output."""
    monkeypatch.setattr(
        "src.backend.services.ai.workflow_activities._resolve_gateway",
        lambda: _make_gateway(),
    )
    inp = LLMActivityInput(prompt="ping", model="gpt-4")
    out = asyncio.run(_execute_llm_call(inp))
    assert isinstance(out, LLMActivityOutput)
    assert out.content == "hello"
    assert out.prompt_tokens == 5
    assert out.completion_tokens == 10
    assert out.cost_usd == pytest.approx(0.0042)
    assert out.model_used == "gpt-4"


def test_cost_tracking_invoked(monkeypatch: pytest.MonkeyPatch) -> None:
    """acost_estimate вызывается для каждого вызова."""
    gateway = _make_gateway(cost=0.05)
    monkeypatch.setattr(
        "src.backend.services.ai.workflow_activities._resolve_gateway",
        lambda: gateway,
    )
    asyncio.run(_execute_llm_call(LLMActivityInput(prompt="x")))
    gateway.acost_estimate.assert_called_once()


def test_heartbeat_called(monkeypatch: pytest.MonkeyPatch) -> None:
    """Heartbeat callback вызывается после API-ответа."""
    monkeypatch.setattr(
        "src.backend.services.ai.workflow_activities._resolve_gateway",
        lambda: _make_gateway(),
    )
    heartbeat_calls: list[int] = []

    def _hb() -> None:
        heartbeat_calls.append(1)

    asyncio.run(_execute_llm_call(LLMActivityInput(prompt="x"), heartbeat=_hb))
    assert heartbeat_calls == [1]


def test_structured_output_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """При structured_output_schema content парсится как JSON."""
    response = _FakeResponse(content='{"score": 0.95, "label": "approved"}')
    monkeypatch.setattr(
        "src.backend.services.ai.workflow_activities._resolve_gateway",
        lambda: _make_gateway(response=response),
    )
    inp = LLMActivityInput(prompt="x", structured_output_schema="CreditDecision")
    out = asyncio.run(_execute_llm_call(inp))
    assert out.structured == {"score": 0.95, "label": "approved"}


def test_structured_output_invalid_json_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Невалидный JSON при schema → structured=None, warning логируется."""
    response = _FakeResponse(content="not json")
    monkeypatch.setattr(
        "src.backend.services.ai.workflow_activities._resolve_gateway",
        lambda: _make_gateway(response=response),
    )
    inp = LLMActivityInput(prompt="x", structured_output_schema="CreditDecision")
    out = asyncio.run(_execute_llm_call(inp))
    assert out.structured is None


def test_register_disabled_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """При выключенном feature-flag register_llm_activity возвращает False."""
    monkeypatch.setattr(
        "src.backend.core.config.features.feature_flags.ai_workflow_activity_enabled",
        False,
    )
    worker = MagicMock()
    assert register_llm_activity(worker) is False
    worker.register_activity.assert_not_called()


def test_register_enabled_when_flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """При включённом feature-flag register_llm_activity регистрирует."""
    monkeypatch.setattr(
        "src.backend.core.config.features.feature_flags.ai_workflow_activity_enabled",
        True,
    )
    worker = MagicMock()
    assert register_llm_activity(worker) is True
    worker.register_activity.assert_called_once()


def test_input_validation() -> None:
    """LLMActivityInput валидирует prompt (non-empty) и temperature."""
    with pytest.raises(ValueError):
        LLMActivityInput(prompt="")
    with pytest.raises(ValueError):
        LLMActivityInput(prompt="ok", temperature=3.0)
