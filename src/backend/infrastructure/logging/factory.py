"""Фабрика логирования — единая точка получения логгеров.

Автоматически выбирает бэкенд:
- structlog (если установлен) — структурированные JSON-логи в Graylog
- stdlib logging (fallback) — текущая реализация через LoggerManager

Использование:
    from src.infrastructure.logging.factory import get_logger

    logger = get_logger("application")
    logger.info("Order created", order_id=123, user_id="abc")

Переключение бэкенда:
    from src.infrastructure.logging.factory import configure_logging

    # structlog → Graylog
    configure_logging(backend="structlog")

    # stdlib (по умолчанию)
    configure_logging(backend="stdlib")
"""

from typing import Any

from src.core.config.profile import AppProfileChoices
from src.infrastructure.logging.base import BaseLoggerBackend, LoggerProtocol

__all__ = (
    "configure_logging",
    "get_logger",
    "init_log_sinks",
    "shutdown_log_sinks",
    "shutdown_logging",
)

_backend: BaseLoggerBackend | None = None


def _create_backend(name: str) -> BaseLoggerBackend:
    if name == "structlog":
        try:
            from src.infrastructure.logging.structlog_backend import (
                StructlogGraylogBackend,
            )

            return StructlogGraylogBackend()
        except ImportError:
            pass

    from src.infrastructure.logging.stdlib_backend import StdlibLoggingBackend

    return StdlibLoggingBackend()


def configure_logging(backend: str = "auto", **settings: Any) -> BaseLoggerBackend:
    """Настраивает систему логирования.

    Args:
        backend: ``"structlog"``, ``"stdlib"`` или ``"auto"``
            (structlog если установлен, иначе stdlib).
        **settings: Передаются в backend.configure().

    Returns:
        Настроенный бэкенд.
    """
    global _backend

    if _backend is not None:
        _backend.shutdown()

    if backend == "auto":
        try:
            import structlog  # noqa: F401

            backend = "structlog"
        except ImportError:
            backend = "stdlib"

    _backend = _create_backend(backend)
    _backend.configure(**settings)
    return _backend


def get_logger(name: str) -> LoggerProtocol:
    """Возвращает логгер по имени.

    Если бэкенд ещё не настроен — создаёт stdlib fallback.

    Args:
        name: Имя логгера (например ``"application"``,
            ``"database"``, ``"redis"``).

    Returns:
        Логгер, совместимый с LoggerProtocol.
    """
    global _backend

    if _backend is None:
        _backend = _create_backend("stdlib")
        _backend.configure()

    return _backend.get_logger(name)


def shutdown_logging() -> None:
    """Корректно завершает систему логирования."""
    global _backend
    if _backend is not None:
        _backend.shutdown()
        _backend = None


def init_log_sinks(profile: AppProfileChoices | None = None, **kwargs: Any) -> None:
    """Инициализировать профильный :class:`SinkRouter`.

    Wave 2.5: должен вызываться один раз на старте приложения (lifespan
    startup). После инициализации structlog-processor :func:`route_to_sinks`
    начнёт пересылать event_dict во все настроенные sink-и (``ConsoleJson``,
    ``DiskRotating``, ``GraylogGelf``).

    Аргументы:
        profile: явный профиль; если ``None`` — берётся из ``APP_PROFILE``.
        **kwargs: проброс параметров в :func:`build_sinks_for_profile`
            (например, ``disk_path``, ``graylog_host``).

    Идемпотентно: повторный вызов заменит активный набор sink-ов
    (старые при этом НЕ закрываются — это ответственность вызывающего
    кода, обычно ``shutdown_log_sinks``).
    """
    from src.infrastructure.logging.router import (
        build_sinks_for_profile,
        configure_router,
    )

    sinks = build_sinks_for_profile(profile, **kwargs)
    configure_router(sinks)


async def shutdown_log_sinks() -> None:
    """Корректно закрыть все sink-и активного :class:`SinkRouter`.

    Должен вызываться в lifespan shutdown ПЕРЕД остановкой остальной
    инфраструктуры — гарантирует, что финальные логи стартапа/штатной
    остановки доедут до sink-ов и буферы сбросятся.

    Если router ещё не инициализирован — no-op.
    """
    from src.infrastructure.logging.router import (
        get_router,
        is_router_configured,
        reset_router,
    )

    if not is_router_configured():
        return
    await get_router().aclose()
    reset_router()
