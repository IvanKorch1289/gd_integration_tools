"""S107 W3 — ``core.audit.facade.ai``: AI workspace audit.

Per-domain helper (S106 W2 Path A pattern A, dict-based).
Used by ``core/ai/workspace_manager.py`` (2 calls).
Accepts raw dict payload (matches legacy ``self._audit(payload)``).
"""

from __future__ import annotations

from typing import Any

from src.backend.core.audit.facade._base import emit_audit

__all__ = ("emit_ai_workspace",)


def emit_ai_workspace(event: dict[str, object]) -> Any:
    """Emit audit event for AI workspace (Path A pattern A, dict-based).

    Used by ``core/ai/workspace_manager.py`` (2 calls). Accepts raw dict
    payload (matches legacy ``self._audit(payload)`` signature).

    Args:
        event: Event dict (e.g. ``{"event": "workspace.create", ...}``).
            Must contain ``"event"`` key for canonical event name.

    Returns:
        Result of ``AuditService.emit()``.
    """
    event_name = str(event.get("event", "ai_workspace.event"))
    details: dict[str, Any] = {
        k: v
        for k, v in event.items()
        if k not in ("event", "actor", "resource", "action", "outcome")
    }
    return emit_audit(
        event=event_name,
        actor=str(event.get("actor", "system")),
        resource=str(event.get("resource", "")),
        action=str(event.get("action", "")),
        outcome=str(event.get("outcome", "success")),
        details=details or None,
    )
