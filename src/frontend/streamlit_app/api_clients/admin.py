"""Admin API клиент."""

from __future__ import annotations

from typing import Any

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient

__all__ = ("AdminClient",)


class AdminClient(BaseAPIClient):
    """Клиент для Admin operations (config, metrics, feature-flags, etc.)."""

    def get_metrics(self) -> dict[str, Any]:
        """GET /api/v1/admin/metrics."""
        return self.get("/api/v1/admin/metrics")

    def get_health(self) -> dict[str, Any]:
        """GET /api/v1/health/components."""
        return self.get("/api/v1/health/components")

    def get_flags(self) -> list[dict[str, Any]]:
        """GET /api/v1/admin/feature-flags."""
        try:
            return self.get("/api/v1/admin/feature-flags")
        except Exception:  # noqa: BLE001
            return []

    def toggle_flag(self, name: str, enabled: bool) -> bool:
        """POST /api/v1/admin/feature-flags/{name}/toggle."""
        try:
            self.post(
                f"/api/v1/admin/feature-flags/{name}/toggle",
                json={"enabled": enabled},
            )
            return True
        except Exception:  # noqa: BLE001
            return False

    def set_override(
        self, flag: str, value: Any, tenant_id: str | None = None, actor: str = "ui"
    ) -> dict[str, Any] | None:
        """PUT /api/v1/admin/feature-flags/{flag} — установить runtime override."""
        try:
            return self.put(
                f"/api/v1/admin/feature-flags/{flag}",
                json={"value": value, "tenant_id": tenant_id, "actor": actor},
            )
        except Exception:  # noqa: BLE001
            return None

    def clear_override(
        self, flag: str, tenant_id: str | None = None, actor: str = "ui"
    ) -> dict[str, Any] | None:
        """DELETE /api/v1/admin/feature-flags/{flag} — снять runtime override."""
        try:
            params: dict[str, Any] = {"actor": actor}
            if tenant_id is not None:
                params["tenant_id"] = tenant_id
            return self.delete(f"/api/v1/admin/feature-flags/{flag}", params=params)
        except Exception:  # noqa: BLE001
            return None

    def get_config(self) -> dict[str, Any]:
        """GET /api/v1/admin/config."""
        try:
            return self.get("/api/v1/admin/config")
        except Exception:  # noqa: BLE001
            return {}

    def get_trace_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        """GET /api/v1/admin/trace-logs."""
        try:
            result = self.get("/api/v1/admin/trace-logs", params={"limit": limit})
            return result if isinstance(result, list) else []
        except Exception:  # noqa: BLE001
            return []

    def get_ready(self) -> dict[str, Any]:
        """GET /ready — агрегированный health status всех подсистем."""
        try:
            return self.get("/ready")
        except Exception:  # noqa: BLE001
            return {"status": "error", "components": {}}

    def get_capability_catalog(self) -> dict[str, Any]:
        """GET /api/v1/admin/capabilities."""
        try:
            return self.get("/api/v1/admin/capabilities")
        except Exception as exc:  # noqa: BLE001
            return {"vocabulary": [], "catalog": [], "error": str(exc)}

    def get_processor_catalog(
        self, query: str = "", namespace: str | None = None, limit: int = 25
    ) -> dict[str, Any]:
        """GET /api/v1/dsl/processors/search."""
        params: dict[str, Any] = {"q": query, "limit": limit}
        if namespace:
            params["namespace"] = namespace
        try:
            return self.get("/api/v1/dsl/processors/search", params=params)
        except Exception as exc:  # noqa: BLE001
            return {"query": query, "items": [], "total": 0, "error": str(exc)}

    def get_audit_events(
        self, plugin: str | None = None, tenant: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """GET /api/v1/admin/audit/capability."""
        params: dict[str, Any] = {"limit": limit}
        if plugin:
            params["plugin"] = plugin
        if tenant:
            params["tenant"] = tenant
        try:
            response = self.get("/api/v1/admin/audit/capability", params=params)
            if isinstance(response, list):
                return response
            return response.get("events", []) if isinstance(response, dict) else []
        except Exception:  # noqa: BLE001
            return []

    def get_dependency_graph(self) -> dict[str, Any]:
        """GET /api/v1/admin/plugins/dependency-graph."""
        try:
            return self.get("/api/v1/admin/plugins/dependency-graph")
        except Exception as exc:  # noqa: BLE001
            return {"nodes": [], "edges": [], "error": str(exc)}

    def get_capability_graph(self) -> dict[str, Any]:
        """GET /api/v1/admin/capabilities/graph."""
        try:
            return self.get("/api/v1/admin/capabilities/graph")
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
        """POST /api/v1/admin/plugins/scaffold."""
        body = {
            "name": name,
            "description": description,
            "capabilities": capabilities or [],
            "features": features or [],
            "dry_run": dry_run,
        }
        try:
            return self.post("/api/v1/admin/plugins/scaffold", json=body)
        except Exception as exc:  # noqa: BLE001
            return {"name": name, "created": False, "error": str(exc)}
