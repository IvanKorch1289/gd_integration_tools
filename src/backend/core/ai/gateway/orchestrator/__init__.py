"""S175 M2.1 (ARC-009): AIGateway orchestrator subpackage.

Split AIGateway logic into dedicated subpackage для maintainability.
Originally single file ``gateway_orchestrator_mixin.py`` (380 LOC).

Modules:
- :mod:`enforced_invoke` — :class:`EnforcedInvokeMixin` (9-step pipeline)
"""

from __future__ import annotations as annotations

from src.backend.core.ai.gateway.orchestrator.enforced_invoke import EnforcedInvokeMixin  # noqa: F401 — re-export

__all__ = ("EnforcedInvokeMixin",)
