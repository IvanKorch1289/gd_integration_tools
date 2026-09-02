"""Unit-тесты ``services.ai.semantic_cache`` — coverage ratchet (Post-Plan A Sprint 22).

core/ai/semantic_cache subpackage (S67 W3 decomp from 461 LOC → 3 files per-class):
re-exports 5 symbols (SemanticCache + L3RetrievalGraphCache classes +
get_semantic_cache/get_l3_retrieval_cache singletons + RAG_CACHE_INVALIDATE_CHANNEL
constant). ~10 stmts, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class/constant/callable identity.
"""

from __future__ import annotations

import pytest

from src.backend.services.ai import semantic_cache
from src.backend.services.ai.semantic_cache import (
    RAG_CACHE_INVALIDATE_CHANNEL,
    L3RetrievalGraphCache,
    SemanticCache,
    get_l3_retrieval_cache,
    get_semantic_cache,
)


@pytest.mark.unit
class TestSemanticCacheFacadeAllExports:
    """``__all__`` audit + class/constant/callable identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "RAG_CACHE_INVALIDATE_CHANNEL",
            "L3RetrievalGraphCache",
            "SemanticCache",
            "get_l3_retrieval_cache",
            "get_semantic_cache",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(semantic_cache, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in semantic_cache.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 5 символов."""
        assert len(semantic_cache.__all__) == 5

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает semantic cache (S67 W3 decomp)."""
        assert semantic_cache.__doc__ is not None
        assert "Semantic" in semantic_cache.__doc__ or "cache" in semantic_cache.__doc__.lower()


@pytest.mark.unit
class TestSemanticCacheFacadeIdentity:
    """Identity checks для 5 re-exports."""

    def test_semantic_cache_is_class(self) -> None:
        """``SemanticCache`` — class (8 methods)."""
        assert isinstance(SemanticCache, type)

    def test_l3_retrieval_graph_cache_is_class(self) -> None:
        """``L3RetrievalGraphCache`` — class (10 methods)."""
        assert isinstance(L3RetrievalGraphCache, type)

    def test_get_semantic_cache_is_callable(self) -> None:
        """``get_semantic_cache`` — callable (singleton getter)."""
        assert callable(get_semantic_cache)

    def test_get_l3_retrieval_cache_is_callable(self) -> None:
        """``get_l3_retrieval_cache`` — callable (singleton getter)."""
        assert callable(get_l3_retrieval_cache)

    def test_rag_cache_invalidate_channel_is_string(self) -> None:
        """``RAG_CACHE_INVALIDATE_CHANNEL`` — str constant (Redis channel name)."""
        assert isinstance(RAG_CACHE_INVALIDATE_CHANNEL, str)
        assert len(RAG_CACHE_INVALIDATE_CHANNEL) > 0
