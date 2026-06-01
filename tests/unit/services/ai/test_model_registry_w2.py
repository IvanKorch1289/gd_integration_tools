"""Тесты S32 W2: ModelRecord capability-tags + LiteLLMGateway dynamic routing.

Wave: ``[wave:s32/w2]``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.services.ai.gateway.client import LiteLLMGateway
from src.backend.services.ai.model_registry import ModelRecord
from src.backend.services.ai.model_registry.adapter import ModelRegistryAdapter

pytestmark = pytest.mark.asyncio


# ── ModelRecord.match_capabilities ──────────────────────────────────────


def _make_record(
    *,
    name: str = "test-model",
    supports_vision: bool = False,
    supports_function_calling: bool = False,
    supports_streaming: bool = False,
    max_tokens: int = 4096,
    latency_tier: str = "standard",
    tags: dict[str, str] | None = None,
) -> ModelRecord:
    return ModelRecord(
        name=name,
        supports_vision=supports_vision,
        supports_function_calling=supports_function_calling,
        supports_streaming=supports_streaming,
        max_tokens=max_tokens,
        latency_tier=latency_tier,  # type: ignore[arg-type]
        tags=tags or {},
    )


class TestMatchCapabilities:
    def test_vision_filter_false_negative(self) -> None:
        rec = _make_record(supports_vision=False)
        assert not rec.match_capabilities(vision=True)

    def test_vision_filter_true_positive(self) -> None:
        rec = _make_record(supports_vision=True)
        assert rec.match_capabilities(vision=True)

    def test_function_calling_filter(self) -> None:
        rec = _make_record(supports_function_calling=True)
        assert rec.match_capabilities(function_calling=True)
        # False = "не требуется" — модель со function_calling подходит
        assert rec.match_capabilities(function_calling=False)

    def test_streaming_filter(self) -> None:
        rec = _make_record(supports_streaming=True)
        assert rec.match_capabilities(streaming=True)

    def test_min_max_tokens_ok(self) -> None:
        rec = _make_record(max_tokens=8192)
        assert rec.match_capabilities(min_max_tokens=4096)
        assert rec.match_capabilities(min_max_tokens=8192)
        assert not rec.match_capabilities(min_max_tokens=16384)

    def test_latency_tier_filter(self) -> None:
        rec = _make_record(latency_tier="fast")
        assert rec.match_capabilities(latency_tier="fast")
        assert not rec.match_capabilities(latency_tier="standard")

    def test_all_filters_match(self) -> None:
        rec = _make_record(
            supports_vision=True,
            supports_function_calling=True,
            supports_streaming=True,
            max_tokens=16384,
            latency_tier="fast",
        )
        assert rec.match_capabilities(
            vision=True,
            function_calling=True,
            streaming=True,
            min_max_tokens=8192,
            latency_tier="fast",
        )

    def test_no_filters_always_true(self) -> None:
        rec = _make_record()
        assert rec.match_capabilities() is True


# ── LiteLLMGateway.find_model_by_capabilities ───────────────────────────


async def test_find_model_by_capabilities_no_registry_returns_default() -> None:
    gw = LiteLLMGateway(default_model="openai/gpt-4o-mini")
    assert gw._default_model == "openai/gpt-4o-mini"
    result = await gw.find_model_by_capabilities()
    assert result == gw._default_model


async def test_find_model_by_capabilities_registry_returns_matching() -> None:
    rec1 = _make_record(
        name="gpt-4o-mini",
        supports_function_calling=True,
        supports_streaming=True,
        max_tokens=16384,
        tags={"provider": "openai"},
    )
    rec2 = _make_record(
        name="claude-sonnet",
        supports_vision=True,
        supports_function_calling=True,
        tags={"provider": "anthropic"},
    )
    mock_registry = MagicMock(spec=ModelRegistryAdapter)
    mock_registry.list_models = AsyncMock(return_value=[rec1, rec2])

    gw = LiteLLMGateway(
        default_model="openai/gpt-4o-mini",
        model_registry=mock_registry,
    )
    result = await gw.find_model_by_capabilities(function_calling=True)
    assert result == "openai/gpt-4o-mini"


async def test_find_model_by_capabilities_vision_filter() -> None:
    rec1 = _make_record(
        name="gpt-4o-mini",
        supports_vision=False,
        tags={"provider": "openai"},
    )
    rec2 = _make_record(
        name="claude-sonnet",
        supports_vision=True,
        tags={"provider": "anthropic"},
    )
    mock_registry = MagicMock(spec=ModelRegistryAdapter)
    mock_registry.list_models = AsyncMock(return_value=[rec1, rec2])

    gw = LiteLLMGateway(
        default_model="openai/gpt-4o-mini",
        model_registry=mock_registry,
    )
    result = await gw.find_model_by_capabilities(vision=True)
    assert result == "anthropic/claude-sonnet"


async def test_find_model_by_capabilities_provider_filter() -> None:
    rec1 = _make_record(
        name="gpt-4o",
        tags={"provider": "openai"},
    )
    rec2 = _make_record(
        name="claude-sonnet",
        tags={"provider": "anthropic"},
    )
    mock_registry = MagicMock(spec=ModelRegistryAdapter)
    mock_registry.list_models = AsyncMock(return_value=[rec1, rec2])

    gw = LiteLLMGateway(
        default_model="openai/gpt-4o-mini",
        model_registry=mock_registry,
    )
    result = await gw.find_model_by_capabilities(preferred_provider="anthropic")
    assert result == "anthropic/claude-sonnet"


async def test_find_model_by_capabilities_no_match_returns_default() -> None:
    rec = _make_record(
        name="gpt-4o-mini",
        supports_vision=False,
        tags={"provider": "openai"},
    )
    mock_registry = MagicMock(spec=ModelRegistryAdapter)
    mock_registry.list_models = AsyncMock(return_value=[rec])

    gw = LiteLLMGateway(
        default_model="openai/gpt-4o-mini",
        model_registry=mock_registry,
    )
    result = await gw.find_model_by_capabilities(vision=True)
    assert result == gw._default_model


async def test_find_model_by_capabilities_registry_error_returns_default() -> None:
    mock_registry = MagicMock(spec=ModelRegistryAdapter)
    mock_registry.list_models = AsyncMock(side_effect=RuntimeError("network"))

    gw = LiteLLMGateway(
        default_model="openai/gpt-4o-mini",
        model_registry=mock_registry,
    )
    result = await gw.find_model_by_capabilities(vision=True)
    assert result == gw._default_model


async def test_find_model_by_capabilities_empty_registry_returns_default() -> None:
    mock_registry = MagicMock(spec=ModelRegistryAdapter)
    mock_registry.list_models = AsyncMock(return_value=[])

    gw = LiteLLMGateway(
        default_model="openai/gpt-4o-mini",
        model_registry=mock_registry,
    )
    result = await gw.find_model_by_capabilities()
    assert result == gw._default_model


# ── Backward compatibility: existing tests still pass ──────────────────


def test_lite_llm_gateway_init_default_model() -> None:
    gw = LiteLLMGateway(default_model="test/model")
    assert gw._default_model == "test/model"


def test_lite_llm_gateway_model_registry_property() -> None:
    mock_registry = MagicMock(spec=ModelRegistryAdapter)
    gw = LiteLLMGateway(model_registry=mock_registry)
    assert gw.model_registry is mock_registry


def test_lite_llm_gateway_model_registry_none_by_default() -> None:
    gw = LiteLLMGateway()
    assert gw.model_registry is None
