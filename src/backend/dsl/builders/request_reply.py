"""RequestReply mixin для RouteBuilder.

Обёртка над ReplyChannel (EventBus-based request/reply).
Stateless — см. контракт в ``base.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder


class RequestReplyMixin:
    """Поведенческий миксин request-reply операций для ``RouteBuilder``."""

    __slots__ = ()

    def request(
        self,
        target_channel: str,
        payload: Any = None,
        *,
        timeout: float = 30.0,
        correlation_id: str | None = None,
        result_property: str = "reply",
    ) -> RouteBuilder:
        """Отправляет запрос в ``target_channel`` и ждёт reply.

        Args:
            target_channel: Имя канала EventBus для публикации запроса.
            payload: Тело запроса (dict). ``None`` — берётся из ``body``.
            timeout: Секунд ожидания reply (по умолчанию 30).
            correlation_id: Внешний correlation ID. ``None`` — uuid4.
            result_property: Имя property для записи reply-payload.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.request_reply",
            "RequestProcessor",
            target_channel=target_channel,
            payload=payload,
            timeout=timeout,
            correlation_id=correlation_id,
            result_property=result_property,
        )

    def reply(
        self,
        reply_channel: str | None = None,
        payload: Any = None,
        *,
        correlation_id: str | None = None,
    ) -> RouteBuilder:
        """Публикует reply в ``reply_channel`` (reply_to).

        Args:
            reply_channel: Имя reply-канала. ``None`` — берётся из
                ``properties.reply_to`` или headers.
            payload: Тело reply. ``None`` — берётся из ``body``.
            correlation_id: Correlation ID. ``None`` — берётся из
                ``properties.correlation_id`` или headers.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.request_reply",
            "ReplyProcessor",
            reply_channel=reply_channel,
            payload=payload,
            correlation_id=correlation_id,
        )
