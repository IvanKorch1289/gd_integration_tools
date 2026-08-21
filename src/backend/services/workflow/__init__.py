"""Workflow registry facade для entrypoints (S45 W2 + Sprint 224 lazy proxy).

Single entry-point для WorkflowRegistry access из entrypoints layer.
Re-export canonical ``infrastructure.workflow.registry`` symbols.

Sprint 224 refactor: convert direct re-export to ``__getattr__``-based lazy
proxy (ponytail: thin proxy). Устраняет layer-violation
``services → infrastructure``.

Использование::

    from src.backend.services.workflow import WorkflowDescriptor, workflow_registry

Layer policy: entrypoints -> services (allowed per V22).
"""

from __future__ import annotations as annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.infrastructure.workflow.registry import (
        WorkflowDescriptor,
        workflow_registry,
    )

__all__ = ("WorkflowDescriptor", "workflow_registry")


def __getattr__(name: str) -> Any:
    """Lazy proxy: import infrastructure только при lookup атрибута."""
    if name in {"WorkflowDescriptor", "workflow_registry"}:
        from src.backend.core.api.workflow import registry as _m

        return getattr(_m, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
