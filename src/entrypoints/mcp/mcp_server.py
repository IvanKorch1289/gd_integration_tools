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

import logging

import orjson
from typing import Any

__all__ = ("create_mcp_server", "register_mcp_tools")

logger = logging.getLogger(__name__)


def create_mcp_server() -> Any:
    """Создаёт и настраивает FastMCP-сервер.

    Returns:
        Экземпляр FastMCP.

    Raises:
        ImportError: Если fastmcp не установлен.
    """
    from fastmcp import FastMCP

    mcp = FastMCP(
        "GD Integration Tools",
        description="MCP-сервер интеграционной шины GD. "
        "Предоставляет бизнес-actions, управление маршрутами, "
        "конвертацию форматов, шаблоны и мониторинг.",
    )

    register_mcp_tools(mcp)
    _register_route_tools(mcp)
    _register_template_tools(mcp)
    _register_convert_tools(mcp)
    _register_system_tools(mcp)
    return mcp


def register_mcp_tools(mcp: Any) -> None:
    """Регистрирует все actions из ActionHandlerRegistry как MCP tools.

    Args:
        mcp: Экземпляр FastMCP.
    """
    from app.dsl.commands.registry import action_handler_registry

    for action_name in action_handler_registry.list_actions():
        _register_single_tool(mcp, action_name)

    logger.info(
        "Зарегистрировано %d action MCP tools",
        len(action_handler_registry.list_actions()),
    )


def _register_single_tool(mcp: Any, action_name: str) -> None:
    """Регистрирует один action как MCP tool."""
    from app.dsl.commands.registry import action_handler_registry
    from app.schemas.invocation import ActionCommandSchema

    @mcp.tool(
        name=action_name.replace(".", "_"),
        description=f"Выполняет action '{action_name}' через интеграционную шину",
    )
    async def tool_handler(
        payload: str = "{}",
        _action: str = action_name,
    ) -> str:
        try:
            parsed_payload = orjson.loads(payload) if payload else {}
        except (orjson.JSONDecodeError, TypeError):
            parsed_payload = {"raw": payload}

        command = ActionCommandSchema(
            action=_action,
            payload=parsed_payload,
            meta={"source": "mcp"},
        )

        try:
            result = await action_handler_registry.dispatch(command)
            if hasattr(result, "model_dump"):
                return orjson.dumps(result.model_dump(mode="json")).decode()
            return orjson.dumps(result).decode()
        except Exception as exc:
            return orjson.dumps({"error": str(exc)}).decode()


# ── Route Management Tools ──


def _register_route_tools(mcp: Any) -> None:
    """Tools для управления DSL-маршрутами."""

    @mcp.tool(
        name="route_list",
        description="Список всех зарегистрированных DSL-маршрутов с описаниями и процессорами",
    )
    async def route_list() -> str:
        from app.dsl.registry import route_registry
        routes = []
        for rid in route_registry.list_routes():
            pipeline = route_registry.get_optional(rid)
            if pipeline:
                routes.append({
                    "route_id": rid,
                    "source": pipeline.source,
                    "description": pipeline.description,
                    "processor_count": len(pipeline.processors),
                    "processors": [p.name for p in pipeline.processors],
                    "protocol": pipeline.protocol.value if pipeline.protocol else None,
                })
        return orjson.dumps(routes).decode()

    @mcp.tool(
        name="route_execute",
        description="Выполняет DSL-маршрут по route_id с указанным payload. Возвращает результат Exchange.",
    )
    async def route_execute(route_id: str, payload: str = "{}") -> str:
        from app.dsl.engine.execution_engine import ExecutionEngine
        from app.dsl.registry import route_registry

        try:
            pipeline = route_registry.get(route_id)
        except KeyError:
            return orjson.dumps({"error": f"Route '{route_id}' not found"}).decode()

        try:
            parsed = orjson.loads(payload) if payload else {}
        except (orjson.JSONDecodeError, TypeError):
            parsed = {"raw": payload}

        engine = ExecutionEngine()
        exchange = await engine.execute(pipeline, body=parsed)

        result = exchange.out_message.body if exchange.out_message else exchange.in_message.body
        return orjson.dumps({
            "status": exchange.status.value,
            "result": result,
            "error": exchange.error,
            "properties": {k: v for k, v in exchange.properties.items() if not k.startswith("_")},
        }, default=str).decode()

    @mcp.tool(
        name="route_inspect",
        description="Детальная информация о DSL-маршруте: процессоры, pipeline metadata, feature flags.",
    )
    async def route_inspect(route_id: str) -> str:
        from app.dsl.registry import route_registry

        pipeline = route_registry.get_optional(route_id)
        if not pipeline:
            return orjson.dumps({"error": f"Route '{route_id}' not found"}).decode()

        return orjson.dumps({
            "route_id": pipeline.route_id,
            "source": pipeline.source,
            "description": pipeline.description,
            "protocol": pipeline.protocol.value if pipeline.protocol else None,
            "feature_flag": pipeline.feature_flag,
            "processors": [
                {"name": p.name, "type": type(p).__name__}
                for p in pipeline.processors
            ],
        }).decode()


