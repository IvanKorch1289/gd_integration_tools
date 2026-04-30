"""W23.8 — :class:`WebSocketSource` (reverse client-stream).

Подключается как WebSocket-клиент к удалённому endpoint и эмитит каждое
полученное сообщение как ``SourceEvent``. Используется для приёма
push-потоков (биржевые тикеры, чат-серверы и т.п.). Использует библиотеку
``websockets`` (если не установлена — поднимет понятный ImportError).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from src.core.interfaces.source import EventCallback, SourceEvent, SourceKind
from src.infrastructure.sources._lifecycle import graceful_cancel

__all__ = ("WebSocketSource",)

logger = logging.getLogger("infrastructure.sources.websocket")


class WebSocketSource:
    """WebSocket-client Source.

    Args:
        source_id: Уникальный id.
        url: ``ws://`` или ``wss://`` endpoint.
        decode_json: Декодировать ли входящие текстовые сообщения как JSON.
        reconnect_delay_seconds: Задержка перед попыткой реконнекта.
    """

    kind: SourceKind = SourceKind.WEBSOCKET

    def __init__(
        self,
        source_id: str,
        *,
        url: str,
        decode_json: bool = True,
        reconnect_delay_seconds: float = 2.0,
    ) -> None:
        self.source_id = source_id
        self._url = url
        self._decode = decode_json
        self._reconnect = reconnect_delay_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def start(self, on_event: EventCallback) -> None:
        if self._task is not None and not self._task.done():
            raise RuntimeError(f"WebSocketSource(id={self.source_id!r}) уже запущен")
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(on_event))
        logger.info("WebSocketSource started: id=%s url=%s", self.source_id, self._url)

    async def stop(self) -> None:
        self._stop_event.set()
        await graceful_cancel(self._task, source_id=self.source_id)
        self._task = None

    async def health(self) -> bool:
        return self._task is not None and not self._task.done()

    def _decode_payload(self, msg: Any) -> Any:
        if isinstance(msg, bytes):
            return msg
        if not self._decode:
            return msg
        try:
            import orjson

            return orjson.loads(msg)
        except Exception:
            return msg

    async def _run(self, on_event: EventCallback) -> None:
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError(
                "websockets не установлен; добавь его в pyproject.toml."
            ) from exc

        while not self._stop_event.is_set():
            try:
                async with websockets.connect(self._url) as ws:
                    async for msg in ws:
                        if self._stop_event.is_set():
                            break
                        event = SourceEvent(
                            source_id=self.source_id,
                            kind=self.kind,
                            payload=self._decode_payload(msg),
                            event_time=datetime.now(UTC),
                            metadata={"url": self._url},
                        )
                        try:
                            await on_event(event)
                        except Exception as exc:
                            logger.error("WebSocketSource on_event failed: %s", exc)
            except Exception as exc:
                logger.warning("WebSocketSource %s: connection error: %s", self._url, exc)
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self._reconnect
                    )
                except TimeoutError:
                    continue
