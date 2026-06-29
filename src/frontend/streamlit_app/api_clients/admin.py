"""Admin API клиент.

Sprint 46 W4: refactor — AdminClient теперь composition facade
над domain clients (FlagsClient, MetricsClient, ConfigClient) +
admin-only methods inline. Удалено 8 дублирующихся методов (50% от
общего объёма AdminClient). Публичный API НЕ изменился — все 16
методов остались на месте, но 8 теперь thin delegations.

Преимущества:
- Нет дублирования — single source of truth для каждой операции.
- Retry policy, jitter, auth — унаследованы от domain clients.
- Изменения в FlagsClient автоматически применяются в AdminClient.
"""

from __future__ import annotations

from typing import Any

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient
from src.frontend.streamlit_app.api_clients.config import ConfigClient
from src.frontend.streamlit_app.api_clients.flags import FlagsClient
from src.frontend.streamlit_app.api_clients.metrics import MetricsClient

__all__ = ("AdminClient",)


class AdminClient(BaseAPIClient):
    """Facade для admin operations: composition + admin-only methods.

    Delegated (FlagsClient / MetricsClient / ConfigClient):
        - get_metrics, get_health → MetricsClient
        - get_flags, toggle_flag, set_override, clear_override → FlagsClient
        - get_config, get_trace_logs → ConfigClient

    Admin-only (inline):
        - get_ready, get_capability_catalog, get_processor_catalog,
          get_audit_events, get_dependency_graph, get_capability_graph,
          scaffold_plugin, get_langgraph_sessions
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # Composition: каждый domain client использует тот же base_url,
        # token, max_retries, retry_overrides, jitter_ratio.
        self._flags = FlagsClient(**kwargs)
        self._metrics = MetricsClient(**kwargs)
        self._config = ConfigClient(**kwargs)

    # ============================================================
    # Delegated methods (FlagsClient)
    # ============================================================

    def get_flags(self) -> list[dict[str, Any]]:
        """GET /api/v1/admin/feature-flags."""
        return self._flags.get_flags()

    def toggle_flag(self, name: str, enabled: bool) -> bool:
        """POST /api/v1/admin/feature-flags/{name}/toggle."""
        return self._flags.toggle_flag(name, enabled)

    def set_override(
        self, flag: str, value: Any, tenant_id: str | None = None, actor: str = "ui"
    ) -> dict[str, Any] | None:
        """PUT /api/v1/admin/feature-flags/{flag} — установить runtime override."""
        return self._flags.set_override(flag, value, tenant_id=tenant_id, actor=actor)

    def clear_override(
        self, flag: str, tenant_id: str | None = None, actor: str = "ui"
    ) -> dict[str, Any] | None:
        """DELETE /api/v1/admin/feature-flags/{flag} — снять runtime override."""
        return self._flags.clear_override(flag, tenant_id=tenant_id, actor=actor)

    # ============================================================
    # Delegated methods (MetricsClient)
    # ============================================================

    def get_metrics(self) -> dict[str, Any]:
        """GET /api/v1/admin/metrics."""
        return self._metrics.get_metrics()

    def get_health(self) -> dict[str, Any]:
        """GET /api/v1/health/components."""
        return self._metrics.get_health()

    # ============================================================
    # Delegated methods (ConfigClient)
    # ============================================================

    def get_config(self) -> dict[str, Any]:
        """GET /api/v1/admin/config."""
        return self._config.get_config()

    def get_trace_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        """GET /api/v1/admin/trace-logs."""
        return self._config.get_trace_logs(limit=limit)

    # ============================================================
    # Admin-only methods (inline — нет дублей в domain clients)
    # ============================================================

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

    def get_langgraph_sessions(
        self, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """GET /api/v1/admin/langgraph/checkpoints — список активных
LangGraph сессий."""
        try:
            return self.get(
                "/api/v1/admin/langgraph/checkpoints",
                params={"limit": limit, "offset": offset},
            )
        except Exception as exc:  # noqa: BLE001
            return {"sessions": [], "count": 0, "error": str(exc)}
