"""Route/DSL API клиент."""

from __future__ import annotations

from typing import Any

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient

__all__ = ("RouteClient",)


class RouteClient(BaseAPIClient):
    """Клиент для Route/DSL operations."""

    def list_dsl_routes(self) -> list[str]:
        """GET /api/v1/admin/dsl-routes — список route_id."""
        try:
            result = self.get("/api/v1/admin/dsl-routes")
            return result if isinstance(result, list) else []
        except Exception:  # noqa: BLE001
            return []

    def get_dsl_route(self, route_id: str) -> dict[str, Any] | None:
        """GET /api/v1/admin/dsl-routes/{id} — yaml + spec + python."""
        try:
            return self.get(f"/api/v1/admin/dsl-routes/{route_id}")
        except Exception:  # noqa: BLE001
            return None

    def create_dsl_route(self, yaml_str: str) -> dict[str, Any]:
        """POST /api/v1/admin/dsl-routes — создать маршрут."""
        return self.post("/api/v1/admin/dsl-routes", json={"yaml": yaml_str})

    def update_dsl_route(self, route_id: str, yaml_str: str) -> dict[str, Any]:
        """PUT /api/v1/admin/dsl-routes/{id} — обновить маршрут."""
        return self.put(
            f"/api/v1/admin/dsl-routes/{route_id}", json={"yaml": yaml_str}
        )

    def delete_dsl_route(self, route_id: str) -> bool:
        """DELETE /api/v1/admin/dsl-routes/{id} — удалить маршрут."""
        try:
            self.delete(f"/api/v1/admin/dsl-routes/{route_id}")
            return True
        except Exception:  # noqa: BLE001
            return False

    def validate_dsl_route(self, yaml_str: str) -> dict[str, Any]:
        """POST /api/v1/admin/dsl-routes/validate — валидация без записи."""
        try:
            return self.post(
                "/api/v1/admin/dsl-routes/validate", json={"yaml": yaml_str}
            )
        except Exception as exc:  # noqa: BLE001
            return {"valid": False, "error": str(exc)}

    def diff_dsl_route(self, route_id: str, yaml_str: str) -> dict[str, Any] | None:
        """POST /api/v1/admin/dsl-routes/{id}/diff — diff с переданным YAML."""
        try:
            return self.post(
                f"/api/v1/admin/dsl-routes/{route_id}/diff",
                json={"yaml": yaml_str},
            )
        except Exception:  # noqa: BLE001
            return None

    def get_routes(self) -> list[dict[str, Any]]:
        """GET /api/v1/admin/routes — список маршрутов."""
        return self.get("/api/v1/admin/routes")
