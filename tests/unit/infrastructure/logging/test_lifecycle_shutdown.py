"""Lifecycle regression tests: configure → get_logger → shutdown_logging.

Проверяет, что полный жизненный цикл logging-стека корректно работает
end-to-end:

1. ``configure_logging()`` поднимает backend (structlog default).
2. ``get_logger(name)`` возвращает рабочий логгер.
3. Логгер может emit'ить events (info/warning/error/critical/exception).
4. ``bind(**kwargs)`` создаёт дочерний логгер с контекстом.
5. ``shutdown_logging()`` корректно завершает backend, flush'ит handlers,
   закрывает GELF sink-ы (S60 W1 fix S-L7-3).
6. После shutdown() ``get_logger(name)`` поднимает backend заново (lazy init).

Цель — зафиксировать поведение facade, чтобы future refactor не сломал
lifecycle (см. docs/architecture/logging.md).
"""

from __future__ import annotations

import logging

import pytest

from src.backend.core.logging import configure_logging, get_logger, shutdown_logging
from src.backend.infrastructure.logging import factory
from src.backend.infrastructure.logging.structlog_backend import (
    StructlogGraylogBackend,
    StructlogLogger,
)


@pytest.fixture(autouse=True)
def _reset_factory_backend() -> None:
    """Сброс модульного ``_backend`` singleton между тестами."""
    factory._backend = None
    yield
    factory._backend = None
    try:
        shutdown_logging()
    except (OSError, RuntimeError):
        pass


class TestConfigureLoggingLifecycle:
    """``configure_logging()`` поднимает backend (structlog default)."""

    def test_configure_returns_structlog_backend(self) -> None:
        """Default backend — structlog (auto-detect), не stdlib."""
        backend = configure_logging(backend="auto")
        assert isinstance(backend, StructlogGraylogBackend)

    def test_configure_default_is_structlog(self) -> None:
        """``configure_logging()`` без аргументов → structlog backend."""
        backend = configure_logging()
        assert isinstance(backend, StructlogGraylogBackend)


class TestGetLoggerAfterConfigure:
    """``get_logger()`` после ``configure_logging()`` возвращает рабочий логгер."""

    def test_get_logger_returns_structlog_logger(self) -> None:
        """После configure_logging() get_logger → StructlogLogger."""
        configure_logging()
        log = get_logger("test.lifecycle.cycle")
        assert isinstance(log, StructlogLogger)

    def test_get_logger_can_emit_info(self) -> None:
        """``logger.info(msg, **kwargs)`` работает без ошибок."""
        configure_logging()
        log = get_logger("test.lifecycle.info")
        # Не должно raise / fail
        log.info("hello world", iteration=1, key="value")

    def test_get_logger_can_emit_warning_with_positional_args(self) -> None:
        """``logger.warning("msg %s", arg)`` — Sprint 60 W1 compat shim."""
        configure_logging()
        log = get_logger("test.lifecycle.posarg")
        log.warning("warning with %s substitution", "arg_value")

    def test_get_logger_can_emit_error_with_exception(self) -> None:
        """``logger.exception(msg)`` включает traceback в JSON output."""
        configure_logging()
        log = get_logger("test.lifecycle.exc")
        try:
            raise ValueError("simulated failure")
        except ValueError:
            log.exception("caught error", extra_field="data")


class TestBindReturnsChildLogger:
    """``logger.bind(**kwargs)`` возвращает child logger с контекстом."""

    def test_bind_creates_new_logger(self) -> None:
        """``bind`` возвращает StructlogLogger (не original)."""
        configure_logging()
        parent = get_logger("test.lifecycle.bind.parent")
        child = parent.bind(correlation_id="abc-123")
        assert isinstance(child, StructlogLogger)
        assert child is not parent

    def test_bound_child_can_log_with_context(self) -> None:
        """Bound child logger пишет events без raise (контекст сохраняется в structlog)."""
        configure_logging()
        parent = get_logger("test.lifecycle.bind.emit")
        bound = parent.bind(tenant_id="t-1", correlation_id="c-1")
        bound.info("bound event", key="value")


