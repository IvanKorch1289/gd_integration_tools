"""Workflow step logs: list + drill-down (Sprint 5 K5 W1)."""

from __future__ import annotations

from typing import Any

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient

__all__ = ("LogsClient",)


class LogsClient(BaseAPIClient):
    """Клиент для admin/workflow/step-logs endpoints."""

    def list_step_logs(
        self,
        workflow_name: str | None = None,
        tenant_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        status: list[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """GET /api/v1/admin/workflow/step-logs — список workflow step-логов.

        Args:
            workflow_name: Фильтр по имени workflow (substring match).
            tenant_id: Фильтр по tenant.
            date_from: Начало периода (ISO date YYYY-MM-DD).
            date_to: Конец периода (ISO date YYYY-MM-DD).
            status: Список статусов для фильтра (ok/fail/retry/timeout).
            limit: Максимум записей в ответе.

        Returns:
            Список step-логов (dict). При ошибке backend поднимает RuntimeError.
        """
        params: dict[str, Any] = {
            k: v
            for k, v in {
                "workflow_name": workflow_name,
                "tenant_id": tenant_id,
                "date_from": date_from,
                "date_to": date_to,
                "status": ",".join(status) if status else None,
                "limit": limit,
            }.items()
            if v is not None
        }
        try:
            result = self._request(
                "GET", "/api/v1/admin/workflow/step-logs", params=params
            )
            if isinstance(result, list):
                return result
            return []
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"Failed to fetch step logs: {e}") from e

    def get_step_detail(self, workflow_id: str) -> dict[str, Any]:
        """GET /api/v1/admin/workflow/step-logs/{workflow_id} — drill-down.

        Args:
            workflow_id: Идентификатор workflow для drill-down.

        Returns:
            Подробности workflow со списком всех steps.
        """
        try:
            result = self._request(
                "GET", f"/api/v1/admin/workflow/step-logs/{workflow_id}"
            )
            if isinstance(result, dict):
                return result
            return {}
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"Failed to fetch step detail: {e}") from e
