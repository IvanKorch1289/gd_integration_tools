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

S45 QW10: AuditService + get_unified_audit_service теперь импортируются
из canonical ``core.audit.facade.audit_service`` (shim удалён в S45 W1).
"""

from __future__ import annotations

from src.backend.core.audit.facade.audit_service import (  # noqa: E402,F401
    AuditService,
    get_unified_audit_service,
)
from src.backend.services.audit.clickhouse_audit_service import (
    AuditEvent,
    ClickHouseAuditService,
    get_audit_service,
)
from src.backend.services.audit.workflow_audit_sink import (
    WorkflowAuditSink,
    get_workflow_audit_sink,
    reset_workflow_audit_sink,
    set_workflow_audit_sink,
)

__all__ = (
    "AuditEvent",
    "AuditService",
    "ClickHouseAuditService",
    "WorkflowAuditSink",
    "get_audit_service",
    "get_unified_audit_service",
    "get_workflow_audit_sink",
    "reset_workflow_audit_sink",
    "set_workflow_audit_sink",
)
