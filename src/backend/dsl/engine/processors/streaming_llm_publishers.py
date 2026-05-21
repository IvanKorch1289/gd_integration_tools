"""Publisher'ы для :class:`TokenStreamLLMProcessor` (SSE / WS / Webhook)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import orjson

logger = logging.getLogger(__name__)

__all__ = ("SSEPublisher", "WSPublisher", "WebhookChunkedPublisher")


class _BasePublisher:
    """Общий интерфейс publisher'а."""

    async def publish_chunk(self, *, exchange: Any, chunk: dict[str, Any]) -> None:
        raise NotImplementedError

    async def publish_done(self, *, exchange: Any, finish_reason: str) -> None:
        raise NotImplementedError


class SSEPublisher(_BasePublisher):
    """Складывает чанки в exchange.properties['sse_events'] для SSE-роута."""

    PROPERTY = "sse_events"

    async def publish_chunk(self, *, exchange: Any, chunk: dict[str, Any]) -> None:
        events = exchange.properties.get(self.PROPERTY)
        if events is None:
            events = []
            exchange.set_property(self.PROPERTY, events)
        events.append({"event": "delta", "data": chunk["delta"]})

    async def publish_done(self, *, exchange: Any, finish_reason: str) -> None:
        events = exchange.properties.get(self.PROPERTY) or []
        events.append({"event": "done", "data": finish_reason})
        exchange.set_property(self.PROPERTY, events)


class WSPublisher(_BasePublisher):
    """Шлёт чанки через WebSocket-канал из exchange.properties['ws_send']."""

    SEND_PROPERTY = "ws_send"

    async def publish_chunk(self, *, exchange: Any, chunk: dict[str, Any]) -> None:
        send = exchange.properties.get(self.SEND_PROPERTY)
        if send is None:
            return
        await send({"type": "delta", "delta": chunk["delta"]})

    async def publish_done(self, *, exchange: Any, finish_reason: str) -> None:
        send = exchange.properties.get(self.SEND_PROPERTY)
        if send is None:
            return
        await send({"type": "done", "finish_reason": finish_reason})


class WebhookChunkedPublisher(_BasePublisher):
    """Шлёт чанки в webhook URL через httpx с timeout."""

    def __init__(
        self, *, url_property: str = "webhook_url", timeout: float = 5.0
    ) -> None:
        self._url_property = url_property
        self._timeout = timeout

    async def _send(self, url: str, payload: dict[str, Any]) -> None:
        try:
            import httpx

            from src.backend.core.net import OutboundHttpClient
        except ImportError:
            return
        try:
            timeout = httpx.Timeout(self._timeout)
            async with OutboundHttpClient(timeout=timeout) as client:
                await asyncio.wait_for(
                    client.post(url, content=orjson.dumps(payload)),
                    timeout=self._timeout,
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("WebhookChunkedPublisher: send failed: %s", exc)

    async def publish_chunk(self, *, exchange: Any, chunk: dict[str, Any]) -> None:
        url = exchange.properties.get(self._url_property)
        if not url:
            return
        await self._send(url, {"type": "delta", "delta": chunk["delta"]})

    async def publish_done(self, *, exchange: Any, finish_reason: str) -> None:
        url = exchange.properties.get(self._url_property)
        if not url:
            return
        await self._send(url, {"type": "done", "finish_reason": finish_reason})