# ── Template Tools ──


def _register_template_tools(mcp: Any) -> None:
    """Tools для работы с шаблонами Pipeline."""

    @mcp.tool(
        name="template_list",
        description="Список всех доступных шаблонов DSL Pipeline с параметрами. "
        "Шаблоны — готовые паттерны для типовых задач (ETL, scraping, AI Q&A, CRUD и т.д.).",
    )
    async def template_list() -> str:
        from app.dsl.templates_library import list_templates
        return orjson.dumps(list_templates()).decode()

    @mcp.tool(
        name="template_instantiate",
        description="Создаёт Pipeline из шаблона с указанными параметрами. "
        "Пример: template_id='etl.postgres_to_clickhouse', params='{\"source_query\": \"SELECT...\", \"target_table\": \"analytics.orders\"}'",
    )
    async def template_instantiate(template_id: str, params: str = "{}") -> str:
        from app.dsl.templates_library import templates

        tmpl = templates.get(template_id)
        if not tmpl:
            return orjson.dumps({"error": f"Template '{template_id}' not found"}).decode()

        try:
            parsed_params = orjson.loads(params) if params else {}
        except (orjson.JSONDecodeError, TypeError):
            return orjson.dumps({"error": "Invalid JSON params"}).decode()

        try:
            result = tmpl.builder(**parsed_params)
            if isinstance(result, list):
                return orjson.dumps({
                    "status": "ok",
                    "pipelines": [
                        {"route_id": p.route_id, "processors": len(p.processors)}
                        for p in result
                    ],
                }).decode()
            return orjson.dumps({
                "status": "ok",
                "route_id": result.route_id,
                "processors": len(result.processors),
                "processor_names": [p.name for p in result.processors],
            }).decode()
        except Exception as exc:
            return orjson.dumps({"error": str(exc)}).decode()

    @mcp.tool(
        name="macro_list",
        description="Список всех DSL-макросов (pre-built pipeline patterns). "
        "Макросы — функции для создания типовых интеграционных pipelines.",
    )
    async def macro_list() -> str:
        from app.dsl import macros
        import inspect
        result = []
        for name in macros.__all__:
            fn = getattr(macros, name, None)
            if fn and callable(fn):
                sig = inspect.signature(fn)
                result.append({
                    "name": name,
                    "doc": (fn.__doc__ or "").split("\n")[0],
                    "parameters": [
                        {"name": p.name, "default": str(p.default) if p.default != inspect.Parameter.empty else None}
                        for p in sig.parameters.values()
                    ],
                })
        return orjson.dumps(result).decode()


# ── Format Conversion Tools ──


