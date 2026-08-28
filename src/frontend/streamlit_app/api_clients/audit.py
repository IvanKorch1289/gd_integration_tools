"""Audit-replay HTTP client (S34 W1, Phase C close-out).

``AuditClient`` обёртка для ``GET /api/v1/admin/audit/capability``
endpoint. Используется UI page 34 (DSL Отладчик → Аудит Replay) для
drill-down на конкретные HTTP requests в Redis audit stream.

Sprint 34 W1: заменяет ``list_audit_records`` facade direct import.
"""

from __future__ import annotations

from typing import Any

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient

__all__ = ("AuditClient",)


class AuditClient(BaseAPIClient):
    """Клиент для admin/audit-replay endpoint (S34 W1)."""

    def list_records(
        self, *, count: int = 100, start_id: str = "-"
    ) -> list[dict[str, Any]]:
        """GET /api/v1/admin/audit/capability — последние N audit records.

        Args:
            count: Максимум записей (1..1000, server-side clamp).
            start_id: Stream ID начала чтения (``"-"`` = с начала потока).

        Returns:
            List of audit records (пустой если Redis недоступен).
        """
        try:
            result = self._request(
                "GET",
                "/api/v1/admin/audit/capability",
                params={"count": count, "start_id": start_id},
            )
            return result if isinstance(result, list) else []
        except (
            ConnectionError,
            TimeoutError,
            RuntimeError,
            ValueError,
            TypeError,
        ) as audit_exc:
            # cycle-9/D-AUDIT-pattern: narrow exceptions + observability.
            import logging

            logging.getLogger(__name__).debug(
                "streamlit_audit_client.list_records_failed",
                extra={"error": str(audit_exc)},
            )
            return []
