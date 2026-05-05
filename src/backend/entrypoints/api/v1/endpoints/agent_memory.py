"""REST API для AgentMemory (Wave 8.4).

Три ресурса под одной сессией:

* ``GET/POST/DELETE /sessions/{session_id}/messages``
* ``GET/PUT/DELETE  /sessions/{session_id}/scratchpad``
* ``GET/POST        /sessions/{session_id}/facts``
* ``GET/DELETE      /sessions/{session_id}/facts/{fact_key}``

Регистрируется в ``v1/routers.py`` под префиксом ``/agent_memory``.
TTL уважается на стороне Mongo (см. ``AgentMemoryService``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from src.backend.entrypoints.api.generator.actions import (
    ActionRouterBuilder,
    ActionSpec,
)
from src.backend.schemas.agent_memory import (
    FactCreate,
    FactKeyPath,
    FactRead,
    FactsResponse,
    MessageCreate,
    MessagesResponse,
    ScratchpadResponse,
    ScratchpadValue,
    SessionListQuery,
    SessionPath,
)
from src.backend.services.ai.agent_memory import get_agent_memory_service

__all__ = ("router",)


# --- Service facade --------------------------------------------------------


class _AgentMemoryFacade:
    """Адаптер над ``AgentMemoryService`` для action-маршрутов."""

    # ---- messages ----

    async def list_messages(
        self, *, session_id: str, last_n: int = 20
    ) -> MessagesResponse:
        items = await get_agent_memory_service().get_conversation(session_id, last_n)
        return MessagesResponse(items=items)

    async def add_message(
        self, *, session_id: str, role: str, content: str, metadata: Any = None
    ) -> dict[str, str]:
        await get_agent_memory_service().add_message(
            session_id, role=role, content=content, metadata=metadata
        )
        return {"status": "ok"}

    async def clear_messages(self, *, session_id: str) -> dict[str, str]:
        await get_agent_memory_service().clear_conversation(session_id)
        return {"status": "ok"}

    # ---- scratchpad ----

    async def get_scratchpad(self, *, session_id: str) -> ScratchpadResponse:
        content = await get_agent_memory_service().get_scratchpad(session_id)
        return ScratchpadResponse(session_id=session_id, content=content)

    async def set_scratchpad(
        self, *, session_id: str, content: str = ""
    ) -> ScratchpadResponse:
        await get_agent_memory_service().set_scratchpad(session_id, content)
        return ScratchpadResponse(session_id=session_id, content=content)

    async def clear_scratchpad(self, *, session_id: str) -> dict[str, str]:
        await get_agent_memory_service().set_scratchpad(session_id, "")
        return {"status": "ok"}

    # ---- facts ----

    async def list_facts(self, *, session_id: str) -> FactsResponse:
        raw = await get_agent_memory_service().get_facts(session_id)
        facts = [FactRead(fact_key=k, value=v) for k, v in raw.items()]
        return FactsResponse(session_id=session_id, facts=facts)

    async def add_fact(self, *, session_id: str, fact_key: str, value: str) -> FactRead:
        await get_agent_memory_service().set_fact(session_id, fact_key, value)
        return FactRead(fact_key=fact_key, value=value)

    async def get_fact(self, *, session_id: str, fact_key: str) -> FactRead:
        all_facts = await get_agent_memory_service().get_facts(session_id)
        return FactRead(fact_key=fact_key, value=all_facts.get(fact_key, ""))

    async def delete_fact(self, *, session_id: str, fact_key: str) -> dict[str, str]:
        await get_agent_memory_service().delete_fact(session_id, fact_key)
        return {"status": "ok"}


_FACADE = _AgentMemoryFacade()


def _get_facade() -> _AgentMemoryFacade:
    return _FACADE


# --- Router ----------------------------------------------------------------


router = APIRouter()
builder = ActionRouterBuilder(router)

common_tags = ("AgentMemory",)


builder.add_actions(
    [
        # ---- messages ----
        ActionSpec(
            name="agent_memory_list_messages",
            method="GET",
            path="/sessions/{session_id}/messages",
            summary="Последние N сообщений сессии",
            service_getter=_get_facade,
            service_method="list_messages",
            path_model=SessionPath,
            query_model=SessionListQuery,
            response_model=MessagesResponse,
            tags=common_tags,
        ),
        ActionSpec(
            name="agent_memory_add_message",
            method="POST",
            path="/sessions/{session_id}/messages",
            summary="Добавить сообщение в history",
            service_getter=_get_facade,
            service_method="add_message",
            path_model=SessionPath,
            body_model=MessageCreate,
            tags=common_tags,
        ),
        ActionSpec(
            name="agent_memory_clear_messages",
            method="DELETE",
            path="/sessions/{session_id}/messages",
            summary="Очистить history сессии",
            service_getter=_get_facade,
            service_method="clear_messages",
            path_model=SessionPath,
            tags=common_tags,
        ),
        # ---- scratchpad ----
        ActionSpec(
            name="agent_memory_get_scratchpad",
            method="GET",
            path="/sessions/{session_id}/scratchpad",
            summary="Получить scratchpad",
            service_getter=_get_facade,
            service_method="get_scratchpad",
            path_model=SessionPath,
            response_model=ScratchpadResponse,
            tags=common_tags,
        ),
        ActionSpec(
            name="agent_memory_set_scratchpad",
            method="PUT",
            path="/sessions/{session_id}/scratchpad",
            summary="Перезаписать scratchpad",
            service_getter=_get_facade,
            service_method="set_scratchpad",
            path_model=SessionPath,
            body_model=ScratchpadValue,
            response_model=ScratchpadResponse,
            tags=common_tags,
        ),
        ActionSpec(
            name="agent_memory_clear_scratchpad",
            method="DELETE",
            path="/sessions/{session_id}/scratchpad",
            summary="Очистить scratchpad",
            service_getter=_get_facade,
            service_method="clear_scratchpad",
            path_model=SessionPath,
            tags=common_tags,
        ),
        # ---- facts ----
        ActionSpec(
            name="agent_memory_list_facts",
            method="GET",
            path="/sessions/{session_id}/facts",
            summary="Все факты сессии",
            service_getter=_get_facade,
            service_method="list_facts",
            path_model=SessionPath,
            response_model=FactsResponse,
            tags=common_tags,
        ),
        ActionSpec(
            name="agent_memory_add_fact",
            method="POST",
            path="/sessions/{session_id}/facts",
            summary="Добавить/обновить факт",
            service_getter=_get_facade,
            service_method="add_fact",
            path_model=SessionPath,
            body_model=FactCreate,
            response_model=FactRead,
            tags=common_tags,
        ),
        ActionSpec(
            name="agent_memory_get_fact",
            method="GET",
            path="/sessions/{session_id}/facts/{fact_key}",
            summary="Один факт по ключу",
            service_getter=_get_facade,
            service_method="get_fact",
            path_model=FactKeyPath,
            response_model=FactRead,
            tags=common_tags,
        ),
        ActionSpec(
            name="agent_memory_delete_fact",
            method="DELETE",
            path="/sessions/{session_id}/facts/{fact_key}",
            summary="Удалить один факт",
            service_getter=_get_facade,
            service_method="delete_fact",
            path_model=FactKeyPath,
            tags=common_tags,
        ),
    ]
)
