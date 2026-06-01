"""DSPy critical pipelines registry (K4 S6 W2)."""

from __future__ import annotations

from src.backend.services.ai.dspy.pipelines.credit_scoring import (
    credit_scoring_pipeline,
)
from src.backend.services.ai.dspy.pipelines.document_parser import (
    document_parser_pipeline,
)
from src.backend.services.ai.dspy.pipelines.rag_reranker import rag_reranker_pipeline

CRITICAL_PIPELINES = (
    credit_scoring_pipeline,
    document_parser_pipeline,
    rag_reranker_pipeline,
)

__all__ = ("CRITICAL_PIPELINES",)
