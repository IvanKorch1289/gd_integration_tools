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




# ── convert tools (_register_convert_tools) ──

def _register_convert_tools(mcp: Any) -> None:
    """Tools для конвертации форматов данных."""

    @mcp.tool(
        name="convert_format",
        description="Конвертирует данные между форматами: json, yaml, xml, csv, msgpack, bson. "
        "Пример: from_format='json', to_format='yaml', data='{\"key\": \"value\"}'",
    )
    async def convert_format(from_format: str, to_format: str, data: str) -> str:
        from src.backend.dsl.engine.processors.converters import _STRATEGIES

        key = f"{from_format}→{to_format}"
        strategy = _STRATEGIES.get(key)
        if not strategy:
            available = list(_STRATEGIES.keys())
            return encode_json(
                {"error": f"No converter for {key}", "available": available}
            ).decode("utf-8")

        try:
            input_data: Any = data
            if from_format in ("json", "dict"):
                try:
                    input_data = orjson.loads(data)
                except (orjson.JSONDecodeError, TypeError):
                    pass

            result = strategy.convert(input_data)

            if isinstance(result, bytes):
                import base64

                return encode_json(
                    {
                        "format": to_format,
                        "encoding": "base64",
                        "data": base64.b64encode(result).decode("utf-8"),
                    }
                ).decode("utf-8")

            if isinstance(result, str):
                return result

            return encode_json(result).decode("utf-8")
        except Exception as exc:
            return encode_json({"error": str(exc)}).decode("utf-8")

    @mcp.tool(
        name="convert_list_formats",
        description="Показывает все доступные конвертации форматов (from→to пары).",
    )
    async def convert_list_formats() -> str:
        from src.backend.dsl.engine.processors.converters import _STRATEGIES

        return encode_json(list(_STRATEGIES.keys())).decode("utf-8")

