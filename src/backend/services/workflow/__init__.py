"""Workflow registry facade для entrypoints (S45 W2).

Single entry-point для WorkflowRegistry access из entrypoints layer.
Re-export canonical ``infrastructure.workflow.registry`` symbols.

Использование::

    from src.backend.services.workflow import WorkflowDescriptor, workflow_registry

Layer policy: entrypoints -> services (allowed per V22).
Этот facade — единственный разрешённый путь для entrypoints доступа
к WorkflowRegistry без layer-violation.
"""
from __future__ import annotations

from src.backend.infrastructure.workflow.registry import (  # noqa: E402,F401
    WorkflowDescriptor,
    workflow_registry,
)

__all__ = ("WorkflowDescriptor", "workflow_registry")
