"""Метрики: health + admin metrics.

Graceful: при недоступном backend'е возвращают ``{}`` — Streamlit-страница
рендерит empty-state.
"""

from __future__ import annotations

from typing import Any

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient

__all__ = ("MetricsClient",)


class MetricsClient(BaseAPIClient):
    """Клиент для health-check + admin metrics endpoints."""

    def get_metrics(self) -> dict[str, Any]:
        try:
            return self._request("GET", "/api/v1/admin/metrics")
        except Exception:  # noqa: BLE001
            return {}

    def get_health(self) -> dict[str, Any]:
        try:
            return self._request("GET", "/api/v1/health/components")
        except Exception:  # noqa: BLE001
            return {}
