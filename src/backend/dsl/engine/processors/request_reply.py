"""Request-Reply processors — поверх ReplyChannel / EventBus."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = ("ReplyProcessor", "RequestProcessor")


class RequestProcessor(BaseProcessor):
    """Отправляет запрос через ReplyChannel и ждёт reply."""

    def __init__(
        self,
        target_channel: str,
        payload: Any = None,
        timeout: float = 30.0,
        correlation_id: str | None = None,
        result_property: str = "reply",
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"request:{target_channel}")
        self._target_channel = target_channel
        self._payload = payload
        self._timeout = timeout
        self._correlation_id = correlation_id
        self._result_property = result_property

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.backend.infrastructure.clients.messaging.reply_channel import (
            ReplyChannel,
        )

        payload = (
            self._payload if self._payload is not None else exchange.in_message.body
        )
        channel = ReplyChannel.instance()
        reply = await channel.request(
            target_channel=self._target_channel,
            payload=payload if isinstance(payload, dict) else {"body": payload},
            timeout=self._timeout,
            correlation_id=self._correlation_id,
        )
        exchange.set_property(self._result_property, reply)
        exchange.set_out(body=reply, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "request": {
                "target_channel": self._target_channel,
                "payload": self._payload,
                "timeout": self._timeout,
                "correlation_id": self._correlation_id,
                "result_property": self._result_property,
            }
        }


class ReplyProcessor(BaseProcessor):
    """Публикует reply в reply_to-канал через EventBus broker."""

    def __init__(
        self,
        reply_channel: str | None = None,
        payload: Any = None,
        correlation_id: str | None = None,
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "reply")
        self._reply_channel = reply_channel
        self._payload = payload
        self._correlation_id = correlation_id

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        reply_to = (
            self._reply_channel
            or exchange.properties.get("reply_to")
            or exchange.in_message.headers.get("reply_to")
        )
        cid = (
            self._correlation_id
            or exchange.properties.get("correlation_id")
            or exchange.in_message.headers.get("correlation_id")
        )
        payload = (
            self._payload if self._payload is not None else exchange.in_message.body
        )

        if not reply_to or not cid:
            exchange.fail("Missing reply_to or correlation_id for reply")
            return

        from src.backend.infrastructure.clients.messaging.event_bus import get_event_bus

        bus = get_event_bus()
        broker = getattr(bus, "_broker", None)
        if broker is None:
            exchange.fail("EventBus broker not available")
            return

        message: dict[str, Any] = {
            "correlation_id": cid,
            "payload": payload if isinstance(payload, dict) else {"body": payload},
        }
        await broker.publish(message, channel=reply_to)
        exchange.set_property("reply_sent", True)
        exchange.set_out(body=payload, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "reply": {
                "reply_channel": self._reply_channel,
                "payload": self._payload,
                "correlation_id": self._correlation_id,
            }
        }
