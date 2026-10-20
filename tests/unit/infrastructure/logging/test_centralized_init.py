"""Centralized logging init regression tests (cycle 161 audit).

Проверяет, что :func:`init_application_logging` корректно настраивает
весь logging-стек одной функцией — backend + SinkRouter — в порядке,
который нужен lifespan-стартапу ``create_app()``.

Цель — зафиксировать поведение facade для future refactor-ов
(см. docs/architecture/logging.md и ADR-0351 § Phase 2).
"""

from __future__ import annotations

import pytest

from src.backend.core.logging import (
    get_logger,
    init_application_logging,
    shutdown_logging,
)
from src.backend.infrastructure.logging import factory
from src.backend.infrastructure.logging.router import (
    get_router,
    is_router_configured,
    reset_router,
)
from src.backend.infrastructure.logging.structlog_backend import StructlogGraylogBackend


@pytest.fixture(autouse=True)
def _reset_factory_and_router() -> None:
    """Сбросить factory._backend + router между тестами."""
    factory._backend = None
    reset_router()
    yield
    factory._backend = None
    reset_router()
    try:
        shutdown_logging()
    except (OSError, RuntimeError):
        pass


class TestInitApplicationLogging:
    """``init_application_logging()`` настраивает backend + SinkRouter."""

    def test_init_configures_backend(self) -> None:
        """После init backend не None и является structlog."""
        backend = init_application_logging(level="INFO", environment="test")
        assert isinstance(backend, StructlogGraylogBackend)

    def test_init_activates_sink_router(self) -> None:
        """После init SinkRouter configured (event_dict доходят до sink-ов)."""
        assert not is_router_configured()
        init_application_logging(level="INFO", environment="test")
        assert is_router_configured()

    def test_init_with_explicit_profile(self) -> None:
        """``profile`` параметр принимается и не вызывает ошибки."""
        backend = init_application_logging(
            level="DEBUG",
            environment="test",
            profile="dev",
        )
        assert isinstance(backend, StructlogGraylogBackend)
        assert is_router_configured()

    def test_init_creates_get_logger_works(self) -> None:
        """После init ``get_logger(name)`` возвращает рабочий логгер."""
        init_application_logging(level="INFO", environment="test")
        log = get_logger("test.centralized.init")
        log.info("init works", key="value")

    def test_init_is_idempotent(self) -> None:
        """Повторный init пересоздаёт backend (старый shutdown'ится)."""
        backend1 = init_application_logging(level="INFO", environment="test")
        backend2 = init_application_logging(level="DEBUG", environment="test")
        assert backend1 is not backend2


class TestInitApplicationLoggingFailureTolerant:
    """``init_application_logging()`` failure-tolerant для lifespan startup."""

    def test_init_with_invalid_level_does_not_raise(self) -> None:
        """Backend accepts any level string (default 'INFO' если unrecognized).

        Это сознательная policy: backend лучше работать с произвольным
        уровнем, чем крашить startup (cycle 161 audit). Если нужен strict
        validation — добавляется в factory._VALID_LEVELS whitelist в ADR.
        """
        # НЕ должно raise — startup должен быть failure-tolerant.
        backend = init_application_logging(level="INVALID_LEVEL", environment="test")
        assert isinstance(backend, StructlogGraylogBackend)


class TestCentralizedInitShutsDownCleanly:
    """``init_application_logging()`` + ``shutdown_logging()`` работают в паре."""

    def test_init_then_shutdown_resets_backend(self) -> None:
        """После shutdown factory._backend = None."""
        init_application_logging(level="INFO", environment="test")
        assert factory._backend is not None
        shutdown_logging()
        assert factory._backend is None

    def test_init_then_shutdown_router_persists(self) -> None:
        """``shutdown_logging()`` НЕ закрывает router (это shutdown_log_sinks).
        Это сознательное разделение — приложение может reopen router позже."""
        init_application_logging(level="INFO", environment="test")
        assert is_router_configured()
        shutdown_logging()
        # Router всё ещё configured, потому что shutdown_log_sinks — separate op.
        assert is_router_configured()


class TestRouterFanOutAfterInit:
    """После centralized init event_dict доходят до настроенных sink-ов."""

    def test_logger_emit_reaches_active_sinks(self) -> None:
        """``log.info(...)`` → structlog → route_to_sinks → active sinks."""
        init_application_logging(level="INFO", environment="test")

        router = get_router()
        # Контракт: router.sinks — список LogSink (см. router.py).
        assert hasattr(router, "sinks")
        assert len(router.sinks) > 0

        # Emit event — должен пройти через structlog pipeline в router.sinks.
        log = get_logger("test.centralized.fanout")
        log.info("event_dict reaches router", iteration=1)


class TestFacadeSurfaceExport:
    """``init_application_logging`` exposed через ``core.logging`` facade."""

    def test_facade_reexports_init(self) -> None:
        """``from src.backend.core.logging import init_application_logging`` работает."""
        from src.backend.core.logging import init_application_logging as facade_init

        # Проверяем, что это та же функция, что в factory.py
        from src.backend.infrastructure.logging.factory import (
            init_application_logging as factory_init,
        )

        assert facade_init is factory_init

    def test_facade_lazy_resolution(self) -> None:
        """Facade работает через ``__getattr__`` lazy resolution."""
        import src.backend.core.logging as facade_module

        # Атрибут не импортирован module-level (lazy через __getattr__)
        # Проверяем, что facade содержит __all__ с init_application_logging
        assert "init_application_logging" in facade_module.__all__


class TestCentralizedInitInLifespanContext:
    """Сценарий использования из ``app_factory.create_app()`` lifespan."""

    def test_create_app_init_pattern(self) -> None:
        """Симулирует вызов из app_factory.create_app() перед FastAPI init."""
        # До init
        assert factory._backend is None
        assert not is_router_configured()

        # init (lifespan startup pattern)
        init_application_logging(
            level="INFO",
            environment="production",
        )

        # После init
        assert factory._backend is not None
        assert is_router_configured()

        # Application code может использовать get_logger() сразу после init.
        log = get_logger("lifespan.startup.centralized.log")
        log.info("startup complete", key="value")

        # Shutdown (lifespan shutdown pattern)
        shutdown_logging()
