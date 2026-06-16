"""RAGService package (S64 W4 decomp from rag_service.py 478 LOC).

14 methods decomposed в 4 mixin files + state.py:
- ``ingest_mixin.py`` (5): _cache_key, chunk_text, _embed, ingest, _invalidate_namespace
- ``search_mixin.py`` (1): search
- ``augment_mixin.py`` (3): augment_prompt, augment_prompt_with_citations, augment
- ``collection_mixin.py`` (4): delete, delete_collection, get_collection_stats, count
- ``state.py``: RAGCitation

Core (1) остается в __init__.py: __init__.

Backward-compat: ``from src.backend.services.ai.rag_service import RAGService`` works.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.backend.core.di import app_state_singleton
from src.backend.core.interfaces.vector_store import BaseVectorStore
from src.backend.services.ai.embedding_providers import (
    EmbeddingProvider,
    get_embedding_provider,
)

if TYPE_CHECKING:  # pragma: no cover
    from src.backend.core.cache.rag import ThreeTierRagCache

from src.backend.services.ai.rag_service.augment_mixin import (
    AugmentMixin,  # S64 W4: MRO
)
from src.backend.services.ai.rag_service.collection_mixin import (
    CollectionMixin,  # S64 W4: MRO
)
from src.backend.services.ai.rag_service.ingest_mixin import IngestMixin  # S64 W4: MRO
from src.backend.services.ai.rag_service.search_mixin import (
    SearchMixin,  # S64 W4: MRO
    _extract_source_id,  # S152 W2: re-export для tests
    _filter_by_embedding_version,  # S152 W1: re-export для tests
    _format_context_with_sources,  # S152 W2: re-export для tests
)
from src.backend.services.ai.rag_service.state import RAGCitation  # S64 W4: re-export
from src.backend.services.ai.rag_types import AugmentResult, FreshnessLabel

__all__ = (
    "AugmentResult",
    "FreshnessLabel",
    "RAGCitation",
    "RAGService",
    "_extract_source_id",
    "_filter_by_embedding_version",
    "_format_context_with_sources",
)


@app_state_singleton("rag_service")
def get_rag_service() -> RAGService:
    """S124 W2: восстановлено (потеряно при S64 W4 decomp).

    Singleton-factory для RAGService через app_state_singleton.
    Используется lazy-импортом из hybrid_rag / semantic_cache /
    feedback_indexer / ai_agent.rag_mixin.
    """
    # S133 W4: default store — memory-backed vector store для non-request
    # контекстов (tests / DSL без зарегистрированного app.state).
    from src.backend.core.vector_store.memory import InMemoryVectorStore

    return RAGService(store=InMemoryVectorStore())


class RAGService(IngestMixin, SearchMixin, AugmentMixin, CollectionMixin):
    """RAG service (4 mixins = 13 methods + 1 core)."""

    __slots__ = ("_store", "_embedder", "_cache")

    def __init__(
        self,
        store: BaseVectorStore,
        embedder: EmbeddingProvider | None = None,
        cache: ThreeTierRagCache | None = None,
    ) -> None:
        self._store = store
        self._embedder = embedder or get_embedding_provider()
        self._cache = cache
