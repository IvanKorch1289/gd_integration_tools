"""S60 W3 — workflow_audit.py part of setup_infra decomp.

Funcs: _init_workflow_audit_sink, _close_workflow_audit_sink.

workflow audit sink init/close.
"""

from __future__ import annotations

from src.backend.core.logging import get_logger
from src.backend.infrastructure.clients.storage.clickhouse import get_clickhouse_client

app_logger = get_logger("application")


async def _init_workflow_audit_sink() -> None:
    """Создаёт :class:`WorkflowAuditSink` + :class:`ClickHouseBulkWriter`.

    Прогоняет миграцию ``0010_workflow_audit.sql`` (idempotent),
    стартует bulk-writer и регистрирует singleton sink. Все шаги
    обёрнуты в ``try/except``: если ClickHouse недоступен — sink
    остаётся ``None``, и :class:`WorkflowFacade` работает в no-op
    режиме (см. docstring facade).
    """
    from pathlib import Path

    from src.backend.infrastructure.clients.storage.clickhouse_bulk_writer import (
        ClickHouseBulkWriter,
    )
    from src.backend.services.audit.workflow_audit_sink import (
        WorkflowAuditSink,
        set_workflow_audit_sink,
    )

    app_logger = get_logger("application")  # S62 W5: was get_log_manager()
    try:
        client = get_clickhouse_client()
        migrations_dir = (
            Path(__file__).resolve().parents[2] / "services" / "audit" / "migrations"
        )
        ddl_path = migrations_dir / "0010_workflow_audit.sql"
        if ddl_path.exists():
            await client.apply_ddl_file(ddl_path)
        writer = ClickHouseBulkWriter(client=client, table="workflow_audit")
        await writer.start()
        sink = WorkflowAuditSink(writer=writer)
        set_workflow_audit_sink(sink)
        app_logger.info("WorkflowAuditSink инициализирован")
    except Exception as exc:
        app_logger.warning("WorkflowAuditSink init skipped: %s", str(exc)[:200])


async def _close_workflow_audit_sink() -> None:
    """Graceful shutdown sink: финальный flush + остановка writer'а."""
    from src.backend.services.audit.workflow_audit_sink import (
        get_workflow_audit_sink,
        reset_workflow_audit_sink,
    )

    sink = get_workflow_audit_sink()
    if sink is None:
        return
    try:
        await sink.aclose()
    finally:
        reset_workflow_audit_sink()
