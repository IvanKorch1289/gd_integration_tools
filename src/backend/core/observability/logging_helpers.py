"""Structured logging helpers (S173 M8.2 — observability pass).

Lightweight wrappers для consistent structured logging через
existing structlog + stdlib logging integration. Per S172 audit-event
pattern (emit_audit_safe facade) — same pattern для log events.

Public API:
    * :func:`log_with_context` — emit log event с structured ``extra``
      fields (correlation_id, workflow_id, tenant_id, audit_event_type).
    * :func:`log_audit_event_lite` — lightweight variant для services
      которые emit'ят только ``logger.warning(...)`` без full audit
      facade integration.

Use case (per S172 audit-trail lessons):
* service вызывает ``log_audit_event_lite(severity='warning',
  event='cache.invalidate', key=...)`` вместо bare
  ``logger.warning('cache invalidated %s', key)``.
* Structured fields доступны в structlog/OTel pipeline (filtering,
  alerting) — bare strings теряются.

Pattern: S173 M8.2 = non-breaking observability pass. Services могут
постепенно переходить на новые helpers (per S113 W1 incremental
adoption pattern).

Cumulative: a3bb7acc → ... → 6a41824b (M8.1) → M8.2.
"""

from __future__ import annotations

import logging
from typing import Any

__all__ = ("log_audit_event_lite", "log_with_context")

# S173 M8.2: standard field names (audit-event schema convention).
_LOG_FIELD_CORRELATION = "correlation_id"
_LOG_FIELD_TENANT = "tenant_id"
_LOG_FIELD_WORKFLOW = "workflow_id"
_LOG_FIELD_EVENT = "audit_event_type"
_LOG_FIELD_SEVERITY = "severity"
_LOG_FIELD_COMPONENT = "component"


def log_with_context(
    logger: logging.Logger,
    level: int,
    msg: str,
    *,
    correlation_id: str | None = None,
    tenant_id: str | None = None,
    workflow_id: str | None = None,
    audit_event_type: str | None = None,
    component: str | None = None,
    **fields: Any,
) -> None:
    """Emit log event с structured ``extra`` context.

    Args:
        logger: target logger (e.g. ``get_logger(__name__)``).
        level: log level (``logging.INFO``, ``logging.WARNING``, etc).
        msg: log message.
        correlation_id: optional correlation ID (для distributed trace).
        tenant_id: optional tenant context.
        workflow_id: optional workflow ID.
        audit_event_type: optional event-type (например ``auth.api_key.used``).
        component: optional component name (например ``cache_decorator``).
        **fields: дополнительные structured fields.

    Notes:
        * ``extra={...}`` в stdlib-logging — passthrough через
          structlog processor chain.
        * НЕ бросает — caller responsibility for retry/catch.
    """
    extra: dict[str, Any] = dict(fields)
    if correlation_id is not None:
        extra[_LOG_FIELD_CORRELATION] = correlation_id
    if tenant_id is not None:
        extra[_LOG_FIELD_TENANT] = tenant_id
    if workflow_id is not None:
        extra[_LOG_FIELD_WORKFLOW] = workflow_id
    if audit_event_type is not None:
        extra[_LOG_FIELD_EVENT] = audit_event_type
    if component is not None:
        extra[_LOG_FIELD_COMPONENT] = component

    logger.log(level, msg, extra=extra)


def log_audit_event_lite(
    logger: logging.Logger,
    *,
    severity: str,
    event: str,
    message: str | None = None,
    correlation_id: str | None = None,
    tenant_id: str | None = None,
    workflow_id: str | None = None,
    **fields: Any,
) -> None:
    """Lightweight audit-event logging helper (no full facade dep).

    Args:
        logger: target logger.
        severity: ``\"info\"`` / ``\"warning\"`` / ``\"error\"``.
        event: audit event type (например ``cache.invalidate``).
        message: optional message (default = event name).
        correlation_id: optional correlation ID.
        tenant_id: optional tenant context.
        workflow_id: optional workflow ID.
        **fields: structured fields.

    Behavior:
        * ``info`` → ``logger.info(...)``
        * ``warning`` → ``logger.warning(...)``
        * ``error`` → ``logger.error(...)``
        * other → fallback ``logger.info(...)``.

    Use case: services которые не хотят подключать ``core.audit.facade``
    (lazy dependency), но хотят consistent structured logging.
    """
    level = _SEVERITY_TO_LEVEL.get(severity, logging.INFO)
    msg = message or event
    log_with_context(
        logger,
        level,
        msg,
        correlation_id=correlation_id,
        tenant_id=tenant_id,
        workflow_id=workflow_id,
        audit_event_type=event,
        **fields,
    )


_SEVERITY_TO_LEVEL: dict[str, int] = {
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "debug": logging.DEBUG,
}
