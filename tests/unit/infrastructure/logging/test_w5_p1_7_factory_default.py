"""Focused tests: factory auto-detect structlog (MINIMAX W5 P1-7, cycle 152).

Verifies that :func:`infrastructure.logging.factory.get_logger` (cold-start
fallback) prefers :class:`StructlogGraylogBackend` over StdlibLogger when
structlog is installed (default in this project per ADR-0084).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from src.backend.infrastructure.logging import factory
from src.backend.infrastructure.logging.structlog_backend import StructlogLogger


@pytest.fixture(autouse=True)
def _reset_factory_backend() -> None:
    """Reset module-level ``_backend`` cache between tests."""
    factory._backend = None
    yield
    factory._backend = None


class TestFactoryAutoDetectBackend:
    """``_detect_available_backend`` returns 'structlog' if installed."""

    def test_returns_structlog_when_importable(self) -> None:
        """structlog is in pyproject.toml — auto-detect returns 'structlog'."""
        backend = factory._detect_available_backend()
        assert backend == "structlog"

    def test_returns_stdlib_when_structlog_missing(self) -> None:
        """If structlog import fails, fallback to stdlib."""

        # Симулируем недоступность structlog.
        import builtins

        real_import = builtins.__import__

        def _import_block_structlog(
            name: str, *args: object, **kwargs: object
        ) -> object:
            if name =="structlog":
                raise ImportError("simulated structlog unavailability")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=_import_block_structlog):
            backend = factory._detect_available_backend()
        assert backend =="stdlib"


class TestGetLoggerUsesStructlogByDefault:
    """``get_logger()`` (cold-start, no prior configure_logging) prefers structlog."""

    def test_get_logger_returns_structlog_logger(self) -> None:
        """First call to get_logger (without configure_logging) должен вернуть StructlogLogger."""
        log = factory.get_logger("test.w5_p1_7.cold_start")
        assert isinstance(log, StructlogLogger)
        assert type(log).__module__ == "src.backend.infrastructure.logging.structlog_backend"

    def test_get_logger_kwargs_api_works(self) -> None:
        """structlog kwargs API (``logger.info('msg', key=val)``) работает."""
        log = factory.get_logger("test.w5_p1_7.kwargs")
        # Не должен raise (PII filter может write warning, но не crash).
        log.info("test message", extra_field="value", iteration=152)

    def test_get_logger_positional_args_formatting(self) -> None:
        """stdlib-style ``logger.info('msg %s', arg)`` работает (Sprint 60 W1 compat shim)."""
        log = factory.get_logger("test.w5_p1_7.posarg")
        log.warning("warning with %s substitution", "arg_value")


class TestGetLoggerFallbackWhenStructlogUnavailable:
    """Если structlog недоступен — fallback на stdlib (graceful degradation)."""

    def test_stdlib_used_when_structlog_unavailable(self) -> None:
        """С ``structlog`` в ImportError — get_logger возвращает stdlib logger."""
        import builtins

        real_import = builtins.__import__

        def _import_block_structlog(
            name: str, *args: object, **kwargs: object
        ) -> object:
            if name =="structlog":
                raise ImportError("simulated")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=_import_block_structlog):
            log = factory.get_logger("test.w5_p1_7.fallback")
        # Stdlib backend — ``StdlibLogger`` wrapper над ``logging.Logger``.
        from src.backend.infrastructure.logging.stdlib_backend import StdlibLogger
        assert isinstance(log, StdlibLogger)


class TestStructlogBackendLazyImport:
    """structlog_backend lazy-importы устраняют circular import (W5 P1-7 fix)."""

    def test_structlog_backend_configure_uses_lazy_processor(self) -> None:
        """``StructlogGraylogBackend.configure()`` использует lazy processor вместо eager import.

        До W5 P1-7: ``from router import route_to_sinks`` в top-level configure()
        → circular import при cold-start (router → core.interfaces → get_logger → configure).
        После W5 P1-7: lazy import через ``_route_to_sinks_lazy`` processor.
        """
        import inspect

        from src.backend.infrastructure.logging.structlog_backend import (
            StructlogGraylogBackend,
        )

        source = inspect.getsource(StructlogGraylogBackend.configure)
        # Lazy processor wrappers (W5 P1-7 fix) должны присутствовать.
        assert "_route_to_sinks_lazy" in source
        assert "_mask_pii_lazy" in source
        # И в shared_processors они должны быть в списке.
        assert "_route_to_sinks_lazy," in source or "_route_to_sinks_lazy\n" in source
        assert "_mask_pii_lazy," in source or "_mask_pii_lazy\n" in source

    def test_structlog_logger_works_after_cold_start(self) -> None:
        """Cold-start get_logger → StructlogLogger — можно сразу логировать.

        До W5 P1-7 fix circular import мешал configure() в первый раз.
        """
        log = factory.get_logger("test.w5_p1_7.cold_start_works")
        # kwargs API работает.
        log.info("after_cold_start", iteration=1)
        # positional args (%s formatting) тоже работает (Sprint 60 W1 compat shim).
        log.warning("positional %s works", "substitution")