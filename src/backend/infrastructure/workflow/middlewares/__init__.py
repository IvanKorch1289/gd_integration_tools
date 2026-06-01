"""Workflow middlewares — наблюдаемость и аудит для workflow-шагов.

Wave ``[wave:s5/k3-w11-step-log-clickhouse]``.

Содержит middleware'ы, которые оборачивают выполнение workflow-шагов:
* StepAuditMiddleware → ClickHouse workflow_step_log (R-V15-14);
* в дальнейшем: TracingMiddleware (OTel custom span attrs).
"""

from src.backend.infrastructure.workflow.middlewares.step_audit import (
    PG_CLICKHOUSE_WORKFLOW_STEP_LOG_DDL,
    StepAuditEvent,
    StepAuditMiddleware,
)

__all__ = (
    "PG_CLICKHOUSE_WORKFLOW_STEP_LOG_DDL",
    "StepAuditEvent",
    "StepAuditMiddleware",
)
