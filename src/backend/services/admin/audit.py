"""Admin audit helpers (S19 K5 W5b).

Emits ``admin.action`` events through the shared audit_callback pattern
(same callback interface as RouteLoader._emit_audit).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from src.backend.infrastructure.logging.factory import get_logger

logger = get_logger(__name__)

# Re-export AuditCallback type for consumers
AuditCallback = Callable[[dict[str, Any]], None]

_audit_callback: Callable[[dict[str, Any]], None] | None = None


def set_audit_callback(cb: Callable[[dict[str, Any]], None] | None) -> None:
    """Inject the shared audit callback (called by app bootstrap)."""
    global _audit_callback
    _audit_callback = cb


def emit_admin_action(
    *,
    actor: str,
    action: str,
    resource: str,
    outcome: str,
    details: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> None:
    """Emit ``admin.action`` audit event.

    Args:
        actor:        Кто совершил действие (user id / service / ``"system"``).
        action:       Название действия (``feature_flag.toggle``, ``session.list``, ...).
        resource:     Ресурс (``flags/<name>``, ``audit``, ``sessions``).
        outcome:      ``allowed`` | ``denied`` | ``error``.
        details:      Доп. контекст (new_value, old_value, filter, ...).
        correlation_id: Опциональный correlation_id (генерируется если не передан).
    """
    cid = correlation_id or str(uuid.uuid4())
    event: dict[str, Any] = {
        "event": "admin.action",
        "correlation_id": cid,
        "timestamp": datetime.now(UTC).isoformat(),
        "actor": actor,
        "action": action,
        "resource": resource,
        "outcome": outcome,
        "details": details or {},
    }
    if _audit_callback is None:
        logger.debug("audit_callback not set — skipping %s", event["event"])
        return
    try:
        _audit_callback(event)
    except Exception as _:
        logger.exception("emit_admin_action failed for %s", event["event"])
