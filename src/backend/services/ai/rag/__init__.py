"""Пакет RAG-сервисов (text, image, audio и мультимодальный)."""

from __future__ import annotations

from src.backend.services.ai.rag.classifier import (  # noqa: F401 — re-export
    AccuracyBenchmarkResult,
    ClassifierResult,
    QueryClassifier,
    benchmark_accuracy,
)
from src.backend.services.ai.rag.dense_retriever import DenseResult, DenseRetriever
from src.backend.services.ai.rag.hybrid_retriever import (  # noqa: F401 — re-export
    HybridResult,
    HybridRetriever,
    rrf_merge,
)
from src.backend.services.ai.rag.hyde_retriever import (  # noqa: F401 — re-export
    HyDEConfig,
    HyDEResult,
    HyDERetriever,
)
from src.backend.services.ai.rag.multi_query_retriever import (  # noqa: F401 — re-export
    MultiQueryConfig,
    MultiQueryResult,
    MultiQueryRetriever,
)
from src.backend.services.ai.rag.strategy_selector import (  # noqa: F401 — re-export
    STRATEGIES,
    AdaptiveStrategySelector,
    StrategyDecision,
)

__all__ = (
    "STRATEGIES",
    "AccuracyBenchmarkResult",
    # Strategy selector.
    "AdaptiveStrategySelector",
    "ClassifierResult",
    "DenseResult",
    # Dense.
    "DenseRetriever",
    "HyDEConfig",
    "HyDEResult",
    # HyDE.
    "HyDERetriever",
    "HybridResult",
    # Hybrid.
    "HybridRetriever",
    "MultiQueryConfig",
    "MultiQueryResult",
    # Multi-query.
    "MultiQueryRetriever",
    # Classifier.
    "QueryClassifier",
    "StrategyDecision",
    "benchmark_accuracy",
    "rrf_merge",
)
