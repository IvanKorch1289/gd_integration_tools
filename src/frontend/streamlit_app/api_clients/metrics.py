"""Метрики: health + admin metrics."""
from __future__ import annotations

from typing import Any

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient

__all__ = ("MetricsClient",)


class MetricsClient(BaseAPIClient):
    """Клиент для health-check + admin metrics endpoints."""

    def get_metrics(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/admin/metrics")

    def get_health(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/health/components")
