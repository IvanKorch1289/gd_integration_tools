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

from src.backend.core.logging import get_logger
from src.backend.core.serialization.msgspec_hotpath import encode_json

logger = get_logger(__name__)


# ── system tools (_register_system_tools) ──


def _register_system_tools(mcp: Any) -> None:
    """Tools для мониторинга и управления системой."""

    @mcp.tool(
        name="system_health",
        description="Проверка здоровья всех компонентов системы (DB, Redis, S3, ES, etc.).",
    )
    async def system_health() -> str:
        from src.backend.dsl.commands.registry import action_handler_registry
        from src.backend.schemas.invocation import ActionCommandSchema

        try:
            result = await action_handler_registry.dispatch(
                ActionCommandSchema(action="tech.check_all_services", payload={})
            )
            if hasattr(result, "model_dump"):
                return encode_json(result.model_dump(mode="json")).decode("utf-8")
            return encode_json(result).decode("utf-8")
        except Exception as exc:
            return encode_json({"error": str(exc)}).decode("utf-8")

    @mcp.tool(
        name="system_actions",
        description="Список всех доступных actions с группировкой по домену. "
        "Полезно для обнаружения возможностей системы.",
    )
    async def system_actions() -> str:
        from src.backend.dsl.commands.registry import action_handler_registry

        actions = action_handler_registry.list_actions()
        domains: dict[str, list[str]] = {}
        for action in actions:
            domain = action.split(".")[0] if "." in action else "other"
            domains.setdefault(domain, []).append(action)

        return encode_json({"total": len(actions), "domains": domains}).decode("utf-8")

    @mcp.tool(
        name="system_processors",
        description="Список всех доступных DSL-процессоров с описаниями. "
        "Процессоры — строительные блоки для создания интеграционных маршрутов.",
    )
    async def system_processors() -> str:
        import inspect

        from src.backend.dsl.engine import processors as proc_module

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
        return encode_json(result).decode("utf-8")

    @mcp.tool(
        name="system_feature_flags",
        description="Показывает состояние feature flags. "
        "Feature flags позволяют включать/отключать маршруты без рестарта.",
    )
    async def system_feature_flags() -> str:
        from src.backend.core.state.runtime import disabled_feature_flags

        return encode_json({"disabled_flags": list(disabled_feature_flags)}).decode(
            "utf-8"
        )
