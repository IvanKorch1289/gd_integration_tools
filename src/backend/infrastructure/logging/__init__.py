"""Пакет infrastructure.logging — backends + router + factory.

Wave 2.5: вводит ``LogSink``-стек поверх structlog.
Совместимость со старыми точками входа (``get_logger``, ``configure_logging``,
``logging.getLogger``) сохранена.
"""

from __future__ import annotations

from src.backend.infrastructure.logging.factory import (
    configure_logging,
    get_logger,
    init_log_sinks,
    shutdown_log_sinks,
    shutdown_logging,
)
from src.backend.infrastructure.logging.router import (
    SinkRouter,
    build_sinks_for_profile,
    configure_router,
    get_router,
    is_router_configured,
    reset_router,
    route_to_sinks,
)

__all__ = (
    "SinkRouter",
    "build_sinks_for_profile",
    "configure_logging",
    "configure_router",
    "get_logger",
    "get_router",
    "init_log_sinks",
    "is_router_configured",
    "reset_router",
    "route_to_sinks",
    "shutdown_log_sinks",
    "shutdown_logging",
)
