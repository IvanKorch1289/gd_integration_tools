"""W23.6 — :class:`SoapSource` (SOAP polling-клиент через zeep).

Периодически вызывает указанный SOAP-метод и эмитит ``SourceEvent`` при
изменении ответа (по hash). По сути — :class:`PollingSource` для SOAP:
один и тот же diff-loop, но вместо HTTP GET вызывается ``client.service.<op>``.

Не реализует SOAP-server (приём входящих SOAP-вызовов уже покрыт
``entrypoints/soap/soap_handler.py``). Если нужен сервер — использовать
существующий entrypoint, который уже интегрирован с Invoker.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

from src.core.interfaces.source import EventCallback, SourceEvent, SourceKind
from src.infrastructure.sources._lifecycle import graceful_cancel

__all__ = ("SoapSource",)

logger = logging.getLogger("infrastructure.sources.soap")


class SoapSource:
    """SOAP polling-клиент с diff-детекцией.

    Args:
        source_id: Уникальный id.
        wsdl_url: Полный WSDL URL.
        operation: Имя операции (``client.service.<operation>``).
        params: Аргументы вызова операции (kwargs для service-method).
        interval_seconds: Интервал между опросами.
        emit_first: Эмитить ли первый успешный ответ (default ``True``).
    """

    kind: SourceKind = SourceKind.SOAP

    def __init__(
        self,
        source_id: str,
        *,
        wsdl_url: str,
        operation: str,
        params: dict[str, Any] | None = None,
        interval_seconds: float = 60.0,
        emit_first: bool = True,
    ) -> None:
        self.source_id = source_id
        self._wsdl = wsdl_url
        self._op = operation
        self._params = params or {}
        self._interval = interval_seconds
        self._emit_first = emit_first
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._last_hash: str | None = None

    async def start(self, on_event: EventCallback) -> None:
        if self._task is not None and not self._task.done():
            raise RuntimeError(f"SoapSource(id={self.source_id!r}) уже запущен")
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(on_event))
        logger.info(
            "SoapSource started: id=%s wsdl=%s op=%s",
            self.source_id,
            self._wsdl,
            self._op,
        )

    async def stop(self) -> None:
        self._stop_event.set()
        await graceful_cancel(self._task, source_id=self.source_id)
        self._task = None

    async def health(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _run(self, on_event: EventCallback) -> None:
        from zeep import AsyncClient
        from zeep.transports import AsyncTransport

        client = AsyncClient(self._wsdl, transport=AsyncTransport())
        try:
            first = True
            while not self._stop_event.is_set():
                try:
                    method = getattr(client.service, self._op)
                    result = await method(**self._params)
                except Exception as exc:
                    logger.warning("SoapSource %s: call failed: %s", self._op, exc)
                else:
                    body_hash = hashlib.sha256(str(result).encode()).hexdigest()
                    changed = body_hash != self._last_hash
                    if changed and (not first or self._emit_first):
                        event = SourceEvent(
                            source_id=self.source_id,
                            kind=self.kind,
                            payload=result,
                            event_time=datetime.now(UTC),
                            metadata={
                                "wsdl": self._wsdl,
                                "operation": self._op,
                                "hash": body_hash,
                            },
                        )
                        try:
                            await on_event(event)
                        except Exception as exc:
                            logger.error("SoapSource on_event failed: %s", exc)
                    self._last_hash = body_hash
                    first = False
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self._interval
                    )
                except TimeoutError:
                    pass
        finally:
            try:
                await client.transport.aclose()
            except Exception as exc:
                logger.debug("SoapSource %s: transport close warning: %s", self._wsdl, exc)
