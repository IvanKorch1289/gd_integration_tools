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
from collections.abc import Awaitable

if TYPE_CHECKING:
    from src.backend.infrastructure.clients.unified_pool_manager import (
        UnifiedPoolManager,
    )


def _async_ping(backend: str) -> Awaitable[bool]:
    """Лёгкий async ping через ``count()`` (canonical Protocol method).

    Note:
        ``VectorStoreClient`` переименован в ``BaseVectorStore`` + factory
        ``get_vector_store(backend=...)`` (``is_available()`` отсутствует
        в новом интерфейсе). ``count()`` — каноничный liveness probe.
    """

    async def _probe() -> bool:
        try:
            from src.backend.infrastructure.clients.storage.vector_store import (
                get_vector_store,
            )

            client = get_vector_store(backend=backend)
            return (await client.count()) >= 0
        except (ImportError, RuntimeError, OSError, ConnectionError, AttributeError) as probe_exc:  # noqa: BLE001
            # cycle-9/D-AUDIT-926: narrow exceptions + observability.
            # ImportError — vector store missing, RuntimeError —
            # backend unavailable, OSError/ConnectionError — network,
            # AttributeError — API mismatch.
            import logging
            logging.getLogger(__name__).debug(
                "vector_pool._async_ping_failed",
                extra={"backend": backend, "error": str(probe_exc)},
            )
            return False

    return _probe()


def qdrant_ping_fn() -> Awaitable[bool]:
    """Qdrant liveness check (best-effort)."""
    return _async_ping("qdrant")


def chroma_ping_fn() -> Awaitable[bool]:
    """Chroma liveness check (best-effort)."""
    return _async_ping("chroma")


def register_vector_pool_if_available(
    manager: UnifiedPoolManager, *, name: str = "vector_main", backend: str = "qdrant"
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
    except (ImportError, RuntimeError, AttributeError, ValueError) as reg_exc:  # noqa: BLE001
        # cycle-9/D-AUDIT-926: narrow exceptions + observability.
        # ImportError — manager missing, RuntimeError — already registered,
        # AttributeError — manager API change, ValueError — invalid args.
        import logging
        logging.getLogger(__name__).debug(
            "vector_pool.register_failed",
            extra={"name": name, "backend": backend, "error": str(reg_exc)},
        )
        return False


__all__ = ("chroma_ping_fn", "qdrant_ping_fn", "register_vector_pool_if_available")
