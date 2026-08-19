"""Cache metrics facade для entrypoints (S45 W2 + Sprint 224 lazy proxy).

Single entry-point для cache metrics access из admin endpoints.
Re-export canonical ``infrastructure.cache.metrics_collector`` +
``infrastructure.cache.rag.metrics``.

Sprint 224 refactor: convert direct re-export to ``__getattr__``-based lazy
proxy (ponytail: thin proxy). Устраняет layer-violation
``services → infrastructure`` (allowlist entries).

Использование::

    from src.backend.services.cache.metrics import (
        get_cache_metrics_snapshot, get_metrics_snapshot,
    )

Layer policy: entrypoints -> services (allowed per V22).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.infrastructure.cache.metrics_collector import (
        get_cache_metrics_snapshot,
    )
    from src.backend.infrastructure.cache.rag.metrics import get_metrics_snapshot

__all__ = ("get_cache_metrics_snapshot", "get_metrics_snapshot")


def __getattr__(name: str) -> Any:
    """Lazy proxy: import infrastructure только при lookup атрибута."""
    if name == "get_cache_metrics_snapshot":
        from src.backend.infrastructure.cache.metrics_collector import (
            get_cache_metrics_snapshot,
        )

        return get_cache_metrics_snapshot
    if name == "get_metrics_snapshot":
        from src.backend.infrastructure.cache.rag.metrics import get_metrics_snapshot

        return get_metrics_snapshot
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
