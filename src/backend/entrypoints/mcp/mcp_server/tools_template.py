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




# ── template tools (_register_template_tools) ──

def _register_template_tools(mcp: Any) -> None:
    """Tools для работы с шаблонами Pipeline."""

    @mcp.tool(
        name="template_list",
        description="Список всех доступных шаблонов DSL Pipeline с параметрами. "
        "Шаблоны — готовые паттерны для типовых задач (ETL, scraping, AI Q&A, CRUD и т.д.).",
    )
    async def template_list() -> str:
        from src.backend.dsl.templates_library import list_templates

        return encode_json(list_templates()).decode("utf-8")

    @mcp.tool(
        name="template_instantiate",
        description="Создаёт Pipeline из шаблона с указанными параметрами. "
        'Пример: template_id=\'etl.postgres_to_clickhouse\', params=\'{"source_query": "SELECT...", "target_table": "analytics.orders"}\'',
    )
    async def template_instantiate(template_id: str, params: str = "{}") -> str:
        from src.backend.dsl.templates_library import templates

        tmpl = templates.get(template_id)
        if not tmpl:
            return encode_json({"error": f"Template '{template_id}' not found"}).decode(
                "utf-8"
            )

        try:
            parsed_params = orjson.loads(params) if params else {}
        except (orjson.JSONDecodeError, TypeError):
            return encode_json({"error": "Invalid JSON params"}).decode("utf-8")

        try:
            result = tmpl.builder(**parsed_params)
            if isinstance(result, list):
                return encode_json(
                    {
                        "status": "ok",
                        "pipelines": [
                            {"route_id": p.route_id, "processors": len(p.processors)}
                            for p in result
                        ],
                    }
                ).decode("utf-8")
            return encode_json(
                {
                    "status": "ok",
                    "route_id": result.route_id,
                    "processors": len(result.processors),
                    "processor_names": [p.name for p in result.processors],
                }
            ).decode("utf-8")
        except Exception as exc:
            return encode_json({"error": str(exc)}).decode("utf-8")

    @mcp.tool(
        name="macro_list",
        description="Список всех DSL-макросов (pre-built pipeline patterns). "
        "Макросы — функции для создания типовых интеграционных pipelines.",
    )
    async def macro_list() -> str:
        import inspect

        from src.backend.dsl import macros

        result = []
        for name in macros.__all__:
            fn = getattr(macros, name, None)
            if fn and callable(fn):
                sig = inspect.signature(fn)
                result.append(
                    {
                        "name": name,
                        "doc": (fn.__doc__ or "").split("\n")[0],
                        "parameters": [
                            {
                                "name": p.name,
                                "default": str(p.default)
                                if p.default != inspect.Parameter.empty
                                else None,
                            }
                            for p in sig.parameters.values()
                        ],
                    }
                )
        return encode_json(result).decode("utf-8")

