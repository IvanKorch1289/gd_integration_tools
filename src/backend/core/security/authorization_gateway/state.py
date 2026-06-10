from __future__ import annotations
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from src.backend.core.interfaces.capability_gateway import CapabilityGatewayProtocol
from src.backend.core.logging import get_logger

_logger = get_logger("core.security.authorization_gateway")

class AuthorizationReason:
    """Одно звено в reason-chain ``AuthorizationDecision``."""

    source: str
    outcome: str
    detail: str | None = None

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
