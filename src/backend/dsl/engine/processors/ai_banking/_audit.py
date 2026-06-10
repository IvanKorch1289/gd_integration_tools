"""Banking AI audit helper (S50 W3 extraction).

Extracted from ``ai_banking.py`` god-file (828 LOC).
Backward-compat: re-exported via ``ai_banking/__init__.py``.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger

__all__ = ("_emit_audit",)

_logger = get_logger("dsl.engine.processors.ai_banking")


async def _emit_audit(
    event: str,
    processor: str,
    params: dict[str, Any],
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """Эмитит audit-event для banking AI процессоров.

    Args:
        event: Event name (e.g., "banking.kyc_aml.verify").
        processor: Processor name.
        params: Input parameters.
        result: Optional result data.
        error: Optional error message.
    """
    try:
        from src.backend.services.audit.audit_service import AuditService

        try:
            from src.backend.infrastructure.service_locator import locator  # type: ignore[import-not-found]  # noqa: I001

            audit = locator.resolve(AuditService)
        except Exception as _:
            audit = None
        if audit is None:
            _logger.debug("audit service not available: %s", event)
            return
        outcome: str = "failure" if error else "success"
        severity: str = "warning" if error else "info"
        payload = {
            "event": event,
            "actor": f"processor:{processor}",
            "resource": f"banking/{processor}",
            "action": event.split(".")[-1] if "." in event else event,
            "outcome": outcome,
            "severity": severity,
            "details": {
                "processor": processor,
                "params": params,
                "result": result,
                "error": error,
            },
        }
        await audit.emit(**payload)
    except Exception as _:
        _logger.debug("audit emit skipped: %s", event)
