"""Graceful shutdown middleware (W1+W2, ledger REOPENED M5-#2).

S91 создал BaseHTTPMiddleware-версию с тремя дефектами:
1. не была зарегистрирована в ``MiddlewareRegistry`` (drain не работал);
2. in-flight счётчик был инстанс-локальным и не инкрементировался —
   ``get_in_flight_count()`` всегда возвращал 0;
3. ``drain()`` при 0 in-flight возвращался, не выставив shutdown-флаг —
   новые запросы продолжали приниматься.

W1: pure-ASGI реализация (BaseHTTPMiddleware несовместим с проектным
chain'ом на /docs, /redoc, /metrics — см. gzip_compression_excluding).
W2: единый глобальный ``_INFLIGHT_COUNTER`` (инкремент в ``__call__``).

Drain вызывается из ``plugins/composition/lifecycle/shutdown.py``
(step 0) — in-flight HTTP завершаются, пока подсистемы ещё живы.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Final

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from src.backend.entrypoints.middlewares._registry import _INFLIGHT_COUNTER

__all__ = (
    "GracefulShutdownMiddleware",
    "get_graceful_shutdown",
    "get_in_flight_count",
)

_logger = logging.getLogger(__name__)

_DEFAULT_DRAIN_TIMEOUT: Final[float] = 30.0  # M5-#2: 30s graceful drain

_DRAIN_503_BODY: Final[dict[str, str]] = {
    "error": "service_draining",
    "message": "Service is shutting down, retry later",
}


class GracefulShutdownMiddleware:
    """Pure-ASGI gate: drain in-flight HTTP, новые запросы → 503 (W1).

    Регистрируется с максимальным order (880 → outermost в LIFO-цепочке
    реестра): gate срабатывает до любой обработки. Некомендуемых
    исключений нет — во время drain LB должен видеть 503 на всё, включая
    /health. WS/lifespan проходят без gate (у WS свой TaskRegistry).
    """

    def __init__(self, app: ASGIApp, drain_timeout: float = _DEFAULT_DRAIN_TIMEOUT) -> None:
        self.app = app
        self.drain_timeout = drain_timeout
        self._shutting_down = False
        self._drain_event = asyncio.Event()
        self._drain_event.set()  # Initial state: not draining
        global _ACTIVE_INSTANCE
        _ACTIVE_INSTANCE = self

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if self._shutting_down:
            response = JSONResponse(
                status_code=503,
                content=_DRAIN_503_BODY,
                headers={"Retry-After": "5"},
            )
            await response(scope, receive, send)
            return

        _INFLIGHT_COUNTER.value += 1  # W2: глобальный счётчик
        self._drain_event.clear()
        try:
            await self.app(scope, receive, send)
        finally:
            _INFLIGHT_COUNTER.value -= 1
            if _INFLIGHT_COUNTER.value == 0:
                self._drain_event.set()

    async def drain(self) -> None:
        """Выставить shutdown-флаг и ждать in_flight = 0 ИЛИ timeout.

        Флаг выставляется ВСЕГДА (в т.ч. при 0 in-flight) — иначе новые
        запросы продолжают приниматься после начала shutdown.
        """
        self._shutting_down = True

        if _INFLIGHT_COUNTER.value == 0:
            _logger.info("graceful_drain: no in-flight requests")
            return

        _logger.info(
            "graceful_drain: starting, in_flight=%d, timeout=%.1fs",
            _INFLIGHT_COUNTER.value,
            self.drain_timeout,
        )
        try:
            await asyncio.wait_for(
                self._drain_event.wait(),
                timeout=self.drain_timeout,
            )
            _logger.info("graceful_drain: complete, all requests finished")
        except TimeoutError:
            _logger.warning(
                "graceful_drain: timeout, in_flight=%d (forced shutdown)",
                _INFLIGHT_COUNTER.value,
            )


_ACTIVE_INSTANCE: GracefulShutdownMiddleware | None = None


def get_graceful_shutdown() -> GracefulShutdownMiddleware | None:
    """Инстанс middleware текущего приложения (None до регистрации)."""
    return _ACTIVE_INSTANCE


def get_in_flight_count() -> int:
    """Публичный хелпер для health-check интеграции (M5-#9 / W2)."""
    return _INFLIGHT_COUNTER.value
