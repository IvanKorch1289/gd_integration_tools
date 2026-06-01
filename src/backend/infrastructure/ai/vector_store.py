"""Re-export ``QdrantVectorStore`` для обратной совместимости.

Каноническое место — ``src.infrastructure.clients.storage.vector_store``.
Здесь оставлен thin alias, чтобы не ломать прежние импорты.
"""

from __future__ import annotations

from src.backend.infrastructure.clients.storage.vector_store import QdrantVectorStore

__all__ = ("QdrantVectorStore",)
