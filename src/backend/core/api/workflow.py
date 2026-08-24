"""Sprint 38: workflow facade — re-exports canonical workflow primitives.

R13 FIX (2026-08-30): expose ``registry`` sub-module through this facade
so the lazy proxy in :mod:`src.backend.services.workflow` resolves correctly.

The lazy proxy expects module-level access to ``registry`` to fetch
``WorkflowDescriptor`` and ``workflow_registry`` without violating
services → infrastructure layer policy.

Layer policy: entrypoints → services. services → core.api (facade).
core.api → infrastructure (allowed via facade).
"""
from __future__ import annotations

from src.backend.infrastructure import workflow as _workflow
from src.backend.infrastructure.workflow import registry

__all__ = ["workflow", "registry"]

# Re-export the parent ``workflow`` module for backward compat with
# callers that did ``from src.backend.core.api.workflow import workflow``.
workflow = _workflow