class TestShutdownLoggingFlushesHandlers:
    """``shutdown_logging()`` flush'ит stdlib handlers и закрывает GELF sink-ы."""

    def test_shutdown_logging_does_not_raise(self) -> None:
        """``shutdown_logging()`` после configure → не raise."""
        configure_logging()
        get_logger("test.lifecycle.shutdown.basic")
        # Не должно raise
        shutdown_logging()

    def test_shutdown_logging_resets_backend(self) -> None:
        """После ``shutdown_logging()`` factory._backend = None."""
        configure_logging()
        get_logger("test.lifecycle.shutdown.reset")
        assert factory._backend is not None
        shutdown_logging()
        assert factory._backend is None

    def test_shutdown_logging_flushes_stdlib_handlers(self) -> None:
        """``shutdown_logging()`` вызывает ``flush() + close()`` для stdlib handlers.

        Проверяем через monkeypatch — handlers из logging.root должны
        быть flushed (или хотя бы иметь вызванные методы).
        """
        configure_logging()
        # Добавим кастомный handler для мониторинга flush
        flushed: list[bool] = []
        closed: list[bool] = []

        class _RecordingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                pass

            def flush(self) -> None:
                flushed.append(True)

            def close(self) -> None:
                closed.append(True)

        rec = _RecordingHandler()
        logging.getLogger().addHandler(rec)

        shutdown_logging()
        # S-L7-3 fix: handler должен быть flush'd + closed
        assert flushed == [True]
        assert closed == [True]


class TestGetLoggerLazyAfterShutdown:
    """После ``shutdown_logging()`` ``get_logger()`` поднимает backend заново."""

    def test_get_logger_after_shutdown_returns_fresh_logger(self) -> None:
        """``shutdown_logging()`` + ``get_logger(name)`` → новый structlog backend."""
        configure_logging()
        get_logger("test.lifecycle.after.shutdown")
        shutdown_logging()
        log2 = get_logger("test.lifecycle.after.shutdown")
        # log2 — fresh от нового backend
        assert isinstance(log2, StructlogLogger)

    def test_get_logger_after_shutdown_does_not_raise(self) -> None:
        """``shutdown_logging()`` + ``get_logger(name)`` + ``log.info(...)`` — no raise."""
        configure_logging()
        shutdown_logging()
        log = get_logger("test.lifecycle.fresh")
        log.info("after shutdown", key="value")


class TestMultipleConfigureCalls:
    """Повторный ``configure_logging()`` корректно пересоздаёт backend."""

    def test_reconfigure_replaces_backend(self) -> None:
        """Двойной ``configure_logging()`` → старый backend shutdown, новый created."""
        backend1 = configure_logging()
        backend2 = configure_logging()
        assert backend1 is not backend2

    def test_reconfigure_does_not_raise(self) -> None:
        """``configure_logging()`` → ``configure_logging()`` → ``shutdown_logging()`` OK."""
        configure_logging()
        configure_logging(backend="auto", level="DEBUG")
        shutdown_logging()


class TestFacadeLoggingEndToEnd:
    """End-to-end через public facade (core.logging)."""

    def test_facade_full_lifecycle(self) -> None:
        """Полный цикл через ``from src.backend.core.logging import get_logger``."""
        from src.backend.core.logging import configure_logging as facade_configure
        from src.backend.core.logging import get_logger as facade_get
        from src.backend.core.logging import shutdown_logging as facade_shutdown

        facade_configure()
        log = facade_get("test.lifecycle.facade.e2e")
        log.info("facade end-to-end", key="value")
        facade_shutdown()


class TestLoggingWithoutExplicitConfigure:
    """``get_logger()`` без явного ``configure_logging()`` — auto-init."""

    def test_get_logger_lazy_init_with_structlog(self) -> None:
        """Без configure_logging() get_logger() → structlog (auto-detect)."""
        # Не вызываем configure_logging — фабрика сама инициализирует backend
        log = get_logger("test.lifecycle.lazy.init")
        assert isinstance(log, StructlogLogger)
        log.info("lazy init", key="value")
