"""Capability catalog: catalog + processors + audit + graphs + scaffold (Sprint 14)."""

from __future__ import annotations

from typing import Any

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient

__all__ = ("CapabilityClient",)


class CapabilityClient(BaseAPIClient):
    """Клиент для capability catalog + plugin ecosystem (Sprint 14)."""

    def get_capability_catalog(self) -> dict[str, Any]:
        """Sprint 14 K1 W4 / pre-K5 — GET /api/v1/admin/capabilities."""
        try:
            return self._request("GET", "/api/v1/admin/capabilities")
        except Exception as exc:  # noqa: BLE001
            return {"vocabulary": [], "catalog": [], "error": str(exc)}

    def get_processor_catalog(
        self, query: str = "", namespace: str | None = None, limit: int = 25
    ) -> dict[str, Any]:
        """Sprint 14 K3 W1: GET /api/v1/dsl/processors/search."""
        params: dict[str, Any] = {"q": query, "limit": limit}
        if namespace:
            params["namespace"] = namespace
        try:
            return self._request("GET", "/api/v1/dsl/processors/search", params=params)
        except Exception as exc:  # noqa: BLE001
            return {"query": query, "items": [], "total": 0, "error": str(exc)}

    def get_audit_events(
        self, plugin: str | None = None, tenant: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Sprint 14 K1 W4: GET /api/v1/admin/audit/capability."""
        params: dict[str, Any] = {"limit": limit}
        if plugin:
            params["plugin"] = plugin
        if tenant:
            params["tenant"] = tenant
        try:
            response = self._request(
                "GET", "/api/v1/admin/audit/capability", params=params
            )
            if isinstance(response, list):
                return response
            return response.get("events", []) if isinstance(response, dict) else []
        except Exception:  # noqa: BLE001
            return []

    def get_dependency_graph(self) -> dict[str, Any]:
        """Sprint 14 K5 W3: GET /api/v1/admin/plugins/dependency-graph."""
        try:
            return self._request("GET", "/api/v1/admin/plugins/dependency-graph")
        except Exception as exc:  # noqa: BLE001
            return {"nodes": [], "edges": [], "error": str(exc)}

    def get_capability_graph(self) -> dict[str, Any]:
        """Sprint 14 K5 W5: GET /api/v1/admin/capabilities/graph."""
        try:
            return self._request("GET", "/api/v1/admin/capabilities/graph")
        except Exception as exc:  # noqa: BLE001
            return {"nodes": [], "edges": [], "error": str(exc)}

    def scaffold_plugin(
        self,
        name: str,
        *,
        description: str | None = None,
        capabilities: list[str] | None = None,
        features: list[str] | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Sprint 14 K5 W6: POST /api/v1/admin/plugins/scaffold."""
        body = {
            "name": name,
            "description": description,
            "capabilities": capabilities or [],
            "features": features or [],
            "dry_run": dry_run,
        }
        try:
            return self._request("POST", "/api/v1/admin/plugins/scaffold", json=body)
        except Exception as exc:  # noqa: BLE001
            return {"name": name, "created": False, "error": str(exc)}
