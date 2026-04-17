"""MCP-сервер на базе FastMCP.

Автоматически экспортирует все зарегистрированные actions
из ActionHandlerRegistry как MCP tools. Позволяет
LLM-агентам вызывать любой бизнес-action через MCP-протокол.
"""

import json
import logging
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
        "Предоставляет доступ ко всем бизнес-actions.",
    )

    register_mcp_tools(mcp)
    return mcp


def register_mcp_tools(mcp: Any) -> None:
    """Регистрирует все actions из ActionHandlerRegistry как MCP tools.

    Args:
        mcp: Экземпляр FastMCP.
    """
    from app.dsl.commands.registry import action_handler_registry
    from app.schemas.invocation import ActionCommandSchema

    for action_name in action_handler_registry.list_actions():
        _register_single_tool(mcp, action_name)

    logger.info(
        "Зарегистрировано %d MCP tools",
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
        """Универсальный MCP tool handler.

        Args:
            payload: JSON-строка с данными для action.

        Returns:
            JSON-строка с результатом.
        """
        try:
            parsed_payload = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            parsed_payload = {"raw": payload}

        command = ActionCommandSchema(
            action=_action,
            payload=parsed_payload,
            meta={"source": "mcp"},
        )

        try:
            result = await action_handler_registry.dispatch(command)
            if hasattr(result, "model_dump"):
                return json.dumps(result.model_dump(mode="json"), default=str)
            return json.dumps(result, default=str)
        except Exception as exc:
            return json.dumps({"error": str(exc)})
