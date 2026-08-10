"""DSL Routes Store: CRUD + validate + diff (Wave 3.8)."""

from __future__ import annotations

from typing import Any

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient

__all__ = ("DSLRoutesClient",)


class DSLRoutesClient(BaseAPIClient):
    """Клиент для admin/dsl-routes endpoints (YAMLStore CRUD)."""

    def get_routes(self) -> list[dict[str, Any]]:
        """Метод get_routes (см. signature)."""
        return self._request("GET", "/api/v1/admin/routes")

    def list_dsl_routes(self) -> list[str]:
        """GET /api/v1/admin/dsl-routes — список route_id из YAMLStore."""
        try:
            result = self._request("GET", "/api/v1/admin/dsl-routes")
            return result if isinstance(result, list) else []
        except (ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError) as list_exc:  # noqa: BLE001
            # cycle-9/D-AUDIT-1066: narrow exceptions + observability.
            # ConnectionError/TimeoutError — server unreachable, RuntimeError
            # — API failure, ValueError — invalid response, TypeError —
            # wrong type.
            import logging
            logging.getLogger(__name__).debug(
                "streamlit_dsl_routes.list_failed",
                extra={"error": str(list_exc)},
            )
            return []

    def get_dsl_route(self, route_id: str) -> dict[str, Any] | None:
        """GET /api/v1/admin/dsl-routes/{id} — yaml + spec + python."""
        try:
            return self._request("GET", f"/api/v1/admin/dsl-routes/{route_id}")
        except (ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError) as get_exc:  # noqa: BLE001
            # cycle-9/D-AUDIT-1066: см. выше — mirror для get.
            import logging
            logging.getLogger(__name__).debug(
                "streamlit_dsl_routes.get_failed",
                extra={"route_id": route_id, "error": str(get_exc)},
            )
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
        except (ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError) as del_exc:  # noqa: BLE001
            # cycle-9/D-AUDIT-1071: narrow exceptions + observability.
            # ConnectionError/TimeoutError — server unreachable, RuntimeError
            # — API failure, ValueError — invalid response, TypeError —
            # wrong type.
            import logging
            logging.getLogger(__name__).debug(
                "streamlit_dsl_routes.delete_failed",
                extra={"route_id": route_id, "error": str(del_exc)},
            )
            return False

    def validate_dsl_route(self, yaml_str: str) -> dict[str, Any]:
        """POST /api/v1/admin/dsl-routes/validate — валидация без записи."""
        try:
            return self._request(
                "POST", "/api/v1/admin/dsl-routes/validate", json={"yaml": yaml_str}
            )
        except (ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError) as exc:  # noqa: BLE001
            return {"valid": False, "error": str(exc)}

    def diff_dsl_route(self, route_id: str, yaml_str: str) -> dict[str, Any] | None:
        """POST /api/v1/admin/dsl-routes/{id}/diff — diff с переданным YAML."""
        try:
            return self._request(
                "POST",
                f"/api/v1/admin/dsl-routes/{route_id}/diff",
                json={"yaml": yaml_str},
            )
        except (ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError) as diff_exc:  # noqa: BLE001
            # cycle-9/D-AUDIT-1071: см. выше — mirror для diff.
            import logging
            logging.getLogger(__name__).debug(
                "streamlit_dsl_routes.diff_failed",
                extra={"route_id": route_id, "error": str(diff_exc)},
            )
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
        except (ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError) as traces_exc:  # noqa: BLE001
            # cycle-9/D-AUDIT-1071: см. выше — mirror для traces.
            import logging
            logging.getLogger(__name__).debug(
                "streamlit_dsl_routes.traces_failed",
                extra={"route_id": route_id, "error": str(traces_exc)},
            )
            return []

    def execute_registered_route(
        self, route_id: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """POST /api/v1/dsl/execute-registered — выполнить зарегистрированный route.

        P6 thin-client миграция: вызывает HTTP endpoint вместо прямого импорта
        ``dsl_portal.builder_facade.execute_route``.
        """
        try:
            return self._request(
                "POST",
                "/api/v1/dsl/execute-registered",
                json={"route_id": route_id, "body": body or {}},
            )
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": str(exc), "body": None, "trace": []}

    def dry_run(
        self, route: dict[str, Any], sample_payload: Any = None, seed: int = 0
    ) -> dict[str, Any]:
        """POST /api/v1/dsl/dry-run — эмуляция выполнения route.

        P6 thin-client миграция: вызывает HTTP endpoint вместо прямого импорта
        ``dsl_portal.dry_run_route``.
        """
        try:
            return self._request(
                "POST",
                "/api/v1/dsl/dry-run",
                json={"route": route, "sample_payload": sample_payload, "seed": seed},
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "error": str(exc),
                "route_id": None,
                "total_ms": 0.0,
                "steps": [],
                "waterfall": [],
            }
