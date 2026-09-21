"""Unit-тесты LiteLLMImageGenerationService (K4 Sprint 7).

Покрывают:
1. default-OFF: is_available() == False при выключенном flag.
2. Пустой prompt → ValueError; capability формат ``image.generate.<provider>``.
3. generate() с mock-litellm возвращает ImageResult (urls + revised_prompts).
4. Cost tracking: record_cost вызывается при response_cost > 0.
5. ImportError litellm → ImageGenerationUnavailable.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from src.backend.services.ai.image_generation import (
    ImageGenerationUnavailable,
    ImageResult,
    LiteLLMImageGenerationService,
)


def test_is_available_false_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """is_available() == False при выключенном voice_image_gen_enabled."""
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "voice_image_gen_enabled", False, raising=False)
    svc = LiteLLMImageGenerationService()
    assert svc.is_available() is False
    assert svc.enabled is False


def test_capability_and_empty_prompt() -> None:
    """capability формат + ValueError на пустой prompt."""
    svc = LiteLLMImageGenerationService(provider="openai", enabled=True)
    assert svc.capability == "image.generate.openai"

    import asyncio

    with pytest.raises(ValueError, match="пустой prompt"):
        asyncio.run(svc.generate("   "))


@pytest.mark.asyncio
async def test_generate_returns_result_via_mock_litellm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """generate() с mock-litellm возвращает ImageResult с urls и revised_prompts."""
    # Изолируем gateway (заставляем fallback на прямой import).
    monkeypatch.setitem(sys.modules, "src.backend.services.ai.gateway", None)

    captured: dict[str, Any] = {}

    def _fake_image_generation(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "data": [
                {
                    "url": "https://example.com/img1.png",
                    "revised_prompt": "кот в шапке (revised)",
                },
                {"url": "https://example.com/img2.png"},
            ],
            "response_cost": 0.04,
        }

    fake_litellm = types.SimpleNamespace(
        image_generation=_fake_image_generation,
        cost_calculator=types.SimpleNamespace(completion_cost=lambda **kw: 0.0),
    )
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    audited: list[tuple[str, str]] = []
    svc = LiteLLMImageGenerationService(
        enabled=True,
        cost_tracking=False,
        capability_audit=lambda cap, model: audited.append((cap, model)),
    )

    result = await svc.generate("кот в шапке", size="1024x1024", model="dall-e-3", n=2)

    assert isinstance(result, ImageResult)
    assert result.urls == [
        "https://example.com/img1.png",
        "https://example.com/img2.png",
    ]
    assert result.revised_prompts == ["кот в шапке (revised)"]
    assert result.model == "dall-e-3"
    assert result.size == "1024x1024"
    assert result.n == 2
    assert result.cost_usd == pytest.approx(0.04)
    assert audited == [("image.generate.openai", "dall-e-3")]
    assert captured["prompt"] == "кот в шапке"
    assert captured["n"] == 2


@pytest.mark.asyncio
async def test_generate_tracks_cost_via_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При cost_tracking=True вызывается AgentMetricsService.record_cost."""
    monkeypatch.setitem(sys.modules, "src.backend.services.ai.gateway", None)

    fake_litellm = types.SimpleNamespace(
        image_generation=lambda **kw: {
            "data": [{"url": "https://x/y.png"}],
            "response_cost": 0.08,
        },
        cost_calculator=types.SimpleNamespace(completion_cost=lambda **kw: 0.0),
    )
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    recorded: list[dict[str, Any]] = []

    class _FakeMetrics:
        def record_cost(self, *, provider: str, model: str, cost_usd: float) -> None:
            recorded.append(
                {"provider": provider, "model": model, "cost_usd": cost_usd}
            )

    fake_metrics_module = types.ModuleType("src.backend.services.ai.metrics")
    fake_metrics_module.get_agent_metrics_service = lambda: _FakeMetrics()  # type: ignore[attr-defined]
    monkeypatch.setitem(
        sys.modules, "src.backend.services.ai.metrics", fake_metrics_module
    )

    svc = LiteLLMImageGenerationService(enabled=True, cost_tracking=True)
    await svc.generate("test", model="dall-e-3")

    assert len(recorded) == 1
    assert recorded[0]["provider"] == "openai"
    assert recorded[0]["model"] == "dall-e-3"
    assert recorded[0]["cost_usd"] == pytest.approx(0.08)


@pytest.mark.asyncio
async def test_generate_raises_when_litellm_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При отсутствии 'litellm' generate → ImageGenerationUnavailable."""
    monkeypatch.setitem(sys.modules, "src.backend.services.ai.gateway", None)
    monkeypatch.setitem(sys.modules, "litellm", None)

    svc = LiteLLMImageGenerationService(enabled=True)
    with pytest.raises(ImageGenerationUnavailable, match="litellm"):
        await svc.generate("cat")