def _register_convert_tools(mcp: Any) -> None:
    """Tools для конвертации форматов данных."""

    @mcp.tool(
        name="convert_format",
        description="Конвертирует данные между форматами: json, yaml, xml, csv, msgpack, bson. "
        "Пример: from_format='json', to_format='yaml', data='{\"key\": \"value\"}'",
    )
    async def convert_format(from_format: str, to_format: str, data: str) -> str:
        from app.dsl.engine.processors.converters import _STRATEGIES

        key = f"{from_format}→{to_format}"
        strategy = _STRATEGIES.get(key)
        if not strategy:
            available = list(_STRATEGIES.keys())
            return orjson.dumps({
                "error": f"No converter for {key}",
                "available": available,
            }).decode()

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
                return orjson.dumps({
                    "format": to_format,
                    "encoding": "base64",
                    "data": base64.b64encode(result).decode(),
                }).decode()

            if isinstance(result, str):
                return result

            return orjson.dumps(result, default=str).decode()
        except Exception as exc:
            return orjson.dumps({"error": str(exc)}).decode()

    @mcp.tool(
        name="convert_list_formats",
        description="Показывает все доступные конвертации форматов (from→to пары).",
    )
    async def convert_list_formats() -> str:
        from app.dsl.engine.processors.converters import _STRATEGIES
        return orjson.dumps(list(_STRATEGIES.keys())).decode()


# ── System/Monitoring Tools ──


def _register_system_tools(mcp: Any) -> None:
    """Tools для мониторинга и управления системой."""

    @mcp.tool(
        name="system_health",
        description="Проверка здоровья всех компонентов системы (DB, Redis, S3, ES, etc.).",
    )
    async def system_health() -> str:
        from app.dsl.commands.registry import action_handler_registry
        from app.schemas.invocation import ActionCommandSchema

        try:
            result = await action_handler_registry.dispatch(
                ActionCommandSchema(action="tech.check_all_services", payload={})
            )
            if hasattr(result, "model_dump"):
                return orjson.dumps(result.model_dump(mode="json")).decode()
            return orjson.dumps(result, default=str).decode()
        except Exception as exc:
            return orjson.dumps({"error": str(exc)}).decode()

    @mcp.tool(
        name="system_actions",
        description="Список всех доступных actions с группировкой по домену. "
        "Полезно для обнаружения возможностей системы.",
    )
    async def system_actions() -> str:
        from app.dsl.commands.registry import action_handler_registry

        actions = action_handler_registry.list_actions()
        domains: dict[str, list[str]] = {}
        for action in actions:
            domain = action.split(".")[0] if "." in action else "other"
            domains.setdefault(domain, []).append(action)

        return orjson.dumps({
            "total": len(actions),
            "domains": domains,
        }).decode()

    @mcp.tool(
        name="system_processors",
        description="Список всех доступных DSL-процессоров с описаниями. "
        "Процессоры — строительные блоки для создания интеграционных маршрутов.",
    )
    async def system_processors() -> str:
        from app.dsl.engine import processors as proc_module
        import inspect

        result = []
        for name in dir(proc_module):
            obj = getattr(proc_module, name, None)
            if (
                inspect.isclass(obj)
                and name.endswith("Processor")
                and name != "BaseProcessor"
                and name != "CallableProcessor"
            ):
                doc = (obj.__doc__ or "").strip().split("\n")[0]
                result.append({"name": name, "description": doc})

        result.sort(key=lambda x: x["name"])
        return orjson.dumps(result).decode()

    @mcp.tool(
        name="system_feature_flags",
        description="Показывает состояние feature flags. "
        "Feature flags позволяют включать/отключать маршруты без рестарта.",
    )
    async def system_feature_flags() -> str:
        from app.core.config.runtime_state import disabled_feature_flags
        return orjson.dumps({
            "disabled_flags": list(disabled_feature_flags),
        }).decode()
