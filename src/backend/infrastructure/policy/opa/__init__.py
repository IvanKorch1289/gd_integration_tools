"""OPA-policy package (S18 W3, ADR-NEW-1 chain step).

Re-exports:
    :class:`OPAClient` и :class:`PolicyDecision` из :mod:`client` —
    backward-compat alias для существующих импортёров
    (``from src.backend.infrastructure.policy.opa import OPAClient``).

Rego-policies:
    Файлы ``policies/*.rego`` — декларативные политики для OPA-сервера.
    Загружаются OPA отдельно (через bundle/file watch), Python их не
    импортирует. См. ``policies/authz_default.rego`` для reference-scaffold.
"""

from __future__ import annotations

from src.backend.infrastructure.policy.opa.client import OPAClient, PolicyDecision

__all__ = ("OPAClient", "PolicyDecision")
