from __future__ import annotations

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


from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.backend.core.di import app_state_singleton
from src.backend.core.interfaces.vector_store import BaseVectorStore
from src.backend.core.logging import get_logger
from src.backend.services.ai.embedding_providers import (
    EmbeddingProvider,
    get_embedding_provider,
)
from src.backend.services.ai.rag_augment import (
    AugmentResult,
    FreshnessLabel,
    build_augment_result,
)

if TYPE_CHECKING:  # pragma: no cover
    from src.backend.infrastructure.cache.rag.three_tier import ThreeTierRagCache

from src.backend.services.ai.rag_service.augment_mixin import (
    AugmentMixin,  # S64 W4: MRO
)
from src.backend.services.ai.rag_service.collection_mixin import (
    CollectionMixin,  # S64 W4: MRO
)
from src.backend.services.ai.rag_service.ingest_mixin import IngestMixin  # S64 W4: MRO
from src.backend.services.ai.rag_service.search_mixin import SearchMixin  # S64 W4: MRO
from src.backend.services.ai.rag_service.state import RAGCitation  # S64 W4: re-export

__all__ = ("RAGService", "RAGCitation")


class RAGService(IngestMixin, SearchMixin, AugmentMixin, CollectionMixin):
    """RAG service (4 mixins = 13 methods + 1 core)."""

    __slots__ = ()

    def __init__(
        self,
        store: BaseVectorStore,
        embedder: EmbeddingProvider | None = None,
        cache: ThreeTierRagCache | None = None,
    ) -> None:
        self._store = store
        self._embedder = embedder or get_embedding_provider()
        self._cache = cache
