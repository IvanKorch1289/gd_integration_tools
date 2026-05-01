"""AI Tools API — экспозиция AI-инструментов через REST.

W26.5: маршруты регистрируются декларативно через ActionSpec.

Endpoints:
  * ``GET /ai/tools``           — список всех инструментов.
  * ``GET /ai/tools/{tool_id}`` — подробности одного инструмента.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.entrypoints.api.generator.actions import ActionRouterBuilder, ActionSpec
from src.services.ai.tools import get_tool_registry

__all__ = ("router",)


class ToolIdPath(BaseModel):
    """Path-параметр идентификатора инструмента."""

    tool_id: str = Field(..., description="Уникальный идентификатор AI-инструмента.")


class _AIToolsFacade:
    """Адаптер над ``ToolRegistry`` для action-маршрутов."""

    async def list_tools(self) -> dict[str, Any]:
        registry = get_tool_registry()
        items = [tool.to_dict() for tool in registry.list()]
        return {"tools": items, "total": len(items)}

    async def get_tool(self, *, tool_id: str) -> dict[str, Any]:
        registry = get_tool_registry()
        tool = registry.get(tool_id)
        if tool is None:
            raise HTTPException(status_code=404, detail=f"Tool {tool_id!r} not found")
        return tool.to_dict()


_FACADE = _AIToolsFacade()


def _get_facade() -> _AIToolsFacade:
    return _FACADE


router = APIRouter()
builder = ActionRouterBuilder(router)

common_tags = ("AI · Tools",)


builder.add_actions(
    [
        ActionSpec(
            name="list_ai_tools",
            method="GET",
            path="/tools",
            summary="Список AI-инструментов",
            description="Возвращает реестр AI-инструментов (from_service + plugins).",
            service_getter=_get_facade,
            service_method="list_tools",
            tags=common_tags,
        ),
        ActionSpec(
            name="get_ai_tool",
            method="GET",
            path="/tools/{tool_id}",
            summary="Описание одного инструмента",
            description="Возвращает полное описание AI-инструмента по его идентификатору.",
            service_getter=_get_facade,
            service_method="get_tool",
            path_model=ToolIdPath,
            tags=common_tags,
        ),
    ]
)
