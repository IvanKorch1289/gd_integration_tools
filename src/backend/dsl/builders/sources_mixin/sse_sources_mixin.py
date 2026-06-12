"""S94 W4 — Streaming SSE source registration.

Добавляет ``from_sse`` метод в RouteBuilder — обёртка над
:class:`SSESource` для регистрации SSE-источника в DSL route.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder


class StreamingSSEMixin:
    """SSE-based source registration для RouteBuilder.

    Позволяет регистрировать SSE endpoint как DSL route source.
    """

    __slots__ = ()

    @classmethod
    def from_sse(
        cls,
        route_id: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        event_type: str | None = None,
        last_event_id: str | None = None,
        heartbeat_timeout_s: float = 60.0,
        reconnect_max_retries: int | None = None,
        parse_json: bool = True,
    ) -> RouteBuilder:
        """SSE consumer: регистрирует маршрут с SSE-источником.

        S94 W4: использует :class:`SSESource` для long-poll HTTP-stream.
        Каждое SSE-сообщение эмитится как DSL message.

        Args:
            route_id: Уникальный ID маршрута.
            url: SSE endpoint URL (``text/event-stream``).
            headers: Доп. HTTP-заголовки (e.g. ``Authorization``).
            event_type: Фильтр по ``event: <type>`` (None = все).
            last_event_id: Стартовый ``Last-Event-ID`` (для resume).
            heartbeat_timeout_s: Reconnect если нет событий N секунд.
            reconnect_max_retries: Макс. attempts (None = infinite).
            parse_json: Если True — пытается JSON-decode data.

        Returns:
            RouteBuilder с source ``sse:<route_id>``.

        Example::

            route = (
                RouteBuilder.from_sse(
                    "orders.stream",
                    "https://api.example.com/events",
                    event_type="order.created",
                    headers={"Authorization": f"Bearer {token}"},
                )
                .transform(parse_order)
                .dispatch_action("orders.process")
                .build()
            )
        """
        import importlib

        mod = importlib.import_module("src.backend.infrastructure.sources.sse")
        source = mod.SSESource(
            url=url,
            headers=headers,
            event_type=event_type,
            last_event_id=last_event_id,
            heartbeat_timeout_s=heartbeat_timeout_s,
            reconnect_max_retries=reconnect_max_retries,
            parse_json=parse_json,
        )
        return cls(  # type: ignore[call-arg, return-value]
            route_id, source=f"sse:{route_id}", _source_obj=source
        )
