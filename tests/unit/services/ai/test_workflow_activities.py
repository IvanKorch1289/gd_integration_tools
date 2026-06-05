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
    llm_activity,
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


def _make_gateway(*, response: Any = None, cost: float = 0.0042) -> Any:
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
        "src.backend.services.ai.workflow_activities._resolve_gateway", lambda: gateway
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


def test_structured_output_invalid_json_warns(monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_resolve_gateway_raises_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """_resolve_gateway поднимает RuntimeError при ошибке импорта."""

    def _boom() -> None:
        raise ImportError("no module")

    monkeypatch.setattr(
        "src.backend.services.ai.gateway.client.get_litellm_gateway",
        _boom,
    )
    with pytest.raises(RuntimeError, match="LiteLLMGateway недоступен"):
        from src.backend.services.ai.workflow_activities import _resolve_gateway

        _resolve_gateway()


def test_heartbeat_async_exception_suppressed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Async heartbeat который падает — не прокидывает исключение наружу."""
    monkeypatch.setattr(
        "src.backend.services.ai.workflow_activities._resolve_gateway",
        lambda: _make_gateway(),
    )

    async def _bad_hb() -> None:
        raise RuntimeError("hb boom")

    # Не должно упасть
    out = asyncio.run(_execute_llm_call(LLMActivityInput(prompt="x"), heartbeat=_bad_hb))
    assert out.content == "hello"


def test_acost_estimate_exception_uses_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ошибка acost_estimate → cost_usd = 0.0."""
    gateway = _make_gateway()
    gateway.acost_estimate = AsyncMock(side_effect=RuntimeError("cost err"))
    monkeypatch.setattr(
        "src.backend.services.ai.workflow_activities._resolve_gateway", lambda: gateway
    )
    out = asyncio.run(_execute_llm_call(LLMActivityInput(prompt="x")))
    assert out.cost_usd == 0.0


def test_llm_activity_with_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    """llm_activity передаёт temporalio.activity.heartbeat в _execute_llm_call."""
    hb_mock = MagicMock()
    monkeypatch.setattr(
        "src.backend.services.ai.workflow_activities._resolve_gateway",
        lambda: _make_gateway(),
    )
    # Подставляем temporalio.activity в sys.modules чтобы локальный import сработал
    fake_activity_mod = MagicMock()
    fake_activity_mod.heartbeat = hb_mock
    monkeypatch.setitem(
        __import__("sys").modules,
        "temporalio.activity",
        fake_activity_mod,
    )
    out = asyncio.run(llm_activity(LLMActivityInput(prompt="x")))
    assert out.content == "hello"


def test_register_llm_activity_flag_import_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если импорт feature_flags падает — register возвращает False (NoOp)."""
    monkeypatch.setattr(
        "src.backend.core.config.features.feature_flags",
        None,
    )
    # Удалим атрибут чтобы getattr упал
    monkeypatch.delattr(
        "src.backend.core.config.features.feature_flags",
        raising=False,
    )
    worker = MagicMock()
    assert register_llm_activity(worker) is False


def test_register_llm_activity_via_activities_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fallback регистрация через worker.activities.append."""
    monkeypatch.setattr(
        "src.backend.core.config.features.feature_flags.ai_workflow_activity_enabled",
        True,
    )
    worker = MagicMock(spec=["activities"])
    worker.activities = []
    assert register_llm_activity(worker) is True
    assert len(worker.activities) == 1


def test_register_llm_activity_activities_not_mutable(monkeypatch: pytest.MonkeyPatch) -> None:
    """worker.activities не mutable → возвращает False."""
    monkeypatch.setattr(
        "src.backend.core.config.features.feature_flags.ai_workflow_activity_enabled",
        True,
    )
    worker = MagicMock(spec=["activities"])
    worker.activities = (MagicMock(),)  # tuple — нет append
    assert register_llm_activity(worker) is False


def test_register_llm_activity_no_registration_method(monkeypatch: pytest.MonkeyPatch) -> None:
    """Worker без register_activity и activities → False."""
    monkeypatch.setattr(
        "src.backend.core.config.features.feature_flags.ai_workflow_activity_enabled",
        True,
    )
    worker = MagicMock()
    del worker.register_activity
    del worker.activities
    assert register_llm_activity(worker) is False


def test_module_level_temporalio_wrap(monkeypatch: pytest.MonkeyPatch) -> None:
    """При импорте с доступным temporalio модуль оборачивает llm_activity."""
    import importlib
    import sys

    fake_temporalio = MagicMock()
    fake_activity = MagicMock()
    fake_activity.defn = MagicMock(return_value=lambda f: f)
    fake_temporalio.activity = fake_activity
    monkeypatch.setitem(sys.modules, "temporalio", fake_temporalio)
    monkeypatch.setitem(sys.modules, "temporalio.activity", fake_activity)
    import src.backend.services.ai.workflow_activities as wamod

    importlib.reload(wamod)
    monkeypatch.setattr(wamod, "_resolve_gateway", lambda: _make_gateway())
    out = asyncio.run(wamod.llm_activity(wamod.LLMActivityInput(prompt="x")))
    assert out.content == "hello"
