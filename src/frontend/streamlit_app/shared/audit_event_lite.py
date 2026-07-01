"""Streamlit shared audit-event helper (S176 M11.2 — frontend observability).

Lightweight per-page audit-event helper для observability pattern
extension. Streamlit-only compliance per S174 user rule.

Public API:
    * :func:`emit_admin_error_event` — emit ``frontend.admin.error`` event.
    * :func:`emit_streamlit_page_event` — generic page-event helper.

Pattern: M9.4 (login) + M10.2 (orders CRUD) + M11.2 (admin page)
extension. Centralized helper → single point для frontend observability
evolution. Backward-compat (UI flow unchanged).

Cumulative: a3bb7acc → ... → b1125393 (M11.1) → M11.2.
"""

from __future__ import annotations

import logging
from typing import Any

__all__ = ("emit_admin_error_event", "emit_streamlit_page_event")


def emit_admin_error_event(
    *,
    action: str,
    error: str,
    error_type: str,
    target: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Emit ``frontend.admin.error`` audit-event.

    Args:
        action: Admin action attempted (e.g., ``toggle_plugin``).
        error: Error message.
        error_type: Exception class name.
        target: Optional target identifier (plugin_name, flag_name, etc).
        extra: Optional additional structured fields.

    Notes:
        Lazy-import ``emit_audit_safe`` (dev-envs без DI не сломаются).
        Graceful fallback.
    """
    emit_streamlit_page_event(
        event="frontend.admin.error",
        action=action,
        outcome="failure",
        target=target,
        error=error,
        error_type=error_type,
        page_key="45_Админ",
        extra=extra,
    )


def emit_streamlit_page_event(
    *,
    event: str,
    action: str,
    outcome: str,
    target: str | None = None,
    error: str | None = None,
    error_type: str | None = None,
    page_key: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    """Generic page-event helper.

    Args:
        event: Audit event type.
        action: Action performed.
        outcome: ``"success"`` / ``"failure"``.
        target: Optional target identifier.
        error: Optional error message.
        error_type: Optional exception class name.
        page_key: Page identifier для observability (e.g., ``"45_Админ"``).
        extra: Optional additional structured fields.

    Notes:
        Same facade as :func:`emit_audit_safe` wrapper. Graceful
        fallback (warning log + return) при недоступности facade.
    """
    try:
        from src.backend.core.frontend_facade import emit_audit_safe

        details: dict[str, Any] = {"page_key": page_key}
        if target is not None:
            details["target"] = target
        if error is not None:
            details["error"] = error
        if error_type is not None:
            details["error_type"] = error_type
        if extra:
            details.update(extra)

        emit_audit_safe(
            event=event,
            action=action,
            outcome=outcome,
            details=details,
            severity=("info" if outcome == "success" else "warning"),
        )
    except Exception as _exc:  # pragma: no cover — never fail caller
        logging.getLogger("frontend.shared.audit").debug(
            "%s: audit-event emit failed: %s", event, _exc
        )
