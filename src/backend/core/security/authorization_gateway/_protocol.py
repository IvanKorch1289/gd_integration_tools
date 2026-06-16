"""Structural protocol for AuthorizationGateway mixins.

Sprint 36 (tech-debt): объявляет cross-mixin атрибуты, чтобы mypy видел
``self._audit`` внутри AuditMixin.
"""

from __future__ import annotations

from typing import Any, Protocol

from src.backend.core.security.authorization_gateway.state import AuditCallback


class _AuthorizationGatewayProtocol(Protocol):
    """Общий контракт для AuthorizationGateway mixins."""

    _audit: AuditCallback | None
    _capability_gateway: Any
    _policies: tuple[Any, ...]
    _enabled: bool | None
