"""Cron/Scheduler API клиент."""

from __future__ import annotations

from typing import Any

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient

__all__ = ("CronClient",)


class CronClient(BaseAPIClient):
    """Клиент для Cron/Scheduler operations."""

    def validate(
        self, expression: str, timezone: str = "Europe/Moscow", preview_count: int = 5
    ) -> dict[str, Any]:
        """POST /api/v1/admin/cron/validate — валидировать cron-выражение."""
        try:
            return self.post(
                "/api/v1/admin/cron/validate",
                json={
                    "expression": expression,
                    "timezone": timezone,
                    "preview_count": preview_count,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return {"is_valid": False, "error": str(exc)}

    def schedule(
        self,
        name: str,
        cron_expr: str,
        *,
        timezone: str = "Europe/Moscow",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST /api/v1/admin/cron/schedule — зарегистрировать scheduled job."""
        body: dict[str, Any] = {
            "name": name,
            "cron_expr": cron_expr,
            "timezone": timezone,
        }
        if payload:
            body["payload"] = payload
        try:
            return self.post("/api/v1/admin/cron/schedule", json=body)
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    def list_schedules(
        self, *, tenant_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """GET /api/v1/admin/cron/schedules — список scheduled jobs."""
        params: dict[str, Any] = {"limit": limit}
        if tenant_id:
            params["tenant_id"] = tenant_id
        try:
            result = self.get("/api/v1/admin/cron/schedules", params=params)
            return result if isinstance(result, list) else []
        except Exception as _:  # noqa: BLE001
            return []

    def pause_schedule(self, id: str, *, tenant_id: str | None = None) -> bool:
        """POST /api/v1/admin/cron/{id}/pause."""
        params: dict[str, Any] = {}
        if tenant_id:
            params["tenant_id"] = tenant_id
        try:
            self.post(f"/api/v1/admin/cron/{id}/pause", params=params)
            return True
        except Exception as _:  # noqa: BLE001
            return False

    def resume_schedule(self, id: str, *, tenant_id: str | None = None) -> bool:
        """POST /api/v1/admin/cron/{id}/resume."""
        params: dict[str, Any] = {}
        if tenant_id:
            params["tenant_id"] = tenant_id
        try:
            self.post(f"/api/v1/admin/cron/{id}/resume", params=params)
            return True
        except Exception as _:  # noqa: BLE001
            return False

    def run_now(self, id: str, *, tenant_id: str | None = None) -> bool:
        """POST /api/v1/admin/cron/{id}/run-now."""
        params: dict[str, Any] = {}
        if tenant_id:
            params["tenant_id"] = tenant_id
        try:
            self.post(f"/api/v1/admin/cron/{id}/run-now", params=params)
            return True
        except Exception as _:  # noqa: BLE001
            return False

    def delete_schedule(self, id: str, *, tenant_id: str | None = None) -> bool:
        """DELETE /api/v1/admin/cron/{id}."""
        params: dict[str, Any] = {}
        if tenant_id:
            params["tenant_id"] = tenant_id
        try:
            self.delete(f"/api/v1/admin/cron/{id}", params=params)
            return True
        except Exception as _:  # noqa: BLE001
            return False
