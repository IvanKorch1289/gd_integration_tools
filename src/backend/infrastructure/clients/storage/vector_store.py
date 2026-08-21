"""Vector store backends — facade module (RE_AUDIT_2026-08-25 split).

Wave 6: god-object refactor 1/5. Original 599-LOC file split into:
* :mod:`qdrant` — QdrantVectorStore (default prod backend, no CVE)
* :mod:`chroma` — ChromaVectorStore (gated by CVE protection)
* :mod:`faiss` — FAISSVectorStore (in-memory, dev/tests)

This module keeps the public API stable (backward-compatible re-exports +
factory function) so existing callers (``tests``, ``infrastructure/cache/rag``,
``infrastructure/storage/vector_pool_registration``, ``plugins/composition``)
work without modification.

ABC :class:`BaseVectorStore` lives in ``core/interfaces/vector_store.py``
(Wave 6 original).
"""

from __future__ import annotations

from typing import Any

from src.backend.core.interfaces.vector_store import BaseVectorStore
from src.backend.core.logging import get_logger

from .chroma import ChromaVectorStore
from .faiss import FAISSVectorStore
from .qdrant import QdrantVectorStore

__all__ = (
    "BaseVectorStore",
    "ChromaVectorStore",
    "FAISSVectorStore",
    "QdrantVectorStore",
    "get_vector_store",
)

_logger = get_logger(__name__)


def get_vector_store(backend: str | None = None, **kwargs: Any) -> BaseVectorStore:
    """Фабрика vector store. Если ``backend`` не указан — берёт значение
    из ``rag_settings.vector_backend`` (default ``qdrant``).
    """
    from src.backend.core.config.rag import rag_settings

    backend_name = (backend or rag_settings.vector_backend).lower()

    match backend_name:
        case "qdrant":
            return QdrantVectorStore(
                url=kwargs.get("url", rag_settings.qdrant_url),
                collection_name=kwargs.get(
                    "collection_name", rag_settings.qdrant_collection
                ),
                api_key=kwargs.get("api_key", rag_settings.qdrant_api_key),
                vector_size=kwargs.get("vector_size", 384),
            )
        case "chroma":
            return ChromaVectorStore(
                host=kwargs.get("host", rag_settings.chroma_host),
                port=kwargs.get("port", rag_settings.chroma_port),
                collection_name=kwargs.get(
                    "collection_name", rag_settings.chroma_collection
                ),
            )
        case "faiss":
            return FAISSVectorStore(dimension=kwargs.get("dimension", 384))
        case _:
            raise ValueError(
                f"Неизвестный vector_backend: {backend_name!r}. "
                "Поддерживается: qdrant, chroma, faiss."
            )
