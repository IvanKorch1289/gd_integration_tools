from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from src.backend.core.logging import get_logger
from src.backend.services.audit.clickhouse_audit_service.state import (
    AuditEvent,  # S68 W2: cross-import
)

if TYPE_CHECKING:
    from src.backend.services.audit.clickhouse_audit_service.service import (
        ClickHouseAuditService,
    )

_logger = get_logger("services.audit.clickhouse")

# S114 W1: module-level singleton state (missing since S68 W2 decomp).
# `_service_instance` + `_service_lock` должны жить в module scope,
# иначе `global` declaration в `get_audit_service` падает с NameError.
_service_instance: ClickHouseAuditService | None = None
_service_lock = threading.Lock()


def _make_default_event_id() -> str:
    """Генерирует уникальный ID события через UUID4.

    Returns:
        Строковое представление UUID4.
    """
    return str(uuid.uuid4())


def _make_default_timestamp() -> datetime:
    """Возвращает текущее время в UTC.

    Returns:
        Текущая временная метка в timezone-aware формате UTC.
    """
    return datetime.now(UTC)


def make_audit_event(
    event_type: str,
    *,
    payload: dict[str, Any] | None = None,
    severity: Literal["info", "warning", "error"] = "info",
    tenant_id: str | None = None,
    user_id: str | None = None,
    route_name: str | None = None,
    event_id: str | None = None,
    timestamp: datetime | None = None,
) -> AuditEvent:
    """Удобный конструктор :class:`AuditEvent` с разумными дефолтами.

    Args:
        event_type: Тип события (например ``user.login``).
        payload: Словарь дополнительных данных.
        severity: Уровень важности.
        tenant_id: ID тенанта.
        user_id: ID пользователя.
        route_name: Имя маршрута.
        event_id: Явный ID (если None — генерируется UUID4).
        timestamp: Явная метка времени (если None — текущее UTC).

    Returns:
        Заполненный экземпляр :class:`AuditEvent`.
    """
    return AuditEvent(
        event_id=event_id or _make_default_event_id(),
        timestamp=timestamp or _make_default_timestamp(),
        event_type=event_type,
        tenant_id=tenant_id,
        user_id=user_id,
        route_name=route_name,
        payload=payload or {},
        severity=severity,
    )


def get_audit_service() -> ClickHouseAuditService:
    """Возвращает глобальный singleton :class:`ClickHouseAuditService`.

    Потокобезопасен. Создаётся при первом обращении.

    Returns:
        Единственный экземпляр :class:`ClickHouseAuditService`.
    """
    # Late import: избегаем circular (service.py не импортирует helpers).
    from src.backend.services.audit.clickhouse_audit_service.service import (
        ClickHouseAuditService,
    )

    global _service_instance
    if _service_instance is not None:
        return _service_instance
    with _service_lock:
        if _service_instance is None:
            _service_instance = ClickHouseAuditService()
    return _service_instance
