from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from src.backend.core.logging import get_logger

_logger = get_logger("core.security.authorization_gateway")


@dataclass
class AuthorizationReason:
    """Одно звено в reason-chain ``AuthorizationDecision``."""

    source: str
    outcome: str
    detail: str | None = None


@dataclass
class AuthorizationDecision:
    """Результат ``authorize()``: allow/deny + reason-chain.

    Attributes:
        allowed: True если все policies в цепочке вернули allow.
        correlation_id: Сквозной идентификатор для трассировки.
        reasons: Цепочка policy-решений по порядку проверки.
        principal: Кто запрашивает (plugin id / user / service).
        resource: Имя ресурса (capability / endpoint / table).
        action: Запрашиваемое действие (read / write / call).
    """

    allowed: bool
    correlation_id: str
    reasons: tuple[AuthorizationReason, ...]
    principal: str
    resource: str
    action: str


# Type aliases for policy step and audit callback used across gateway mixins.
PolicyDecider = Callable[
    [str, str, str, dict[str, Any]], Awaitable[AuthorizationReason]
]
AuditCallback = Callable[[dict[str, Any]], None]
