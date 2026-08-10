"""Config: admin config + trace-logs (observability)."""

from __future__ import annotations

from typing import Any

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient

__all__ = ("ConfigClient",)


class ConfigClient(BaseAPIClient):
    """Клиент для admin config + trace-logs endpoints."""

    def get_config(self) -> dict[str, Any]:
        """Метод get_config (см. signature)."""
        try:
            return self._request("GET", "/api/v1/admin/config")
        except (ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError) as cfg_exc:  # noqa: BLE001
            # cycle-9/D-AUDIT-1069: narrow exceptions + observability.
            # ConnectionError/TimeoutError — server unreachable, RuntimeError
            # — API failure, ValueError — invalid response, TypeError —
            # wrong type.
            import logging
            logging.getLogger(__name__).debug(
                "streamlit_config_client.config_failed",
                extra={"error": str(cfg_exc)},
            )
            return {}

    def get_trace_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        """Метод get_trace_logs (см. signature)."""
        try:
            return self._request(
                "GET", "/api/v1/admin/trace-logs", params={"limit": limit}
            )
        except (ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError) as trace_exc:  # noqa: BLE001
            # cycle-9/D-AUDIT-1069: см. выше — mirror для trace-logs.
            import logging
            logging.getLogger(__name__).debug(
                "streamlit_config_client.trace_logs_failed",
                extra={"error": str(trace_exc)},
            )
            return []
