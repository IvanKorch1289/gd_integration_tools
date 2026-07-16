"""WSSink — outbound WebSocket publish (Wave 3.1).

Этот sink работает как **клиент** WebSocket: подключается к
внешнему серверу по URL и публикует payload. Полностью отдельный
канал от inbound WS-handler'а (``entrypoints/websocket/ws_handler.py``)
и от ``ws_manager`` — Pre-Wave ДО зафиксировал риск race condition,
если оба используют один и тот же connection pool. Здесь —
короткоживущее соединение через ``websockets.connect()`` per-send.

Длинноживущие сессии (с переподключением и backoff) — отдельная
тема для Wave 7/9; здесь — минимальная семантика «open → send →
close».
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from src.backend.core.interfaces.sink import Sink, SinkKind, SinkResult
from src.backend.core.resilience.connector_breaker import with_breaker
from src.backend.core.resilience.connector_retry import with_retry
from src.backend.core.security.connector_auth import require_capability
from src.backend.infrastructure.clients.base_connector import HealthResult
from src.backend.dsl.codec.json import dumps_str

__all__ = ("WsSink",)


@dataclass(slots=True)
class WsSink(Sink):
    """Outbound WebSocket sink: открыть → send → close.

    Args:
        sink_id: Уникальный идентификатор.
        url: WebSocket URL (``ws://`` / ``wss://``).
        timeout: Таймаут на connect+send в секундах.
        extra_headers: Дополнительные заголовки handshake.
    """

    sink_id: str
    url: str
    timeout: float = 10.0
    extra_headers: dict[str, str] = field(default_factory=dict)
    kind: SinkKind = field(default=SinkKind.WS, init=False)

    @with_breaker("ws_sink")
    @with_retry(max_attempts=3)
    @require_capability("ws.send", action="write")
    async def send(self, payload: Any) -> SinkResult:
        """Сериализует payload (JSON) и публикует через короткое WS-соединение."""
        try:
            import websockets
        except ImportError:
            return SinkResult(ok=False, details={"error": "websockets not installed"})

        text = payload if isinstance(payload, str) else dumps_str(payload)

        try:
            async with websockets.connect(
                self.url,
                additional_headers=list(self.extra_headers.items()) or None,
                open_timeout=self.timeout,
                close_timeout=self.timeout,
            ) as ws:
                await ws.send(text)
        except Exception as exc:
            return SinkResult(
                ok=False, details={"error": str(exc) or exc.__class__.__name__}
            )

        return SinkResult(ok=True, details={"bytes": len(text), "url": self.url})

    async def health(self, mode: str = "fast") -> HealthResult:
        """Health: успешный handshake + close без отправки данных."""
        try:
            import websockets
        except ImportError:
            return HealthResult.failed(error="websockets not installed", mode=mode)
        start = time.perf_counter()
        try:
            async with websockets.connect(
                self.url,
                additional_headers=list(self.extra_headers.items()) or None,
                open_timeout=self.timeout,
                close_timeout=self.timeout,
            ):
                pass
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.failed(
                error=f"{type(exc).__name__}: {exc}", mode=mode, latency_ms=latency_ms
            )
        latency_ms = (time.perf_counter() - start) * 1000.0
        return HealthResult.ok(latency_ms=latency_ms, mode=mode)
