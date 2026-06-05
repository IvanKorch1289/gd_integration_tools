"""Тесты Sprint 11 K4 W3 — AdaptiveStrategySelector."""

from __future__ import annotations

import pytest

from src.backend.services.ai.rag.strategy_selector import (
    STRATEGIES,
    AdaptiveStrategySelector,
    StrategyDecision,
)


@pytest.mark.asyncio
async def test_short_question_returns_dense() -> None:
    """Простой короткий запрос → dense."""
    selector = AdaptiveStrategySelector()
    decision = await selector.select("кот")
    assert isinstance(decision, StrategyDecision)
    assert decision.strategy == "dense"


@pytest.mark.asyncio
async def test_how_why_question_picks_hyde() -> None:
    """Вопросы 'как'/'почему' → hyde (hypothetical embeddings)."""
    selector = AdaptiveStrategySelector()
    decision = await selector.select("Как работает RAG?")
    assert decision.strategy == "hyde"


@pytest.mark.asyncio
async def test_long_multi_sentence_picks_multi_query() -> None:
    """Многословный multi-sentence query → multi_query."""
    selector = AdaptiveStrategySelector()
    query = (
        "Расскажи про архитектуру системы. Включи details про сервисы. "
        "Какие там зависимости? Расскажи про DI и кеширование тоже."
    )
    decision = await selector.select(query)
    assert decision.strategy == "multi_query"


@pytest.mark.asyncio
async def test_uppercase_entity_picks_hybrid() -> None:
    """Запрос с uppercase entity (API/SDK) → hybrid (keyword+dense)."""
    selector = AdaptiveStrategySelector()
    decision = await selector.select("найди docs FASTAPI Pydantic")
    assert decision.strategy == "hybrid"


@pytest.mark.asyncio
async def test_cache_hit_marks_from_cache() -> None:
    """Повторный select для того же query → from_cache=True."""
    selector = AdaptiveStrategySelector()
    first = await selector.select("test query")
    second = await selector.select("test query")
    assert first.from_cache is False
    assert second.from_cache is True
    assert second.strategy == first.strategy


@pytest.mark.asyncio
async def test_latency_overhead_under_50ms() -> None:
    """DoD #2: overhead < 50ms — эвристика без LLM работает за < 1ms."""
    selector = AdaptiveStrategySelector()
    decision = await selector.select("какие правила api сервиса")
    assert decision.elapsed_ms < 50.0


@pytest.mark.asyncio
async def test_llm_classifier_used_when_available() -> None:
    """LLM-classifier приоритетнее эвристики."""

    async def fake_llm(query: str) -> tuple[str, float]:
        return "multi_query", 0.92

    selector = AdaptiveStrategySelector(llm_classify=fake_llm)
    decision = await selector.select("hello world")
    assert decision.strategy == "multi_query"
    assert decision.confidence == pytest.approx(0.92)


@pytest.mark.asyncio
async def test_strategies_constant_includes_all() -> None:
    """STRATEGIES константа содержит 4 паттерна (без adaptive)."""
    assert STRATEGIES == ("dense", "hybrid", "hyde", "multi_query")
