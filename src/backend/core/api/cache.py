"""Sprint 38: cache facade."""
from src.backend.infrastructure.cache import metrics_collector
from src.backend.infrastructure.cache.rag import metrics as rag_metrics

__all__ = ["metrics_collector", "rag_metrics", "RagMetrics"]
RagMetrics = rag_metrics
