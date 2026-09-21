"""Тесты CostTrackingCallback: extract cost / usage и запись в metrics."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.backend.services.ai.gateway.callbacks import CostTrackingCallback


def _make_response(
    cost: float, prompt_tokens: int, completion_tokens: int
) -> SimpleNamespace:
    return SimpleNamespace(
        response_cost=cost,
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        ),
    )


def test_callback_records_cost_and_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    metrics = MagicMock()
    cb = CostTrackingCallback()
    cb._metrics = metrics
    cb({"model": "openai/gpt-4o-mini"}, _make_response(0.0125, 100, 50))
    metrics.record_cost.assert_called_once_with(
        provider="openai", model="openai/gpt-4o-mini", cost_usd=0.0125
    )
    metrics.record_tokens.assert_called_once_with(
        provider="openai",
        model="openai/gpt-4o-mini",
        input_tokens=100,
        output_tokens=50,
    )


def test_callback_handles_missing_cost() -> None:
    metrics = MagicMock()
    cb = CostTrackingCallback()
    cb._metrics = metrics
    cb({"model": "gpt-4o"}, SimpleNamespace())
    metrics.record_cost.assert_not_called()


def test_provider_from_model_default() -> None:
    assert CostTrackingCallback._provider_from_model("gpt-4o") == "openai"
    assert (
        CostTrackingCallback._provider_from_model("anthropic/claude-3-5") == "anthropic"
    )
