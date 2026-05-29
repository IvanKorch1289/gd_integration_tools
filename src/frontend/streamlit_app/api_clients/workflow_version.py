"""Workflow Versioning API клиент."""

from __future__ import annotations

from typing import Any

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient

__all__ = ("WorkflowVersionClient",)


class WorkflowVersionClient(BaseAPIClient):
    """Клиент для Workflow Versioning operations."""

    def pin_version(self, workflow_id: str, semver: str) -> dict[str, Any] | None:
        """POST /api/v1/admin/workflow-versioning/{id}/pin."""
        try:
            return self.post(
                f"/api/v1/admin/workflow-versioning/{workflow_id}/pin",
                params={"semver": semver},
            )
        except Exception as _:  # noqa: BLE001
            return None

    def rollback(self, workflow_id: str) -> dict[str, Any] | None:
        """POST /api/v1/admin/workflow-versioning/{id}/rollback."""
        try:
            return self.post(
                f"/api/v1/admin/workflow-versioning/{workflow_id}/rollback"
            )
        except Exception as _:  # noqa: BLE001
            return None

    def get_running_count(self, workflow_id: str) -> dict[str, Any]:
        """GET /api/v1/admin/workflow-versioning/{id}/running-count."""
        try:
            return self.get(
                f"/api/v1/admin/workflow-versioning/{workflow_id}/running-count"
            )
        except Exception as _:  # noqa: BLE001
            return {"counts": {}}
