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
        # S97 W1: RouteBuilder.__init__ теперь принимает (route_id, source, description).
        # Bind source через object.__setattr__ (slot declaration в __slots__).
        builder = cls.from_(  # type: ignore[return-value]
            route_id, source=f"sse:{route_id}", description=f"SSE stream: {url}"
        )
        object.__setattr__(builder, "_sse_source", source)
        return builder

    @classmethod
    def from_sse_multi(
        cls,
        route_id: str,
        urls: list[str],
        *,
        merge_strategy: str = "interleave",
        headers: dict[str, str] | None = None,
        event_type: str | None = None,
        heartbeat_timeout_s: float = 60.0,
        reconnect_max_retries: int | None = None,
        parse_json: bool = True,
    ) -> RouteBuilder:
        """S96 W4: multi-stream SSE consumer — subscribe N URLs параллельно.

        Каждый URL подписывается отдельно через :class:`SSESource`,
        события мерджатся согласно ``merge_strategy``:

        * ``"interleave"`` (default) — round-robin merge, preserves order
          across streams (как :func:`merge_streams`).
        * ``"concat"`` — strict ordered concat: дожидается close от stream N
          перед N+1. Полезно для batch-replay.
        * ``"first"`` — fire event от первого активного stream (как
          :class:`ForkJoinProcessor` aggregation="first").

        Args:
            route_id: Уникальный ID маршрута (suffix ``.multi`` добавится).
            urls: Список SSE endpoint URLs.
            merge_strategy: One of ``"interleave"``, ``"concat"``, ``"first"``.
            headers: Общие заголовки для всех streams.
            event_type: Общий фильтр (``None`` = все типы).
            heartbeat_timeout_s: Reconnect timeout (per stream).
            reconnect_max_retries: Max attempts (None = infinite).
            parse_json: JSON-decode если True.

        Returns:
            RouteBuilder с source ``sse-multi:<route_id>``.

        Raises:
            ValueError: Если ``urls`` пуст или ``merge_strategy`` invalid.

        Example::

            route = (
                RouteBuilder.from_sse_multi(
                    "multi.tenant_streams",
                    [
                        "https://tenant-a.example.com/events",
                        "https://tenant-b.example.com/events",
                    ],
                    merge_strategy="interleave",
                    headers={"Authorization": f"Bearer {token}"},
                )
                .transform(unify_event_schema)
                .dispatch_action("events.process")
                .build()
            )
        """
        if not urls:
            raise ValueError("from_sse_multi: urls must be non-empty list")
        if merge_strategy not in ("interleave", "concat", "first"):
            raise ValueError(
                f"from_sse_multi: invalid merge_strategy={merge_strategy!r} "
                f"(expected: interleave, concat, first)"
            )

        import importlib

        mod = importlib.import_module("src.backend.infrastructure.sources.sse")

        # Build N SSESource instances.
        sources = [
            mod.SSESource(
                url=u,
                headers=headers,
                event_type=event_type,
                last_event_id=None,
                heartbeat_timeout_s=heartbeat_timeout_s,
                reconnect_max_retries=reconnect_max_retries,
                parse_json=parse_json,
            )
            for u in urls
        ]
        # Multi-source route_id suffix для disambiguation.
        multi_route_id = (
            f"{route_id}.multi" if not route_id.endswith(".multi") else route_id
        )

        # S97 W1: same as from_sse — use cls.from_ (no-args cls() deprecated).
        builder = cls.from_(  # type: ignore[return-value]
            multi_route_id,
            source=f"sse-multi:{multi_route_id}",
            description=f"SSE multi: {len(urls)} streams ({merge_strategy})",
        )
        object.__setattr__(builder, "_sse_multi_source", (sources, merge_strategy))
        return builder  # type: ignore[return-value]
