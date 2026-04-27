"""AI Tools API — экспозиция AI-инструментов через REST.

Предоставляет метаданные инструментов, зарегистрированных
в ``ToolRegistry``, для внешних систем (агентные платформы,
UI developer portal, mcp-мосты).

Endpoints:
  * ``GET /ai/tools`` — список всех инструментов.
  * ``GET /ai/tools/{tool_id}`` — подробности одного инструмента.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.services.ai.tools import get_tool_registry

__all__ = ("router",)

router = APIRouter()


@router.get(
    "/tools",
    summary="Список AI-инструментов",
    description="Возвращает реестр AI-инструментов (from_service + plugins).",
)
async def list_tools() -> dict:
    """Отдаёт все зарегистрированные инструменты.

    Returns:
        dict: ``{"tools": [...], "total": N}`` с JSON-описанием.
    """
    registry = get_tool_registry()
    items = [tool.to_dict() for tool in registry.list()]
    return {"tools": items, "total": len(items)}


@router.get(
    "/tools/{tool_id}",
    summary="Описание одного инструмента",
    description="Возвращает полное описание AI-инструмента по его идентификатору.",
)
async def get_tool(tool_id: str) -> dict:
    """Отдаёт подробности одного инструмента.

    Args:
        tool_id: Уникальный идентификатор инструмента.

    Returns:
        dict: JSON-описание инструмента.

    Raises:
        HTTPException: 404, если инструмент не зарегистрирован.
    """
    registry = get_tool_registry()
    tool = registry.get(tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"Tool {tool_id!r} not found")
    return tool.to_dict()
