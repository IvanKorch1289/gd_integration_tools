"""Capability-checked facade для external API base client (S120 W1).

ADR-0207: extensions/* используют ``BaseExternalAPIClient`` для HTTP-интеграций
со внешними API (SKB, DaData, WebAutomation). Изначально класс жил в
``services.core.base_external_api``, что нарушает V22 boundary (extensions
не должны импортировать из services/*).

Этот facade переносит публичную поверхность в ``core.services``.

Migration path:
- ``from src.backend.services.core.base_external_api import BaseExternalAPIClient``
  → ``from src.backend.core.services.base import BaseExternalAPIClient``

Related:
- AGENTS.md (boundary rules)
- ADR-0207 (S120 W5 closure)
"""

from __future__ import annotations

from src.backend.services.core.base_external_api import (  # noqa: F401
    BaseExternalAPIClient,
)

__all__ = ("BaseExternalAPIClient",)
