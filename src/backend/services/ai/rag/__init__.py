"""Пакет RAG-сервисов (text, image, audio и мультимодальный)."""

from __future__ import annotations

from src.backend.services.ai.rag.classifier import (
    AccuracyBenchmarkResult,
    ClassifierResult,
    QueryClassifier,
    benchmark_accuracy,
)
from src.backend.services.ai.rag.dense_retriever import DenseResult, DenseRetriever
from src.backend.services.ai.rag.hybrid_retriever import (
    HybridResult,
    HybridRetriever,
    rrf_merge,
)
from src.backend.services.ai.rag.hyde_retriever import (
    HyDEConfig,
    HyDEResult,
    HyDERetriever,
)
from src.backend.services.ai.rag.multi_query_retriever import (
    MultiQueryConfig,
    MultiQueryResult,
    MultiQueryRetriever,
)
from src.backend.services.ai.rag.strategy_selector import (
    STRATEGIES,
    AdaptiveStrategySelector,
    StrategyDecision,
)

__all__ = (
    # Strategy selector.
    "AdaptiveStrategySelector",
    "StrategyDecision",
    "STRATEGIES",
    # Classifier.
    "QueryClassifier",
    "ClassifierResult",
    "AccuracyBenchmarkResult",
    "benchmark_accuracy",
    # Dense.
    "DenseRetriever",
    "DenseResult",
    # Hybrid.
    "HybridRetriever",
    "HybridResult",
    "rrf_merge",
    # HyDE.
    "HyDERetriever",
    "HyDEResult",
    "HyDEConfig",
    # Multi-query.
    "MultiQueryRetriever",
    "MultiQueryResult",
    "MultiQueryConfig",
)
