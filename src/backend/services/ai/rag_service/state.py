"""Backward-compat alias for RAGCitation.

S36 tech-debt: RAGCitation переехал в ``src.backend.services.ai.rag_types``,
чтобы разорвать circular import между ``rag_augment`` и пакетом ``rag_service``.
"""

from __future__ import annotations

from src.backend.services.ai.rag_types import RAGCitation

__all__ = ("RAGCitation",)
