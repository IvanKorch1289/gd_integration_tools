"""Unit-тесты LLMModelPricing — Sprint 12 K4 W2."""

# ruff: noqa: S101

from __future__ import annotations

from decimal import Decimal

import pytest

from src.backend.services.ai.costs.llm_model_pricing import LLMModelPricing


def test_known_models_have_prices() -> None:
    pricing = LLMModelPricing()
    assert pricing.get_price("gpt-4o") == Decimal("0.005")
    assert pricing.get_price("claude-sonnet-4-6") == Decimal("0.003")
    assert pricing.get_price("claude-opus-4-7") == Decimal("0.015")
    assert pricing.get_price("claude-haiku-4-5") == Decimal("0.0008")


def test_unknown_model_returns_default() -> None:
    pricing = LLMModelPricing()
    assert pricing.get_price("nonexistent-model") == Decimal("0.002")


def test_empty_model_id_returns_default() -> None:
    pricing = LLMModelPricing()
    assert pricing.get_price("") == Decimal("0.002")


def test_model_id_case_insensitive() -> None:
    pricing = LLMModelPricing()
    assert pricing.get_price("GPT-4O") == Decimal("0.005")
    assert pricing.get_price("Claude-Opus-4-7") == Decimal("0.015")


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PRICE_GPT-4O", "0.99")
    pricing = LLMModelPricing()
    assert pricing.get_price("gpt-4o") == Decimal("0.99")


def test_list_known_returns_sorted() -> None:
    pricing = LLMModelPricing()
    known = pricing.list_known()
    assert "gpt-4o" in known
    assert "claude-sonnet-4-6" in known
    assert known == sorted(known)
