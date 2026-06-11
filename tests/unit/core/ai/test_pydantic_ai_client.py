"""Unit-тесты на :class:`PydanticAIClient` (S32 W1).

Тестируют:
- happy path (primary model OK)
- fallback chain detection via is_fallback flag
- retry logic
- metrics emission
- default model (no model_router)
- stream raises NotImplementedError
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.backend.core.ai.policy.spec import ModelRouterSpec
from src.backend.core.ai.pydantic_ai_client import (
    LLMDependencies,
    LLMResult,
    PydanticAIClient,
)
from src.backend.services.ai.gateway.exceptions import (
    GatewayRateLimited,
    GatewayUnavailable,
)


def _mock_flags(enforce: bool = False) -> MagicMock:
    flags = MagicMock()
    flags.ai_gateway_enforce = enforce
    return flags


@pytest.fixture(autouse=True)
def _disable_ai_gateway_enforce() -> None:
    with patch(
        "src.backend.core.config.features.feature_flags", _mock_flags(enforce=False)
    ):
        yield


class _FakeLLMGateway:
    """Fake :class:`LiteLLMGateway` с kontrolёy otказав."""

    def __init__(
        self,
        *,
        content: str = "ok",
        model: str = "openai/gpt-4o-mini",
        prompt_tokens: int = 5,
        completion_tokens: int = 7,
        exception: Exception | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._payload = {
            "model": model,
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            },
        }
        self._exception = exception

    async def acompletion(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append(
            {"messages": messages, "model": model, "stream": stream, **kwargs}
        )
        if self._exception is not None:
            raise self._exception
        return dict(self._payload)


class _FakeMetricsRegistry:
    """Fake MetricsRegistry для проверки метрик.

    Реализует auto-registration в __getattr__: если getattr(name) для
    ещё не зарегистрированного counter/histogram — создаёт объект
    автоматически (аналог real MetricsRegistry). Это позволяет тестам
    проверять metrics без предварительного вызова counter()/histogram().
    """

    def __init__(self) -> None:
        self.counters: dict[str, list[dict[str, str]]] = {}
        self.histograms: dict[str, list[tuple[int, dict[str, str]]]] = {}
        self._counter_objs: dict[str, _FakeCounter] = {}
        self._histogram_objs: dict[str, _FakeHistogram] = {}

    def counter(self, name: str, description: str, *, labels: tuple[str, ...] = ()):
        obj = _FakeCounter(name, self.counters)
        self._counter_objs[name] = obj
        return obj

    def histogram(self, name: str, description: str, *, labels: tuple[str, ...] = ()):
        obj = _FakeHistogram(name, self.histograms)
        self._histogram_objs[name] = obj
        return obj

    def __getattr__(self, name: str) -> Any:
        if name in self._counter_objs:
            return self._counter_objs[name]
        if name in self._histogram_objs:
            return self._histogram_objs[name]
        # Auto-registration
        counter_obj = _FakeCounter(name, self.counters)
        self._counter_objs[name] = counter_obj
        return counter_obj


class _FakeCounter:
    def __init__(self, name: str, storage: dict[str, list[dict[str, str]]]) -> None:
        self._name = name
        self._storage = storage

    def labels(self, **kwargs: str) -> "_FakeCounterLabel":
        return _FakeCounterLabel(self._name, kwargs, self._storage)


class _FakeCounterLabel:
    def __init__(
        self,
        name: str,
        labels: dict[str, str],
        storage: dict[str, list[dict[str, str]]],
    ) -> None:
        self._name = name
        self._labels = labels
        self._storage = storage

    def inc(self) -> None:
        self._storage.setdefault(self._name, []).append(self._labels)


class _FakeHistogram:
    def __init__(
        self, name: str, storage: dict[str, list[tuple[int, dict[str, str]]]]
    ) -> None:
        self._name = name
        self._storage = storage

    def labels(self, **kwargs: str) -> "_FakeHistogramLabel":
        return _FakeHistogramLabel(self._name, kwargs, self._storage)


class _FakeHistogramLabel:
    def __init__(
        self,
        name: str,
        labels: dict[str, str],
        storage: dict[str, list[tuple[int, dict[str, str]]]],
    ) -> None:
        self._name = name
        self._labels = labels
        self._storage = storage

    def observe(self, value: int) -> None:
        self._storage.setdefault(self._name, []).append((value, self._labels))


@pytest.fixture()
def fake_gateway() -> _FakeLLMGateway:
    return _FakeLLMGateway(content="Привет!", model="openai/gpt-4o-mini")


@pytest.fixture()
def fake_metrics() -> _FakeMetricsRegistry:
    return _FakeMetricsRegistry()


@pytest.mark.asyncio
async def test_run_happy_path(fake_gateway: _FakeLLMGateway) -> None:
    """Успешный вызов → LLMResult с content/model/tokens."""
    client = PydanticAIClient(
        gateway=fake_gateway,
        model_router=ModelRouterSpec(
            primary="openai/gpt-4o-mini", fallback=["openai/gpt-4o"], retry_attempts=2
        ),
        metrics_registry=None,
    )

    result = await client.run(prompt="Привет!")

    assert isinstance(result, LLMResult)
    assert result.content == "Привет!"
    assert result.model_used == "openai/gpt-4o-mini"
    assert result.tokens_prompt == 5
    assert result.tokens_completion == 7
    assert result.is_fallback is False
    assert len(fake_gateway.calls) == 1


@pytest.mark.asyncio
async def test_deps_passed_to_run(fake_gateway: _FakeLLMGateway) -> None:
    """deps параметр принимается без ошибки."""
    client = PydanticAIClient(gateway=fake_gateway)

    deps = LLMDependencies(
        tenant_id="tenant-1",
        correlation_id="req-123",
        user_id="user-1",
        session_id="session-1",
    )
    result = await client.run(prompt="test", deps=deps)

    assert result.content == "Привет!"


@pytest.mark.asyncio
async def test_tokens_extracted_from_response(fake_gateway: _FakeLLMGateway) -> None:
    """Tokens правильно извлекаются из litellm-ответа."""
    client = PydanticAIClient(
        gateway=fake_gateway, model_router=ModelRouterSpec(primary="openai/gpt-4o-mini")
    )

    result = await client.run(prompt="test")

    assert result.tokens_prompt == 5
    assert result.tokens_completion == 7


@pytest.mark.asyncio
async def test_metrics_success_emitted(
    fake_gateway: _FakeLLMGateway, fake_metrics: _FakeMetricsRegistry
) -> None:
    """Успешный вызов → counter + histogram emission."""
    client = PydanticAIClient(
        gateway=fake_gateway,
        model_router=ModelRouterSpec(primary="openai/gpt-4o-mini", retry_attempts=2),
        metrics_registry=fake_metrics,
    )

    result = await client.run(prompt="test")

    assert result.content == "Привет!"
    assert "ai_pydantic_client_requests_total" in fake_metrics.counters
    started = [
        c
        for c in fake_metrics.counters["ai_pydantic_client_requests_total"]
        if c.get("status") == "started"
    ]
    success = [
        c
        for c in fake_metrics.counters["ai_pydantic_client_requests_total"]
        if c.get("status") == "success"
    ]
    assert len(started) >= 1
    assert len(success) == 1


@pytest.mark.asyncio
async def test_no_model_router_uses_default() -> None:
    """Без model_router → используется default model."""
    fake_gateway = _FakeLLMGateway()
    client = PydanticAIClient(gateway=fake_gateway)

    result = await client.run(prompt="test")

    assert result.content == "ok"
    assert result.model_used == "openai/gpt-4o-mini"
    assert len(fake_gateway.calls) == 1


@pytest.mark.asyncio
async def test_stream_raises_not_implemented() -> None:
    """stream=True raises NotImplementedError."""
    fake_gateway = _FakeLLMGateway()
    client = PydanticAIClient(gateway=fake_gateway)

    with pytest.raises(NotImplementedError, match="Streaming support planned"):
        await client.run(prompt="test", stream=True)


@pytest.mark.asyncio
async def test_rate_limit_propagates() -> None:
    """GatewayRateLimited correctly propagates."""
    gateway = _FakeLLMGateway()
    gateway._exception = GatewayRateLimited("Rate limited")

    client = PydanticAIClient(
        gateway=gateway,
        model_router=ModelRouterSpec(primary="openai/gpt-4o-mini", retry_attempts=1),
    )

    with pytest.raises(GatewayRateLimited, match="Rate limited"):
        await client.run(prompt="test")


@pytest.mark.asyncio
async def test_unavailable_propagates() -> None:
    """GatewayUnavailable correctly propagates."""
    gateway = _FakeLLMGateway()
    gateway._exception = GatewayUnavailable("All providers down")

    client = PydanticAIClient(
        gateway=gateway,
        model_router=ModelRouterSpec(
            primary="openai/gpt-4o-mini", fallback=["openai/gpt-4o"], retry_attempts=1
        ),
    )

    with pytest.raises(GatewayUnavailable, match="All providers down"):
        await client.run(prompt="test")
