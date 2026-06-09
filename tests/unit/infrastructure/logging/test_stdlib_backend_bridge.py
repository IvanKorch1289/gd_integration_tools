"""Тесты bridge StdlibLoggingBackend → logging_service (Wave 2)."""

# ruff: noqa: S101

from __future__ import annotations

import logging

import pytest

from src.backend.infrastructure.logging.stdlib_backend import StdlibLoggingBackend


@pytest.fixture
def backend() -> StdlibLoggingBackend:
    return StdlibLoggingBackend()


def test_get_logger_returns_stdlib_logger(backend: StdlibLoggingBackend) -> None:
    """get_logger возвращает StdlibLogger, оборачивающий stdlib Logger."""
    logger = backend.get_logger("database")
    assert isinstance(logger._inner, logging.Logger)


def test_stdlib_logger_supports_positional_args(backend: StdlibLoggingBackend) -> None:
    """StdlibLogger должен поддерживать positional args (template %s)."""
    logger = backend.get_logger("redis")
    # Не должно падать с TypeError.
    logger.warning("Redis cache недоступен: %s", "connection refused")


def test_stdlib_logger_supports_exc_info(backend: StdlibLoggingBackend) -> None:
    """StdlibLogger должен поддерживать exc_info=True."""
    logger = backend.get_logger("redis")
    try:
        raise RuntimeError("fail")
    except Exception:
        logger.error("Ошибка: %s", "msg", exc_info=True)


def test_get_logger_returns_stdlib_logger_directly(
    backend: StdlibLoggingBackend,
) -> None:
    """Sprint 38: get_logger возвращает stdlib logger напрямую без legacy manager."""
    logger = backend.get_logger("database")
    assert isinstance(logger._inner, logging.Logger)
    assert logger._inner.name == "database"
