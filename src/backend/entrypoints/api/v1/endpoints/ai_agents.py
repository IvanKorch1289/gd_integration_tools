"""REST API для специализированных AI-агентов (Wave 8.7).

Единый dispatch ``POST /api/v1/ai/agents/{name}/invoke``:

* ``analytics`` → :class:`AnalyticsAgent` (Polars/DuckDB);
* ``search`` → :class:`SearchAgent` (RAG/AgentMemory).

Каталог инструментов агента: ``GET /api/v1/ai/agents/{name}/tools``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from src.entrypoints.api.generator.actions import ActionRouterBuilder, ActionSpec
from src.services.ai.agents import get_analytics_agent, get_search_agent

__all__ = ("router",)


# --- Schemas ---------------------------------------------------------------


class AgentNamePath(BaseModel):
    """Path-параметр имени агента."""

    name: str = Field(..., description="``analytics`` или ``search``.")


class AgentInvokeRequest(BaseModel):
    """Тело POST /invoke."""

    prompt: str = Field(..., min_length=1)
    tool: str | None = Field(default=None, description="Конкретный tool (optional).")
    payload: dict[str, Any] | None = Field(default=None)


class AgentInvokeResponse(BaseModel):
    """Ответ /invoke."""

    success: bool
    tool: str | None = None
    result: Any | None = None
    error: str | None = None
    mode: str | None = None
    prompt: str | None = None
    tools: list[dict[str, Any]] | None = None
    available: list[str] | None = None


class AgentToolsResponse(BaseModel):
    """Ответ /tools — каталог."""

    agent: str
    tools: list[dict[str, Any]]


# --- Service facade --------------------------------------------------------


def _resolve_agent(name: str) -> Any:
    match name:
        case "analytics":
            return get_analytics_agent()
        case "search":
            return get_search_agent()
        case _:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"unknown agent: {name!r}. Доступны: analytics, search.",
            )


class _AIAgentsFacade:
    """Адаптер над специализированными агентами."""

    async def invoke(
        self,
        *,
        name: str,
        prompt: str,
        tool: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AgentInvokeResponse:
        agent = _resolve_agent(name)
        result = await agent.invoke(prompt, tool=tool, payload=payload)
        return AgentInvokeResponse(**result)

    async def tools(self, *, name: str) -> AgentToolsResponse:
        agent = _resolve_agent(name)
        tools = agent.list_tools()
        return AgentToolsResponse(agent=name, tools=[t.to_dict() for t in tools])


_FACADE = _AIAgentsFacade()


def _get_facade() -> _AIAgentsFacade:
    return _FACADE


# --- Router ----------------------------------------------------------------


router = APIRouter()
builder = ActionRouterBuilder(router)

common_tags = ("AI · Agents",)

builder.add_actions(
    [
        ActionSpec(
            name="ai_agent_invoke",
            method="POST",
            path="/agents/{name}/invoke",
            summary="Вызвать специализированного AI-агента",
            service_getter=_get_facade,
            service_method="invoke",
            path_model=AgentNamePath,
            body_model=AgentInvokeRequest,
            response_model=AgentInvokeResponse,
            tags=common_tags,
        ),
        ActionSpec(
            name="ai_agent_tools",
            method="GET",
            path="/agents/{name}/tools",
            summary="Каталог инструментов агента",
            service_getter=_get_facade,
            service_method="tools",
            path_model=AgentNamePath,
            response_model=AgentToolsResponse,
            tags=common_tags,
        ),
    ]
)
