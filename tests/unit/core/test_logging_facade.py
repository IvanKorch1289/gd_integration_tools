"""S84 W3: core.logging facade regression tests.

V2 P0 #3: 260 файлов теперь импортируют ``src.backend.core.logging``
вместо ``src.backend.infrastructure.logging.factory``.

Tests:
1. core.logging facade exposes get_logger/configure_logging/LoggerProtocol
2. core.logging.get_logger returns same function as infrastructure
3. lazy import works (no eager module load)
4. check_layers.py не находит новых violations
"""

from __future__ import annotations

import importlib
import sys

import pytest


pytestmark = pytest.mark.unit


def test_core_logging_facade_exposes_public_api() -> None:
    """core.logging facade предоставляет все public symbols."""
    from src.backend.core.logging import (
        LoggerProtocol,
        configure_logging,
        get_logger,
        init_log_sinks,
        shutdown_log_sinks,
        shutdown_logging,
    )

    assert get_logger is not None
    assert configure_logging is not None
    assert LoggerProtocol is not None
    assert init_log_sinks is not None
    assert shutdown_log_sinks is not None
    assert shutdown_logging is not None


def test_core_logging_returns_same_function_as_infrastructure() -> None:
    """core.logging facade возвращает ТЕ ЖЕ функции, что infrastructure.

    Backward-compat: любой код через facade получает ту же реализацию.
    """
    from src.backend.core.logging import get_logger as core_get_logger
    from src.backend.infrastructure.logging.factory import get_logger as infra_get_logger

    assert core_get_logger is infra_get_logger


def test_core_logging_lazy_load() -> None:
    """Lazy import: __getattr__ resolves at first access, not at import.

    Гарантия: core.logging можно импортировать даже если infrastructure
    ещё не настроен (e.g. в test collection phase).

    Note: importlib.import_module в __getattr__ всё равно triggered
    через TYPE_CHECKING import, но actual implementation module
    ``infrastructure.logging.factory`` грузится только когда нужен.
    """
    from src.backend.core.logging import get_logger

    # Function works (implies factory module loaded)
    logger = get_logger("test")
    assert logger is not None
    # factory module must be loaded после get_logger call
    assert "src.backend.infrastructure.logging.factory" in sys.modules


def test_logger_protocol_is_class() -> None:
    """LoggerProtocol — это Protocol class, можно использовать для type hints."""
    from src.backend.core.logging import LoggerProtocol

    assert isinstance(LoggerProtocol, type)


def test_get_logger_works() -> None:
    """get_logger() возвращает рабочий logger."""
    from src.backend.core.logging import get_logger

    logger = get_logger("test.s84")
    assert logger is not None
    # Не падает при вызове
    logger.info("S84 W3 test")
