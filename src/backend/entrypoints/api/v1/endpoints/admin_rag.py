"""Admin REST для RAG strategy stats (Sprint 11 K5 W1).

* ``GET /admin/rag/strategy-stats`` — счётчики выбора стратегий
  AdaptiveStrategySelector (для Streamlit dashboard).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/admin/rag", tags=["admin", "rag"])

# Lazy singleton — создаётся при первом обращении.
_selector_instance: Any = None


def _get_selector() -> Any:
    global _selector_instance
    if _selector_instance is None:
        from src.backend.services.ai.rag.strategy_selector import (
            AdaptiveStrategySelector,
        )

        _selector_instance = AdaptiveStrategySelector()
    return _selector_instance


@router.get(
    "/strategy-stats",
    summary="Adaptive RAG strategy stats для dashboard",
    description=(
        "Возвращает счётчики выбора каждой стратегии "
        "(vector_search / keyword_search / hybrid / reranker) "
        "AdaptiveStrategySelector + текущее значение feature-flag "
        "adaptive_rag_strategy. Используется в Streamlit "
        "Admin dashboard для observability retriever selection."
    ),
    tags=["admin", "rag"],
    responses={
        200: {"description": "Stats по каждой стратегии + feature_flag state."},
        500: {"description": "Ошибка инициализации AdaptiveStrategySelector."},
    },
)
async def strategy_stats() -> dict[str, Any]:
    """Возвращает stats() селектора + текущий feature-flag."""
    from src.backend.core.config.features import feature_flags

    selector = _get_selector()
    stats = selector.stats()
    return {
        "strategies": stats,
        "total": sum(stats.values()),
        "feature_enabled": bool(feature_flags.adaptive_rag_strategy),
    }
