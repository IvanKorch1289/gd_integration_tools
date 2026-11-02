"""Workflow step logs: list + drill-down (Sprint 5 K5 W1).

ADR-0422: клиент выровнен с роутером сервера (канон). Эндпоинта
``/api/v1/admin/workflow/step-logs`` не существует — рабочая поверхность:

* список — ``GET /api/v1/admin/workflows`` (workflow-инстансы с фильтрами
  ``workflow_name`` / ``tenant_id`` / ``status_filter`` / ``limit``);
* drill-down — ``GET /api/v1/admin/workflows/{instance_id}`` (инстанс +
  event-log, то есть шаги).
"""

from __future__ import annotations

from typing import Any

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient

__all__ = ("LogsClient",)

#: Маппинг UI-статусов на ``WorkflowStatus`` сервера
#: (pending / running / paused / succeeded / failed / cancelling / …).
_STATUS_MAP: dict[str, str] = {
    "ok": "succeeded",
    "success": "succeeded",
    "succeeded": "succeeded",
    "fail": "failed",
    "failed": "failed",
    "error": "failed",
}


class LogsClient(BaseAPIClient):
    """Клиент для admin/workflows endpoints (список + drill-down)."""

    def list_step_logs(
        self,
        workflow_name: str | None = None,
        tenant_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        status: list[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """GET /api/v1/admin/workflows — список workflow-инстансов.

        Args:
            workflow_name: Фильтр по имени workflow (substring match).
            tenant_id: Фильтр по tenant.
            date_from: Начало периода (ISO date YYYY-MM-DD) — серверный
                список инстансов такого фильтра не поддерживает; диапазон
                доступен на ``GET /api/v1/admin/workflow-audit/events``.
            date_to: Конец периода (аналогично ``date_from``).
            status: Список статусов (ok/fail/retry/timeout). Значения,
                не соответствующие ``WorkflowStatus`` сервера, игнорируются.
            limit: Максимум записей в ответе.

        Returns:
            Список step-логов (dict). При ошибке backend поднимает RuntimeError.

        """
        params: dict[str, Any] = {
            k: v
            for k, v in {
                "workflow_name": workflow_name,
                "tenant_id": tenant_id,
                "limit": limit,
            }.items()
            if v is not None
        }
        status_filter = _status_filter(status)
        if status_filter:
            params["status_filter"] = status_filter
        try:
            result = self._request("GET", "/api/v1/admin/workflows", params=params)
            if isinstance(result, list):
                return [_as_step_row(item) for item in result]
            return []
        except Exception as e:
            raise RuntimeError(f"Failed to fetch step logs: {e}") from e

    def get_step_detail(self, workflow_id: str) -> dict[str, Any]:
        """GET /api/v1/admin/workflows/{instance_id} — drill-down.

        Args:
            workflow_id: Идентификатор workflow (instance_id) для drill-down.

        Returns:
            Подробности workflow со списком всех steps.

        """
        try:
            result = self._request("GET", f"/api/v1/admin/workflows/{workflow_id}")
            if isinstance(result, dict):
                return result
            return {}
        except Exception as e:
            raise RuntimeError(f"Failed to fetch step detail: {e}") from e


def _status_filter(status: list[str] | None) -> str | None:
    """Выбрать первый статус, понятный серверу (``WorkflowStatus``)."""
    for value in status or []:
        mapped = _STATUS_MAP.get(str(value).lower())
        if mapped:
            return mapped
    return None


def _as_step_row(item: Any) -> dict[str, Any]:
    """Привести строку workflow-инстанса к колонкам UI (step-log view)."""
    if not isinstance(item, dict):
        return {}
    row = dict(item)
    # UI ожидает ``workflow_id`` — сервер отдаёт ``id`` инстанса.
    row.setdefault("workflow_id", row.get("id"))
    row.setdefault("ts", row.get("created_at"))
    duration = _duration_ms(row)
    if duration is not None:
        row.setdefault("duration_ms", duration)
    return row


def _duration_ms(row: dict[str, Any]) -> int | None:
    """Длительность инстанса в мс (``finished_at`` − ``created_at``)."""
    created = row.get("created_at")
    finished = row.get("finished_at")
    if not created or not finished:
        return None
    try:
        return int((finished - created).total_seconds() * 1000)
    except (AttributeError, TypeError, ValueError):
        return None
