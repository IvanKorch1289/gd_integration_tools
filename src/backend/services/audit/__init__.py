"""Пакет audit-сервисов.

Предоставляет:
    * :class:`~clickhouse_audit_service.ClickHouseAuditService` — отправка
      security/business событий в ClickHouse (audit_events trail).
    * :class:`~clickhouse_audit_service.AuditEvent` — dataclass события.
    * :func:`~clickhouse_audit_service.get_audit_service` — singleton.

По умолчанию (default-OFF через ``feature_flags.audit_clickhouse_enabled``)
сервис принимает emit/emit_batch без реального подключения к ClickHouse.
"""

from __future__ import annotations

from src.backend.services.audit.clickhouse_audit_service import (
    AuditEvent,
    ClickHouseAuditService,
    get_audit_service,
)

__all__ = (
    "AuditEvent",
    "ClickHouseAuditService",
    "get_audit_service",
)
