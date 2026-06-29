"""Durable workflows: admin/workflows
(list, detail, events, retry, cancel, resume, trigger)."""

from __future__ import annotations

from typing import Any

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient

__all__ = ("WorkflowsClient",)


class WorkflowsClient(BaseAPIClient):
    """Клиент для admin/workflows endpoints (IL-WF1.5 admin API)."""

    def list_workflows(
        self,
        *,
        status: str | None = None,
        workflow_name: str | None = None,
        tenant_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """GET /api/v1/admin/workflows — список instances с фильтрами."""
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        if workflow_name:
            params["workflow_name"] = workflow_name
        if tenant_id:
            params["tenant_id"] = tenant_id
        try:
            result = self._request("GET", "/api/v1/admin/workflows", params=params)
            return result if isinstance(result, list) else []
        except Exception:  # noqa: BLE001
            return []

    def get_workflow(self, instance_id: str) -> dict[str, Any] | None:
        """GET /api/v1/admin/workflows/{id} — header + event log."""
        try:
            return self._request("GET", f"/api/v1/admin/workflows/{instance_id}")
        except Exception:  # noqa: BLE001
            return None

    def get_workflow_events(
        self, instance_id: str, *, after_seq: int = 0, limit: int = 200
    ) -> list[dict[str, Any]]:
        """GET /api/v1/admin/workflows/{id}/events — paginated event log."""
        try:
            result = self._request(
                "GET",
                f"/api/v1/admin/workflows/{instance_id}/events",
                params={"after_seq": after_seq, "limit": limit},
            )
            return result if isinstance(result, list) else []
        except Exception:  # noqa: BLE001
            return []

    def retry_workflow(self, instance_id: str) -> bool:
        """POST /{id}/retry — next_attempt_at=now."""
        try:
            self._request("POST", f"/api/v1/admin/workflows/{instance_id}/retry")
            return True
        except Exception:  # noqa: BLE001
            return False

    def cancel_workflow(self, instance_id: str, reason: str | None = None) -> bool:
        """POST /{id}/cancel — → compensate → cancelled."""
        try:
            self._request(
                "POST",
                f"/api/v1/admin/workflows/{instance_id}/cancel",
                json={"reason": reason} if reason else {},
            )
            return True
        except Exception:  # noqa: BLE001
            return False

    def resume_workflow(self, instance_id: str) -> bool:
        """POST /{id}/resume — для paused: немедленно execute."""
        try:
            self._request("POST", f"/api/v1/admin/workflows/{instance_id}/resume")
            return True
        except Exception:  # noqa: BLE001
            return False

    def trigger_workflow(
        self,
        workflow_name: str,
        payload: dict[str, Any],
        *,
        wait: bool = False,
        timeout_s: int = 30,
    ) -> dict[str, Any] | None:
        """POST /trigger/{name} — создать workflow instance."""
        try:
            return self._request(
                "POST",
                f"/api/v1/admin/workflows/trigger/{workflow_name}",
                json=payload,
                params={"wait": str(wait).lower(), "timeout_s": timeout_s},
            )
        except Exception:  # noqa: BLE001
            return None

    def get_saga_history(
        self, workflow_id: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        """GET /api/v1/admin/workflows/{id}/saga-history — compensation timeline.

        P6 thin-client миграция: вызывает HTTP endpoint вместо прямого импорта
        ``workflows.saga_history.get_saga_history``.
        """
        try:
            result = self._request(
                "GET",
                f"/api/v1/admin/workflows/{workflow_id}/saga-history",
                params={"limit": limit},
            )
            return result if isinstance(result, list) else []
        except Exception:  # noqa: BLE001
            return []
