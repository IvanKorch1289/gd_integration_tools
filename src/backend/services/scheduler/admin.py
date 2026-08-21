"""Scheduler admin facade для entrypoints (S45 W2 + Sprint 224 lazy proxy).

Single entry-point для scheduler DLQ + manager access из admin endpoints.
Re-export canonical ``infrastructure.scheduler.dlq`` + ``scheduler_manager``.

Sprint 224 refactor: convert direct re-export to ``__getattr__``-based lazy
proxy (ponytail: thin proxy). Устраняет layer-violation
``services → infrastructure``.

Использование::

    from src.backend.services.scheduler.admin import (
        SchedulerDLQStore, get_scheduler_dlq_store, get_scheduler_manager,
    )

Layer policy: entrypoints -> services (allowed per V22).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.infrastructure.scheduler.dlq import (
        SchedulerDLQStore,
        get_scheduler_dlq_store,
    )
    from src.backend.infrastructure.scheduler.scheduler_manager import (
        get_scheduler_manager,
    )

__all__ = ("SchedulerDLQStore", "get_scheduler_dlq_store", "get_scheduler_manager")


def __getattr__(name: str) -> Any:
    """Lazy proxy: import infrastructure только при lookup атрибута."""
    if name in {"SchedulerDLQStore", "get_scheduler_dlq_store"}:
        from src.backend.core.api.scheduler import dlq as _m

        return getattr(_m, name)
    if name == "get_scheduler_manager":
        from src.backend.core.api.scheduler import scheduler_manager as _m

        return getattr(_m, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
