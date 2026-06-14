"""Capability-checked facade для RAG 3-tier cache (S123 W3).

ADR-0207: services/ai/rag_service/__init__.py импортирует
``ThreeTierRagCache`` из ``infrastructure.cache.rag.three_tier``.
"""

from __future__ import annotations

from src.backend.infrastructure.cache.rag.three_tier import (  # noqa: F401
    ThreeTierRagCache,
)

__all__ = ("ThreeTierRagCache",)
