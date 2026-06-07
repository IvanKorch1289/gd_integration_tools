"""Config: admin config + trace-logs (observability)."""

from __future__ import annotations

from typing import Any

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient

__all__ = ("ConfigClient",)


class ConfigClient(BaseAPIClient):
    """Клиент для admin config + trace-logs endpoints."""

    def get_config(self) -> dict[str, Any]:
        try:
            return self._request("GET", "/api/v1/admin/config")
        except Exception:  # noqa: BLE001
            return {}

    def get_trace_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        try:
            return self._request(
                "GET", "/api/v1/admin/trace-logs", params={"limit": limit}
            )
        except Exception:  # noqa: BLE001
            return []
