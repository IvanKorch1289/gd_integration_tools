"""MCP-сервер на базе FastMCP.

Автоматически экспортирует все зарегистрированные actions
из ActionHandlerRegistry как MCP tools. Дополнительно предоставляет
инструментальные tools для управления маршрутами, конвертации
форматов, шаблонов и мониторинга.

Категории tools:
- Action tools: автогенерация из ActionHandlerRegistry (50+)
- Route tools: list/execute/inspect DSL маршруты
- Template tools: list/instantiate шаблоны Pipeline
- Convert tools: конвертация форматов (JSON↔XML/YAML/CSV/MsgPack)
- System tools: health check, metrics, feature flags
"""

from typing import Any

import orjson

from src.backend.core.logging import get_logger
from src.backend.core.serialization.msgspec_hotpath import encode_json

logger = get_logger(__name__)


# ── route tools (_register_route_tools) ──


def _register_route_tools(mcp: Any) -> None:
    """Tools для управления DSL-маршрутами."""

    @mcp.tool(
        name="route_list",
        description="Список всех зарегистрированных DSL-маршрутов с описаниями и процессорами",
    )
    async def route_list() -> str:
        from src.backend.dsl.registry import route_registry

        routes = []
        for rid in route_registry.list_routes():
            pipeline = route_registry.get_optional(rid)
            if pipeline:
                routes.append(
                    {
                        "route_id": rid,
                        "source": pipeline.source,
                        "description": pipeline.description,
                        "processor_count": len(pipeline.processors),
                        "processors": [p.name for p in pipeline.processors],
                        "protocol": pipeline.protocol.value
                        if pipeline.protocol
                        else None,
                    }
                )
        return encode_json(routes).decode("utf-8")

    @mcp.tool(
        name="route_execute",
        description="Выполняет DSL-маршрут по route_id с указанным payload. Возвращает результат Exchange.",
    )
    async def route_execute(route_id: str, payload: str = "{}") -> str:
        from src.backend.dsl.engine.execution_engine import ExecutionEngine
        from src.backend.dsl.registry import route_registry

        try:
            pipeline = route_registry.get(route_id)
        except KeyError:
            return encode_json({"error": f"Route '{route_id}' not found"}).decode(
                "utf-8"
            )

        try:
            parsed = orjson.loads(payload) if payload else {}
        except (orjson.JSONDecodeError, TypeError):
            parsed = {"raw": payload}

        engine = ExecutionEngine()
        exchange = await engine.execute(pipeline, body=parsed)

        result = (
            exchange.out_message.body
            if exchange.out_message
            else exchange.in_message.body
        )
        return encode_json(
            {
                "status": exchange.status.value,
                "result": result,
                "error": exchange.error,
                "properties": {
                    k: v
                    for k, v in exchange.properties.items()
                    if not k.startswith("_")
                },
            }
        ).decode("utf-8")

    @mcp.tool(
        name="route_inspect",
        description="Детальная информация о DSL-маршруте: процессоры, pipeline metadata, feature flags.",
    )
    async def route_inspect(route_id: str) -> str:
        from src.backend.dsl.registry import route_registry

        pipeline = route_registry.get_optional(route_id)
        if not pipeline:
            return encode_json({"error": f"Route '{route_id}' not found"}).decode(
                "utf-8"
            )

        return encode_json(
            {
                "route_id": pipeline.route_id,
                "source": pipeline.source,
                "description": pipeline.description,
                "protocol": pipeline.protocol.value if pipeline.protocol else None,
                "feature_flag": pipeline.feature_flag,
                "processors": [
                    {"name": p.name, "type": type(p).__name__}
                    for p in pipeline.processors
                ],
            }
        ).decode("utf-8")
