"""MCP server package (S54 W1 decomp from mcp_server.py 706 LOC).

11 functions split into 7 files:
- ``helpers.py`` (3): _action_input_schema_json, _check_mcp_tool_authz, _register_single_tool
- ``tools_route.py`` (1): _register_route_tools
- ``tools_template.py`` (1): _register_template_tools
- ``tools_convert.py`` (1): _register_convert_tools
- ``tools_system.py`` (1): _register_system_tools
- ``tools_yaml.py`` (1): _register_yaml_tools
- ``tools_document.py`` (1): _register_document_tools

Public API: ``create_mcp_server()``, ``register_mcp_tools()``.

Backward-compat: ``from src.backend.entrypoints.mcp.mcp_server import X`` works.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger
from src.backend.entrypoints.mcp.mcp_server.helpers import (
    _action_input_schema_json,
    _check_mcp_tool_authz,
    _register_single_tool,
)
from src.backend.entrypoints.mcp.mcp_server.tools_convert import _register_convert_tools
from src.backend.entrypoints.mcp.mcp_server.tools_document import (
    _register_document_tools,
)
from src.backend.entrypoints.mcp.mcp_server.tools_route import _register_route_tools
from src.backend.entrypoints.mcp.mcp_server.tools_system import _register_system_tools
from src.backend.entrypoints.mcp.mcp_server.tools_template import (
    _register_template_tools,
)
from src.backend.entrypoints.mcp.mcp_server.tools_yaml import _register_yaml_tools

logger = get_logger(__name__)

__all__ = (
    "create_mcp_server",
    "register_mcp_tools",
    "_action_input_schema_json",
    "_check_mcp_tool_authz",
    "_register_single_tool",
    "_register_route_tools",
    "_register_template_tools",
    "_register_convert_tools",
    "_register_system_tools",
    "_register_yaml_tools",
    "_register_document_tools",
)


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
    _register_yaml_tools(mcp)
    _register_document_tools(mcp)

    # S32 W3: AI namespace tools
    try:
        from src.backend.entrypoints.mcp.namespaces.ai_mcp import register_ai_tools

        register_ai_tools(mcp)
    except Exception as exc:
        logger.debug("AI namespace MCP tools registration skipped: %s", exc)

    # IL-WF1.5: auto-export durable workflows как MCP tools
    # (CrewAI / LangChain / LangGraph получают каждый workflow
    # отдельным tool'ом с валидацией payload через input_schema).
    try:
        from src.backend.entrypoints.mcp.workflow_tools import register_workflow_tools

        register_workflow_tools(mcp)
    except Exception as exc:
        logger.warning("workflow MCP tools registration skipped: %s", exc)

    return mcp



def register_mcp_tools(mcp: Any) -> None:
    """Регистрирует все actions из ActionHandlerRegistry как MCP tools.

    Args:
        mcp: Экземпляр FastMCP.
    """
    from src.backend.dsl.commands.registry import action_handler_registry

    for action_name in action_handler_registry.list_actions():
        _register_single_tool(mcp, action_name)

    logger.info(
        "Зарегистрировано %d action MCP tools",
        len(action_handler_registry.list_actions()),
    )

