"""W23.9 — :class:`PollingSource` (cron + HTTP + diff).

Периодически опрашивает HTTP-эндпоинт и эмитит ``SourceEvent`` только
при изменении ответа (по hash). Без зависимости от APScheduler — внутри
обычный ``asyncio.sleep``-loop с поддержкой shutdown через
``asyncio.Event``. Для cron-выражений можно перейти на APScheduler
позже без изменения публичного API.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from src.backend.core.interfaces.source import EventCallback, SourceEvent, SourceKind
from src.backend.infrastructure.sources._lifecycle import graceful_cancel

__all__ = ("PollingSource",)

logger = logging.getLogger("infrastructure.sources.polling")


class PollingSource:
    """Periodic-poll Source с детекцией diff по hash тела ответа.

    Args:
        source_id: Уникальный id.
        url: HTTP-endpoint для опроса.
        interval_seconds: Интервал между опросами.
        method: HTTP-метод (default ``GET``).
        headers: HTTP headers для запроса.
        timeout_seconds: Таймаут одного запроса (default 10).
        emit_first: Эмитить ли первый успешный ответ (default ``True``);
            ``False`` — эмитить только начиная со второго (когда есть
            baseline для diff).
    """

    kind: SourceKind = SourceKind.POLLING

    def __init__(
        self,
        source_id: str,
        *,
        url: str,
        interval_seconds: float,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        timeout_seconds: float = 10.0,
        emit_first: bool = True,
    ) -> None:
        self.source_id = source_id
        self._url = url
        self._interval = interval_seconds
        self._method = method
        self._headers = headers or {}
        self._timeout = timeout_seconds
        self._emit_first = emit_first
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._last_hash: str | None = None

    async def start(self, on_event: EventCallback) -> None:
        if self._task is not None and not self._task.done():
            raise RuntimeError(f"PollingSource(id={self.source_id!r}) уже запущен")
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(on_event))
        logger.info(
            "PollingSource started: id=%s url=%s interval=%.1fs",
            self.source_id,
            self._url,
            self._interval,
        )

    async def stop(self) -> None:
        self._stop_event.set()
        await graceful_cancel(self._task, source_id=self.source_id)
        self._task = None
        logger.info("PollingSource stopped: id=%s", self.source_id)

    async def health(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _run(self, on_event: EventCallback) -> None:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            first = True
            while not self._stop_event.is_set():
                try:
                    payload, body_hash = await self._poll(client)
                except Exception as exc:
                    logger.warning("PollingSource %s: poll failed: %s", self._url, exc)
                else:
                    changed = body_hash != self._last_hash
                    if changed and (not first or self._emit_first):
                        event = SourceEvent(
                            source_id=self.source_id,
                            kind=self.kind,
                            payload=payload,
                            event_time=datetime.now(UTC),
                            metadata={"url": self._url, "hash": body_hash},
                        )
                        try:
                            await on_event(event)
                        except Exception as exc:
                            logger.error("PollingSource on_event failed: %s", exc)
                    self._last_hash = body_hash
                    first = False
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self._interval
                    )
                except TimeoutError:
                    pass

    async def _poll(self, client: httpx.AsyncClient) -> tuple[Any, str]:
        response = await client.request(self._method, self._url, headers=self._headers)
        response.raise_for_status()
        body = response.content
        body_hash = hashlib.sha256(body).hexdigest()
        try:
            payload: Any = response.json()
        except Exception:
            payload = body.decode(errors="replace")
        return payload, body_hash
