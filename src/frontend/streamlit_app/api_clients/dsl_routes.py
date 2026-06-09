"""DSL Routes Store: CRUD + validate + diff (Wave 3.8)."""

from __future__ import annotations

from typing import Any

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient

__all__ = ("DSLRoutesClient",)


class DSLRoutesClient(BaseAPIClient):
    """Клиент для admin/dsl-routes endpoints (YAMLStore CRUD)."""

    def get_routes(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/v1/admin/routes")

    def list_dsl_routes(self) -> list[str]:
        """GET /api/v1/admin/dsl-routes — список route_id из YAMLStore."""
        try:
            result = self._request("GET", "/api/v1/admin/dsl-routes")
            return result if isinstance(result, list) else []
        except Exception:  # noqa: BLE001
            return []

    def get_dsl_route(self, route_id: str) -> dict[str, Any] | None:
        """GET /api/v1/admin/dsl-routes/{id} — yaml + spec + python."""
        try:
            return self._request("GET", f"/api/v1/admin/dsl-routes/{route_id}")
        except Exception:  # noqa: BLE001
            return None

    def create_dsl_route(self, yaml_str: str) -> dict[str, Any]:
        """POST /api/v1/admin/dsl-routes — создать новый маршрут."""
        return self._request(
            "POST", "/api/v1/admin/dsl-routes", json={"yaml": yaml_str}
        )

    def update_dsl_route(self, route_id: str, yaml_str: str) -> dict[str, Any]:
        """PUT /api/v1/admin/dsl-routes/{id} — обновить маршрут."""
        return self._request(
            "PUT", f"/api/v1/admin/dsl-routes/{route_id}", json={"yaml": yaml_str}
        )

    def delete_dsl_route(self, route_id: str) -> bool:
        """DELETE /api/v1/admin/dsl-routes/{id} — удалить маршрут."""
        try:
            self._request("DELETE", f"/api/v1/admin/dsl-routes/{route_id}")
            return True
        except Exception:  # noqa: BLE001
            return False

    def validate_dsl_route(self, yaml_str: str) -> dict[str, Any]:
        """POST /api/v1/admin/dsl-routes/validate — валидация без записи."""
        try:
            return self._request(
                "POST", "/api/v1/admin/dsl-routes/validate", json={"yaml": yaml_str}
            )
        except Exception as exc:  # noqa: BLE001
            return {"valid": False, "error": str(exc)}

    def diff_dsl_route(self, route_id: str, yaml_str: str) -> dict[str, Any] | None:
        """POST /api/v1/admin/dsl-routes/{id}/diff — diff с переданным YAML."""
        try:
            return self._request(
                "POST",
                f"/api/v1/admin/dsl-routes/{route_id}/diff",
                json={"yaml": yaml_str},
            )
        except Exception:  # noqa: BLE001
            return None

    def get_dsl_route_traces(
        self, route_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """S44 W1: GET /admin/dsl-routes/{id}/traces — последние N trace events.

        Возвращает empty list если маршрут ещё не выполнялся или buffer
        пуст (post-restart). Persistent storage = TD-026 (S45+ D).
        """
        try:
            result = self._request(
                "GET",
                f"/api/v1/admin/dsl-routes/{route_id}/traces",
                params={"limit": limit},
            )
            return result if isinstance(result, list) else []
        except Exception:  # noqa: BLE001
            return []
