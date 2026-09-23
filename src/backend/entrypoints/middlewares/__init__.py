"""Middlewares package — pure ASGI слой между entrypoints и services.

См. ADR-0062 (Sprint 9 K5 W7): этот пакет работает с raw HTTP-фреймворком
(Starlette ``ASGIApp``); не путать с
:mod:`src.backend.services.execution.middlewares` — последний работает
с типизированным ``DispatchContext`` после парсинга в action invocation.
"""

from __future__ import annotations

# S91 M5-#2: graceful shutdown middleware export
from src.backend.entrypoints.middlewares.graceful_shutdown import (
    GracefulShutdownMiddleware,
    get_in_flight_count,
)

__all__ = ("GracefulShutdownMiddleware", "get_in_flight_count")
