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
        return self._request("GET", "/api/v1/orders/all/", params={"page": page, "size": size})

    def create_order(self, data: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/orders/create/", json=data)

    def update_order(self, order_id: int, data: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"/api/v1/orders/update/{order_id}", json=data)

    def delete_order(self, order_id: int) -> None:
        self._request("DELETE", f"/api/v1/orders/delete/{order_id}")

    def chat(self, message: str, session_id: str = "default") -> str:
        result = self._request(
            "POST", "/api/v1/ai/chat",
            json={"message": message, "session_id": session_id},
        )
        return result.get("response", str(result)) if isinstance(result, dict) else str(result)

    def get_flags(self) -> list[dict[str, Any]]:
        try:
            return self._request("GET", "/api/v1/admin/feature-flags")
        except Exception:
            return []

    def toggle_flag(self, name: str, enabled: bool) -> bool:
        try:
            self._request(
                "POST", f"/api/v1/admin/feature-flags/{name}/toggle",
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
            return self._request("GET", "/api/v1/admin/trace-logs", params={"limit": limit})
        except Exception:
            return []


def get_api_client() -> APIClient:
    return APIClient()
