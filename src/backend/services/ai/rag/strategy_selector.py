"""Adaptive RAG strategy selector (Sprint 11 K4 W3).

LLM-based classifier выбирает retrieval-стратегию ``dense|hybrid|hyde|multi_query``
по типу пользовательского query. При недоступности классификатора —
graceful fallback на ``dense`` (default).

Цель — снизить latency overhead < 50ms (DoD#2). При повторных похожих
запросах используется in-memory кэш для ответа за < 5 мкс.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

__all__ = ("STRATEGIES", "AdaptiveStrategySelector", "StrategyDecision")

logger = logging.getLogger("services.ai.rag.strategy_selector")

# Поддерживаемые стратегии — должны совпадать с RagQueryProcessor _RAG_STRATEGIES.
STRATEGIES: tuple[str, ...] = ("dense", "hybrid", "hyde", "multi_query")


@dataclass(frozen=True, slots=True)
class StrategyDecision:
    """Результат селектора стратегии.

    Attributes:
        strategy: Имя выбранной стратегии (``dense``/``hybrid``/``hyde``/``multi_query``).
        confidence: Уверенность классификатора [0..1]; 0.0 для default fallback.
        elapsed_ms: Время выполнения select() в миллисекундах (для bench).
        from_cache: True, если результат взят из in-memory кэша.
    """

    strategy: str
    confidence: float
    elapsed_ms: float
    from_cache: bool = False


def _heuristic_strategy(query: str) -> tuple[str, float]:
    """Простая эвристика на основе query-features.

    * длинные multi-предложенческие запросы → multi_query;
    * содержит вопрос «как/почему/что» — hyde (hypothetical);
    * содержит entity-like uppercase tokens — hybrid (keyword+dense);
    * иначе dense.

    Используется как 1) fast-path при отключенном LLM и 2) как fallback,
    если LLM-classifier вернул unexpected value.
    """
    q = query.strip()
    if not q:
        return "dense", 1.0

    lower = q.lower()
    word_count = len(q.split())
    sentence_count = q.count(".") + q.count("!") + q.count("?")

    if sentence_count >= 2 or word_count > 25:
        return "multi_query", 0.7
    if any(w in lower for w in ("как ", "почему ", "что такое", "how ", "why ")):
        return "hyde", 0.65
    if any(token.isupper() and len(token) > 2 for token in q.split()):
        return "hybrid", 0.6
    return "dense", 0.55


class AdaptiveStrategySelector:
    """Selector с in-memory LRU-кэшем и optional LLM-классификатором.

    Args:
        cache_size: Максимум записей в LRU.
        llm_classify: Опциональная async callable
            ``(query: str) -> tuple[str, float]`` для production-режима.
            Если None — используется только эвристика.
    """

    def __init__(
        self,
        cache_size: int = 512,
        llm_classify: Callable[[str], Awaitable[tuple[str, float]]] | None = None,
    ) -> None:
        self._cache_size = cache_size
        self._cache: dict[str, tuple[str, float]] = {}
        self._llm_classify = llm_classify
        self._stats: dict[str, int] = dict.fromkeys(STRATEGIES, 0)

    def _cache_key(self, query: str) -> str:
        return hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]

    async def select(self, query: str) -> StrategyDecision:
        """Выбрать стратегию для query."""
        started = time.perf_counter()
        key = self._cache_key(query)
        if key in self._cache:
            strategy, confidence = self._cache[key]
            elapsed = (time.perf_counter() - started) * 1000.0
            return StrategyDecision(
                strategy=strategy,
                confidence=confidence,
                elapsed_ms=elapsed,
                from_cache=True,
            )

        strategy, confidence = _heuristic_strategy(query)
        if self._llm_classify is not None:
            try:
                llm_strategy, llm_conf = await self._llm_classify(query)
                if llm_strategy in STRATEGIES:
                    strategy, confidence = llm_strategy, float(llm_conf)
            except Exception as exc:
                logger.warning("strategy LLM classifier failed: %s", exc)

        # LRU eviction.
        if len(self._cache) >= self._cache_size:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = (strategy, confidence)
        self._stats[strategy] = self._stats.get(strategy, 0) + 1

        elapsed = (time.perf_counter() - started) * 1000.0
        return StrategyDecision(
            strategy=strategy,
            confidence=confidence,
            elapsed_ms=elapsed,
            from_cache=False,
        )

    def stats(self) -> dict[str, int]:
        """Возвращает копию счётчиков выбора по стратегиям (для dashboard)."""
        return dict(self._stats)
