"""Метрики: health + admin metrics.

Graceful: при недоступном backend'е возвращают ``{}`` — Streamlit-страница
рендерит empty-state.
"""

from __future__ import annotations

from typing import Any

from src.frontend.streamlit_app.api_clients.base import (
    CLIENT_SAFE_DEFAULT_ERRORS,
    BaseAPIClient,
)

__all__ = ("MetricsClient",)


class MetricsClient(BaseAPIClient):
    """Клиент для health-check + admin metrics endpoints."""

    def get_metrics(self) -> dict[str, Any]:
        """Сводка системы: сервисы / actions / маршруты / feature-флаги.

        ADR-0422: путь выровнен с роутером сервера (канон) — эндпоинта
        ``/admin/metrics`` не существует; ближайший по смыслу —
        ``GET /admin/system-info`` (та же сводка счётчиков).
        """
        try:
            return self._request("GET", "/api/v1/admin/system-info")
        except CLIENT_SAFE_DEFAULT_ERRORS as metrics_exc:
            # cycle-9/D-AUDIT-1065: narrow exceptions + observability.
            # ConnectionError/TimeoutError — server unreachable, RuntimeError
            # — API failure, ValueError — invalid response, TypeError — wrong.
            import logging

            logging.getLogger(__name__).debug(
                "streamlit_metrics_client.metrics_failed",
                extra={"error": str(metrics_exc)},
            )
            return {}

    def get_health(self) -> dict[str, Any]:
        """Метод get_health (см. signature)."""
        try:
            return self._request("GET", "/api/v1/health/components")
        except CLIENT_SAFE_DEFAULT_ERRORS as health_exc:
            # cycle-9/D-AUDIT-1065: см. выше — mirror для health.
            import logging

            logging.getLogger(__name__).debug(
                "streamlit_metrics_client.health_failed",
                extra={"error": str(health_exc)},
            )
            return {}
