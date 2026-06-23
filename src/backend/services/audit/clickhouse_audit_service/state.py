"""S68 W2 - state.py part of clickhouse_audit_service decomp.

Classes: AuditEvent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from src.backend.core.logging import get_logger
from src.backend.core.utils.json_utils import dumps_str

if TYPE_CHECKING:
    pass

_logger = get_logger("services.audit.clickhouse")


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Неизменяемое описание одного audit-события.

    Атрибуты:
        event_id: Уникальный ID события (рекомендуется UUID4 или UUID7).
        timestamp: Временная метка в UTC.
        event_type: Тип события (например ``user.login``, ``order.created``).
        tenant_id: ID тенанта (или None для системных событий).
        user_id: ID пользователя-актора (или None для системных событий).
        route_name: Имя DSL-маршрута или API-пути, из которого пришло событие.
        payload: Произвольный словарь с деталями события (сериализуется в JSON).
        severity: Уровень важности: ``info`` | ``warning`` | ``error``.
    """

    event_id: str
    timestamp: datetime
    event_type: str
    tenant_id: str | None
    user_id: str | None
    route_name: str | None
    payload: dict[str, Any]
    severity: Literal["info", "warning", "error"]

    def to_row(self) -> dict[str, Any]:
        """Преобразует событие в словарь для вставки в ClickHouse.

        Returns:
            Словарь, совместимый с колонками таблицы ``audit_events``.
        """
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp.astimezone(UTC),
            "event_type": self.event_type,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "route_name": self.route_name,
            "payload": dumps_str(self.payload, default=str),
            "severity": self.severity,
        }
