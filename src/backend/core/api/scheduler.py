"""Sprint 38: scheduler facade — re-exports canonical scheduler primitives.

R13 FIX (2026-08-30): expose ``dlq`` and ``scheduler_manager`` sub-modules
through this facade so the lazy proxy in
:mod:`src.backend.services.scheduler.admin` resolves correctly.

The original facade tried to import non-existent ``SchedulerRunner`` and
``scheduler_registry`` symbols from ``infrastructure.scheduler.__init__``
(which is essentially empty — namespace package with docstring only).
The lazy proxy in services layer needs module-level access to:

- ``infrastructure.scheduler.dlq`` (SchedulerDLQStore, get_scheduler_dlq_store)
- ``infrastructure.scheduler.scheduler_manager`` (SchedulerManager, get_scheduler_manager)

Layer policy: entrypoints → services. services → core.api (facade).
core.api → infrastructure (allowed via facade).
"""
from __future__ import annotations

from src.backend.infrastructure.scheduler import dlq, scheduler_manager

# Module-level access (for lazy proxy in services.scheduler.admin)
# Canonical concrete classes live inside these submodules.
__all__ = [
    "dlq",
    "scheduler_manager",
]
