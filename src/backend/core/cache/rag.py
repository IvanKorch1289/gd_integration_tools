"""Capability-checked facade для RAG 3-tier cache (S123 W3).

ADR-0207: services/ai/rag_service/__init__.py импортирует
``ThreeTierRagCache`` из ``infrastructure.cache.rag.three_tier``.
"""

from __future__ import annotations

from src.backend.core.di.providers.infrastructure_facade import (  # noqa: F401
    get_three_tier_rag_cache_class as _get_three_tier_rag_cache_cls,
)
ThreeTierRagCache = _get_three_tier_rag_cache_cls()

__all__ = ("ThreeTierRagCache",)
