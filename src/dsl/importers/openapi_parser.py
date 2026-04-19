"""OpenAPI → DSL Auto-Generator.

Загружает OpenAPI 3.x spec → генерирует DSL RouteBuilder код для каждой операции.
70% быстрее ручной интеграции REST API.

Actions: openapi.import, openapi.preview, openapi.list_imported
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.core.decorators.singleton import singleton

__all__ = ("OpenAPIImporter", "ImportedRoute", "get_openapi_importer")

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ImportedRoute:
    route_id: str
    method: str
    path: str
    summary: str
    parameters: list[dict[str, Any]] = field(default_factory=list)
    request_body: dict[str, Any] | None = None
    response_schema: dict[str, Any] | None = None
    python_code: str = ""
    registered: bool = False


@singleton
class OpenAPIImporter:
    """Импортирует OpenAPI spec и генерирует DSL routes."""

    def __init__(self) -> None:
        self._imported: dict[str, list[ImportedRoute]] = {}

    async def import_spec(
        self, spec: dict[str, Any] | str, prefix: str = "ext"
    ) -> dict[str, Any]:
        """Импортирует OpenAPI spec (dict или URL).

        Args:
            spec: OpenAPI spec dict или URL для загрузки.
            prefix: Префикс для route_id (e.g., "ext" → "ext.get_users").

        Returns:
            Результат импорта: routes, errors.
        """
        if isinstance(spec, str):
            spec = await self._fetch_spec(spec)

        if not isinstance(spec, dict):
            return {"status": "error", "message": "Invalid spec format"}

        info = spec.get("info", {})
        title = info.get("title", "unknown")
        paths = spec.get("paths", {})

        routes: list[ImportedRoute] = []
        errors: list[str] = []

        for path, path_item in paths.items():
            for method in ("get", "post", "put", "patch", "delete"):
                operation = path_item.get(method)
                if not operation:
                    continue

                try:
                    route = self._build_route(prefix, method, path, operation)
                    routes.append(route)
                except Exception as exc:
                    errors.append(f"{method.upper()} {path}: {exc}")

        self._imported[title] = routes
        logger.info("Imported %d routes from '%s'", len(routes), title)

        return {
            "status": "imported",
            "title": title,
            "version": info.get("version", ""),
            "routes_count": len(routes),
            "errors": errors,
            "routes": [self._route_summary(r) for r in routes],
        }

    async def preview(self, spec: dict[str, Any] | str, prefix: str = "ext") -> dict[str, Any]:
        """Превью без регистрации — показывает что будет сгенерировано."""
        result = await self.import_spec(spec, prefix)
        if result.get("status") == "imported":
            title = result["title"]
            routes = self._imported.get(title, [])
            result["code_preview"] = [r.python_code for r in routes[:5]]
            del self._imported[title]
        return result

    async def list_imported(self) -> dict[str, Any]:
        """Список импортированных спецификаций."""
        return {
            title: {
                "count": len(routes),
                "routes": [self._route_summary(r) for r in routes],
            }
            for title, routes in self._imported.items()
        }

    async def register_routes(self, title: str) -> dict[str, Any]:
        """Регистрирует импортированные routes в route_registry."""
        routes = self._imported.get(title)
        if not routes:
            return {"status": "not_found", "title": title}

        registered = 0
        for route in routes:
            if route.registered:
                continue
            try:
                from app.dsl.commands.registry import route_registry
                exec_globals: dict[str, Any] = {}
                exec(route.python_code, exec_globals)
                build_fn = exec_globals.get("build_route")
                if build_fn:
                    pipeline = build_fn()
                    route_registry.register(pipeline)
                    route.registered = True
                    registered += 1
            except Exception as exc:
                logger.error("Failed to register %s: %s", route.route_id, exc)

        return {"status": "registered", "title": title, "registered": registered}

    def _build_route(
        self, prefix: str, method: str, path: str, operation: dict[str, Any]
    ) -> ImportedRoute:
        op_id = operation.get("operationId", "")
        if not op_id:
            op_id = f"{method}_{path.replace('/', '_').strip('_')}"
        route_id = f"{prefix}.{op_id}"
        summary = operation.get("summary", "")
        parameters = operation.get("parameters", [])
        request_body = operation.get("requestBody")
        responses = operation.get("responses", {})

        resp_200 = responses.get("200", responses.get("201", {}))
        response_schema = None
        if resp_200:
            content = resp_200.get("content", {})
            json_content = content.get("application/json", {})
            response_schema = json_content.get("schema")

        action_name = f"{prefix}.{op_id}"
        code = self._generate_code(route_id, method, path, summary, action_name)

        return ImportedRoute(
            route_id=route_id,
            method=method.upper(),
            path=path,
            summary=summary,
            parameters=parameters,
            request_body=request_body,
            response_schema=response_schema,
            python_code=code,
        )

    @staticmethod
    def _generate_code(route_id: str, method: str, path: str, summary: str, action: str) -> str:
        return (
            f'def build_route():\n'
            f'    from app.dsl.builder import RouteBuilder\n'
            f'    return (\n'
            f'        RouteBuilder.from_("{route_id}", source="http:{method.upper()}:{path}")\n'
            f'        .dispatch_action("{action}")\n'
            f'        .log()\n'
            f'        .build()\n'
            f'    )\n'
        )

    @staticmethod
    def _route_summary(route: ImportedRoute) -> dict[str, Any]:
        return {
            "route_id": route.route_id,
            "method": route.method,
            "path": route.path,
            "summary": route.summary,
            "registered": route.registered,
        }

    @staticmethod
    async def _fetch_spec(url: str) -> dict[str, Any]:
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()


def get_openapi_importer() -> OpenAPIImporter:
    return OpenAPIImporter()
