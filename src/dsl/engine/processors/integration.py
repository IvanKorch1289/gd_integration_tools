"""Integration processors — EventBus, Agent Memory."""

from typing import Any, Callable

from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange
from app.dsl.engine.processors.base import BaseProcessor

__all__ = ("EventPublishProcessor", "MemoryLoadProcessor", "MemorySaveProcessor")


class EventPublishProcessor(BaseProcessor):
    """Публикует событие из pipeline через EventBus."""

    def __init__(self, channel: str, event_factory: Callable[[Exchange[Any]], dict[str, Any]] | None = None, name: str | None = None) -> None:
        super().__init__(name)
        self._channel = channel
        self._event_factory = event_factory

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from pydantic import BaseModel
        from app.infrastructure.clients.event_bus import get_event_bus

        bus = get_event_bus()
        if self._event_factory:
            data = self._event_factory(exchange)
        else:
            data = {
                "route_id": context.route_id,
                "body": exchange.in_message.body,
                "correlation_id": exchange.correlation_id,
            }
        event = type("PipelineEvent", (BaseModel,), data)()
        await bus.publish(self._channel, event)


class MemoryLoadProcessor(BaseProcessor):
    """Загружает conversation + facts из AgentMemoryService."""

    def __init__(self, session_id_header: str = "X-Session-Id", name: str | None = None) -> None:
        super().__init__(name)
        self._session_header = session_id_header

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        session_id = exchange.in_message.headers.get(self._session_header)
        if not session_id:
            session_id = exchange.correlation_id
        from app.services.agent_memory import get_agent_memory_service
        memory_svc = get_agent_memory_service()
        memory = await memory_svc.load_memory(session_id)
        exchange.set_property("_agent_memory", memory)
        exchange.set_property("_session_id", session_id)


class MemorySaveProcessor(BaseProcessor):
    """Сохраняет результат в AgentMemoryService."""

    def __init__(self, name: str | None = None) -> None:
        super().__init__(name)

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        session_id = exchange.properties.get("_session_id")
        if not session_id:
            return
        from app.services.agent_memory import get_agent_memory_service
        memory_svc = get_agent_memory_service()
        body = exchange.in_message.body
        content = body if isinstance(body, str) else str(body)
        await memory_svc.add_message(session_id, "assistant", content)
