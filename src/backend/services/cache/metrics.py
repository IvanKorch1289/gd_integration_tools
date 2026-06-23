"""Cache metrics facade для entrypoints (S45 W2).

Single entry-point для cache metrics access из admin endpoints.
Re-export canonical ``infrastructure.cache.metrics_collector`` +
``infrastructure.cache.rag.metrics``.

Использование::

    from src.backend.services.cache.metrics import (
        get_cache_metrics_snapshot, get_metrics_snapshot,
    )

Layer policy: entrypoints -> services (allowed per V22).
"""

from __future__ import annotations

from src.backend.infrastructure.cache.metrics_collector import (  # noqa: E402,F401
    get_cache_metrics_snapshot,
)
from src.backend.infrastructure.cache.rag.metrics import (  # noqa: E402,F401
    get_metrics_snapshot,
)

__all__ = ("get_cache_metrics_snapshot", "get_metrics_snapshot")
