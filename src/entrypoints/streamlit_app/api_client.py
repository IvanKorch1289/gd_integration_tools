"""HTTP-клиент для вызова FastAPI backend из Streamlit."""

from __future__ import annotations

import os
from typing import Any

import httpx

__all__ = ("APIClient", "get_api_client")

_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")


class APIClient:
    """Синхронный HTTP-клиент к FastAPI."""

    def __init__(self, base_url: str = _BASE_URL) -> None:
        self._base_url = base_url.rstrip("/")

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        with httpx.Client(timeout=15) as client:
            response = client.request(method, self._url(path), **kwargs)
            response.raise_for_status()
            if response.headers.get("content-type", "").startswith("application/json"):
                return response.json()
            return response.text

    def get_metrics(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/admin/metrics")

    def get_health(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/health/components")

    def get_routes(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/v1/admin/routes")

    def get_orders(self, page: int = 1, size: int = 50) -> Any:
        return self._request(
            "GET", "/api/v1/orders/all/", params={"page": page, "size": size}
        )

    def create_order(self, data: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/orders/create/", json=data)

    def update_order(self, order_id: int, data: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"/api/v1/orders/update/{order_id}", json=data)

    def delete_order(self, order_id: int) -> None:
        self._request("DELETE", f"/api/v1/orders/delete/{order_id}")

    def chat(self, message: str, session_id: str = "default") -> str:
        result = self._request(
            "POST",
            "/api/v1/ai/chat",
            json={"message": message, "session_id": session_id},
        )
        return (
            result.get("response", str(result))
            if isinstance(result, dict)
            else str(result)
        )

    def get_flags(self) -> list[dict[str, Any]]:
        try:
            return self._request("GET", "/api/v1/admin/feature-flags")
        except Exception:
            return []

    def toggle_flag(self, name: str, enabled: bool) -> bool:
        try:
            self._request(
                "POST",
                f"/api/v1/admin/feature-flags/{name}/toggle",
                json={"enabled": enabled},
            )
            return True
        except Exception:
            return False

    def get_config(self) -> dict[str, Any]:
        try:
            return self._request("GET", "/api/v1/admin/config")
        except Exception:
            return {}

    def get_trace_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        try:
            return self._request(
                "GET", "/api/v1/admin/trace-logs", params={"limit": limit}
            )
        except Exception:
            return []

    # -- Durable workflows (IL-WF1.5 admin API) -------------------------

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
        except Exception:
            return []

    def get_workflow(self, instance_id: str) -> dict[str, Any] | None:
        """GET /api/v1/admin/workflows/{id} — header + event log."""
        try:
            return self._request("GET", f"/api/v1/admin/workflows/{instance_id}")
        except Exception:
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
        except Exception:
            return []

    def retry_workflow(self, instance_id: str) -> bool:
        """POST /{id}/retry — next_attempt_at=now."""
        try:
            self._request("POST", f"/api/v1/admin/workflows/{instance_id}/retry")
            return True
        except Exception:
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
        except Exception:
            return False

    def resume_workflow(self, instance_id: str) -> bool:
        """POST /{id}/resume — для paused: немедленно execute."""
        try:
            self._request("POST", f"/api/v1/admin/workflows/{instance_id}/resume")
            return True
        except Exception:
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
        except Exception:
            return None

    # ──────────── AI Feedback ────────────

    def list_feedback_pending(
        self, *, agent_id: str | None = None, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """GET /api/v1/ai/feedback/pending."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if agent_id:
            params["agent_id"] = agent_id
        return self._request("GET", "/api/v1/ai/feedback/pending", params=params)

    def list_feedback_labeled(
        self,
        *,
        label: str | None = None,
        agent_id: str | None = None,
        indexed_in_rag: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """GET /api/v1/ai/feedback/labeled."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if label:
            params["label"] = label
        if agent_id:
            params["agent_id"] = agent_id
        if indexed_in_rag is not None:
            params["indexed_in_rag"] = str(indexed_in_rag).lower()
        return self._request("GET", "/api/v1/ai/feedback/labeled", params=params)

    def get_feedback_stats(self) -> dict[str, int]:
        """GET /api/v1/ai/feedback/stats."""
        return self._request("GET", "/api/v1/ai/feedback/stats")

    def label_feedback(
        self,
        doc_id: str,
        *,
        label: str,
        comment: str | None = None,
        operator_id: str | None = None,
    ) -> dict[str, Any]:
        """POST /api/v1/ai/feedback/{id}/label."""
        payload: dict[str, Any] = {"label": label}
        if comment:
            payload["comment"] = comment
        if operator_id:
            payload["operator_id"] = operator_id
        return self._request(
            "POST", f"/api/v1/ai/feedback/{doc_id}/label", json=payload
        )

    def index_feedback_to_rag(
        self, *, agent_id: str | None = None, limit: int = 100
    ) -> dict[str, int]:
        """POST /api/v1/ai/feedback/index-to-rag."""
        payload: dict[str, Any] = {"limit": limit}
        if agent_id:
            payload["agent_id"] = agent_id
        return self._request("POST", "/api/v1/ai/feedback/index-to-rag", json=payload)


def get_api_client() -> APIClient:
    return APIClient()
