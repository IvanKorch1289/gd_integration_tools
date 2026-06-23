"""Scheduler admin facade для entrypoints (S45 W2).

Single entry-point для scheduler DLQ + manager access из admin endpoints.
Re-export canonical ``infrastructure.scheduler.dlq`` + ``scheduler_manager``.

Использование::

    from src.backend.services.scheduler.admin import (
        SchedulerDLQStore, get_scheduler_dlq_store, get_scheduler_manager,
    )

Layer policy: entrypoints -> services (allowed per V22).
"""

from __future__ import annotations

from src.backend.infrastructure.scheduler.dlq import (  # noqa: E402,F401
    SchedulerDLQStore,
    get_scheduler_dlq_store,
)
from src.backend.infrastructure.scheduler.scheduler_manager import (  # noqa: E402,F401
    get_scheduler_manager,
)

__all__ = ("SchedulerDLQStore", "get_scheduler_dlq_store", "get_scheduler_manager")
