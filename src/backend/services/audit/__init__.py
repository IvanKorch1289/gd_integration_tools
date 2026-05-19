"""Пакет audit-сервисов.

Предоставляет:
    * :class:`~clickhouse_audit_service.ClickHouseAuditService` — отправка
      security/business событий в ClickHouse (audit_events trail).
    * :class:`~clickhouse_audit_service.AuditEvent` — dataclass события.
    * :func:`~clickhouse_audit_service.get_audit_service` — singleton.
    * :class:`~workflow_audit_sink.WorkflowAuditSink` — typed-обёртка над
      ClickHouseBulkWriter для записи workflow lifecycle событий
      в таблицу ``workflow_audit`` (S12 K1 W1).

По умолчанию (default-OFF через ``feature_flags.audit_clickhouse_enabled``)
сервис принимает emit/emit_batch без реального подключения к ClickHouse.
"""

from __future__ import annotations

from src.backend.services.audit.clickhouse_audit_service import (
    AuditEvent,
    ClickHouseAuditService,
    get_audit_service,
)
from src.backend.services.audit.workflow_audit_sink import WorkflowAuditSink

__all__ = (
    "AuditEvent",
    "ClickHouseAuditService",
    "WorkflowAuditSink",
    "get_audit_service",
)
