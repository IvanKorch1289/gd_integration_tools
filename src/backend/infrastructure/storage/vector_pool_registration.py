"""Vector store pool registration helper (Sprint I-1.3).

Предоставляет :func:`register_vector_pool_if_available` для интеграции
Qdrant/Chroma vector stores в :class:`UnifiedPoolManager`.

Использование::

    from src.backend.infrastructure.storage.vector_pool_registration import (
        register_vector_pool_if_available,
    )

    register_vector_pool_if_available(manager, name="qdrant_main", backend="qdrant")
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.infrastructure.clients.unified_pool_manager import (
        UnifiedPoolManager,
    )


def qdrant_ping_fn() -> bool:
    """Qdrant liveness check (best-effort)."""
    try:
        from src.backend.infrastructure.clients.storage.vector_store import (
            VectorStoreClient,
        )

        client = VectorStoreClient(backend="qdrant")
        return client.is_available()
    except Exception:
        return False


def chroma_ping_fn() -> bool:
    """Chroma liveness check (best-effort)."""
    try:
        from src.backend.infrastructure.clients.storage.vector_store import (
            VectorStoreClient,
        )

        client = VectorStoreClient(backend="chroma")
        return client.is_available()
    except Exception:
        return False


def register_vector_pool_if_available(
    manager: "UnifiedPoolManager",
    *,
    name: str = "vector_main",
    backend: str = "qdrant",
) -> bool:
    """Регистрирует vector store pool если доступен.

    Args:
        manager: UnifiedPoolManager instance.
        name: Pool name (default ``"vector_main"``).
        backend: ``"qdrant"`` или ``"chroma"``.

    Returns:
        True если pool зарегистрирован, False если vector store недоступен.
    """
    try:
        ping_fn = qdrant_ping_fn if backend == "qdrant" else chroma_ping_fn
        # Регистрируем как LOGICAL pool (через ping_fn) — VectorStoreClient
        # сам управляет HTTP соединениями.
        manager.register(
            name=name,
            pool=None,  # logical pool — реальный объект в VectorStoreClient
            ping_fn=ping_fn,
        )
        return True
    except Exception:
        return False


__all__ = (
    "chroma_ping_fn",
    "qdrant_ping_fn",
    "register_vector_pool_if_available",
)
