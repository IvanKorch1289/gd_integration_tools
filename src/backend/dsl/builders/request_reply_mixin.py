"""RequestReplyMixin (S38 W2 — Async Request-Reply EIP, Camel-style).

Apache Camel **Async Request-Reply**: send request → wait for reply on
correlation ID → return reply. Return address = ``reply:<cid>``.

* :class:`RequestReplyBackend` — per-builder pending-future registry,
  asyncio.Lock для thread-safety, pluggable transport.
* :class:`InMemoryTransport` — in-process pub/sub для unit-тестов.
* :class:`RequestReplyTransport` (Protocol) — EventBus/Redis interface.
* :class:`RequestReplyTimeoutError` — ``asyncio.TimeoutError`` subclass.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

from src.backend.core.logging import get_logger

__all__ = (
    "DEFAULT_TIMEOUT_S",
    "REPLY_CHANNEL_PREFIX",
    "InMemoryTransport",
    "RequestReplyBackend",
    "RequestReplyMixin",
    "RequestReplyTimeoutError",
    "RequestReplyTransport",
)

logger = get_logger(__name__)

REPLY_CHANNEL_PREFIX: str = "reply:"
DEFAULT_TIMEOUT_S: float = 30.0
_BACKEND_ATTR = "_rr_backend"
_TRANSPORT_ATTR = "_rr_transport"


class RequestReplyTimeoutError(asyncio.TimeoutError):
    """Reply не пришёл за ``timeout`` секунд."""


@runtime_checkable
class RequestReplyTransport(Protocol):
    """Pluggable transport: EventBus / Redis pub/sub / in-memory."""

    async def publish(self, channel: str, envelope: dict[str, Any]) -> None: ...
    async def subscribe(
        self, channel: str, handler: Callable[[dict[str, Any]], Awaitable[None]]
    ) -> None: ...


class InMemoryTransport:
    """In-process async pub/sub — для unit-тестов и dev-сценариев.

    Multiple subscribers on the same channel получают copies envelope'а.
    ``log`` хранит (direction, channel) для test assertions.
    """

    __slots__ = ("_lock", "_log", "_subs")

    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[..., Awaitable[None]]]] = {}
        self._lock = asyncio.Lock()
        self._log: list[tuple[str, str]] = []

    @property
    def log(self) -> list[tuple[str, str]]:
        return list(self._log)

    async def publish(self, channel: str, envelope: dict[str, Any]) -> None:
        self._log.append(("publish", channel))
        async with self._lock:
            subs = list(self._subs.get(channel, ()))
        for sub in subs:
            await sub(envelope)

    async def subscribe(
        self, channel: str, handler: Callable[[dict[str, Any]], Awaitable[None]]
    ) -> None:
        self._log.append(("subscribe", channel))
        async with self._lock:
            self._subs.setdefault(channel, []).append(handler)


class RequestReplyBackend:
    """Async Request-Reply backend — owns pending future registry.

    Один backend на builder. ``cid`` ↔ ``reply:<cid>`` (return address).
    Thread-safe (asyncio.Lock). Transport failures propagate к caller'у.
    """

    __slots__ = ("_lock", "_pending", "_subscribed", "_transport")

    def __init__(self, transport: RequestReplyTransport) -> None:
        self._transport = transport
        self._pending: dict[str, asyncio.Future[Any]] = {}
        self._lock = asyncio.Lock()
        self._subscribed: set[str] = set()

    @staticmethod
    def reply_channel(correlation_id: str) -> str:
        """Return address: ``reply:<cid>`` per EIP spec."""
        return f"{REPLY_CHANNEL_PREFIX}{correlation_id}"

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def transport(self) -> RequestReplyTransport:
        return self._transport

    async def request(
        self,
        endpoint: str,
        payload: Any,
        *,
        timeout: float = DEFAULT_TIMEOUT_S,
        correlation_id: str | None = None,
    ) -> Any:
        """Опубликовать request в ``endpoint`` и ждать reply.

        Raises:
            ValueError: Дубликат ``correlation_id``.
            RequestReplyTimeoutError: Reply не пришёл за ``timeout``.
        """
        cid = correlation_id or str(uuid.uuid4())
        reply_ch = self.reply_channel(cid)
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        async with self._lock:
            if cid in self._pending:
                raise ValueError(f"duplicate correlation_id: {cid!r}")
            self._pending[cid] = fut
            await self._ensure_subscribed(reply_ch)
        envelope = {"correlation_id": cid, "reply_to": reply_ch, "payload": payload}
        try:
            await self._transport.publish(endpoint, envelope)
            return await asyncio.wait_for(fut, timeout=timeout)
        except TimeoutError as exc:
            raise RequestReplyTimeoutError(
                f"request timeout after {timeout}s (cid={cid})"
            ) from exc
        finally:
            async with self._lock:
                self._pending.pop(cid, None)

    async def reply(self, correlation_id: str, payload: Any) -> None:
        """Опубликовать reply в return address ``reply:<cid>``."""
        await self._transport.publish(
            self.reply_channel(correlation_id),
            {"correlation_id": correlation_id, "payload": payload},
        )

    async def wait_for_reply(
        self, correlation_id: str, *, timeout: float = DEFAULT_TIMEOUT_S
    ) -> Any:
        """Блокирующее ожидание reply для существующего ``correlation_id``."""
        reply_ch = self.reply_channel(correlation_id)
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        async with self._lock:
            if correlation_id in self._pending:
                raise ValueError(f"correlation_id {correlation_id!r} already pending")
            self._pending[correlation_id] = fut
            await self._ensure_subscribed(reply_ch)
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except TimeoutError as exc:
            raise RequestReplyTimeoutError(
                f"wait_for_reply timeout after {timeout}s (cid={correlation_id})"
            ) from exc
        finally:
            async with self._lock:
                self._pending.pop(correlation_id, None)

    async def _ensure_subscribed(self, channel: str) -> None:
        if channel in self._subscribed:
            return
        self._subscribed.add(channel)
        await self._transport.subscribe(channel, self._on_reply)

    async def _on_reply(self, envelope: dict[str, Any]) -> None:
        cid = envelope.get("correlation_id")
        if not cid:
            return
        async with self._lock:
            fut = self._pending.get(cid)
        if fut is None or fut.done():
            return
        fut.set_result(envelope.get("payload"))


class RequestReplyMixin:
    """Async Request-Reply EIP mixin для :class:`RouteBuilder` (S38 W2).

    Per-builder backend (lazy, isolated). По умолчанию —
    :class:`InMemoryTransport`; в production attach'ится EventBus/Redis
    transport через :meth:`attach_transport`.
    """

    __slots__ = ()

    def _request_reply_backend(self) -> RequestReplyBackend:
        backend: RequestReplyBackend | None = getattr(self, _BACKEND_ATTR, None)
        if backend is None:
            transport: RequestReplyTransport = (
                getattr(self, _TRANSPORT_ATTR, None) or InMemoryTransport()
            )
            backend = RequestReplyBackend(transport=transport)
            with contextlib.suppress(AttributeError, TypeError):
                object.__setattr__(self, _BACKEND_ATTR, backend)
        return backend

    def attach_transport(self, transport: RequestReplyTransport) -> RequestReplyMixin:
        """Прикрепить transport (EventBus/Redis). Возвращает self для chain."""
        with contextlib.suppress(AttributeError, TypeError):
            object.__setattr__(self, _TRANSPORT_ATTR, transport)
            object.__setattr__(self, _BACKEND_ATTR, None)
        return self

    async def request(
        self,
        endpoint: str,
        *,
        payload: Any,
        timeout: float = DEFAULT_TIMEOUT_S,
        correlation_id: str | None = None,
    ) -> Any:
        """Send request, wait for reply, return reply."""
        return await self._request_reply_backend().request(
            endpoint, payload, timeout=timeout, correlation_id=correlation_id
        )

    async def reply(self, correlation_id: str, payload: Any) -> None:
        """Опубликовать reply в return address ``reply:<cid>``."""
        await self._request_reply_backend().reply(correlation_id, payload)

    async def wait_for_reply(
        self, correlation_id: str, *, timeout: float = DEFAULT_TIMEOUT_S
    ) -> Any:
        """Блокирующее ожидание reply для ``correlation_id``."""
        return await self._request_reply_backend().wait_for_reply(
            correlation_id, timeout=timeout
        )
