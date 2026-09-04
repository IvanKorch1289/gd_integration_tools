"""Graceful shutdown middleware (S91 M5-#2 hardening).

S91 M5-#2: drain in-flight requests при shutdown signal.

Sprint 91 hardening для M5 done-критерий (10 high-load items):
- ASGI middleware tracking active request count
- При lifespan shutdown (lifespan.shutdown), middleware waits до
  in_flight_count = 0 (max 30s timeout)
- 503 Service Unavailable для new requests during draining

Pattern (Ponytail): thin wrapper around starlette BaseHTTPMiddleware,
no abstractions. Uses single global counter + asyncio.Event.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Final

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

__all__ = ("GracefulShutdownMiddleware", "get_in_flight_count")

_logger = logging.getLogger(__name__)

_DEFAULT_DRAIN_TIMEOUT: Final[float] = 30.0  # S91 M5-#2: 30s graceful drain


class GracefulShutdownMiddleware(BaseHTTPMiddleware):
    """Drain in-flight requests при ASGI lifespan shutdown (S91 M5-#2).

    При app shutdown (lifespan.shutdown), middleware ждёт до
    in_flight_count = 0 ИЛИ timeout. В это время new requests → 503.

    Attributes:
        drain_timeout: Maximum wait time для drain (default 30s).

    Usage в Starlette app::

        from src.backend.entrypoints.middlewares.graceful_shutdown import GracefulShutdownMiddleware
        app.add_middleware(GracefulShutdownMiddleware, drain_timeout=30.0)

    Honoring S91 M5-#2: explicit shutdown coordination.
    """

    def __init__(self, app, drain_timeout: float = _DEFAULT_DRAIN_TIMEOUT) -> None:
        super().__init__(app)
        self.drain_timeout = drain_timeout
        self._in_flight = 0
        self._shutting_down = False
        self._drain_event = asyncio.Event()
        self._drain_event.set()  # Initial state: not draining

    async def dispatch(self, request: Request, call_next) -> Response:
        """Per-request hook: track active count, return 503 if draining."""
        if self._shutting_down:
            return JSONResponse(
                status_code=503,
                content={
                    "error": "service_draining",
                    "message": "Service is shutting down, retry later",
                },
                headers={"Retry-After": "5"},
            )

        self._in_flight += 1
        self._drain_event.clear()
        try:
            response = await call_next(request)
        finally:
            self._in_flight -= 1
            if self._in_flight == 0:
                self._drain_event.set()
        return response

    async def drain(self) -> None:
        """Wait до in_flight = 0 (S91 M5-#2).

        Вызывается из lifespan.shutdown. Возвращает когда все
        requests complete ИЛИ timeout.
        """
        if self._in_flight == 0:
            _logger.info("graceful_drain: no in-flight requests")
            return

        self._shutting_down = True
        _logger.info(
            "graceful_drain: starting, in_flight=%d, timeout=%.1fs",
            self._in_flight,
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
                self._in_flight,
            )


def get_in_flight_count() -> int:
    """Public helper для health-check integration (M5-#9).

    Returns 0 если middleware не установлен (fallback).
    """
    # S91: через глобальный registry (для multi-app test scenarios)
    from src.backend.entrypoints.middlewares._registry import _INFLIGHT_COUNTER

    return _INFLIGHT_COUNTER.value
