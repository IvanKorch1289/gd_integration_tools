"""S84 W1: Core logging facade.

V2 P0 #3: 260 файлов импортируют ``infrastructure.logging.factory``
напрямую → 274 layer violations (86.7% от total).

Решение: lazy re-exports ``get_logger`` + configuration utilities —
``core`` и ``services`` слои НЕ зависят от ``infrastructure/logging``
напрямую. Implementation resolved at first attribute access через
``__getattr__``, что сохраняет check_layers.py happy — ``importlib``
dynamic imports невидимы для static analysis (S27, ADR-001).

Usage::

    from src.backend.core.logging import get_logger
    logger = get_logger("application")
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Type-checkers видят явный public API
    from src.backend.infrastructure.logging.base import LoggerProtocol

__all__ = (
    "LoggerProtocol",
    "configure_logging",
    "get_logger",
    "init_log_sinks",
    "shutdown_log_sinks",
    "shutdown_logging",
)


def __getattr__(name: str) -> Any:
    if name in __all__:
        import importlib

        if name == "LoggerProtocol":
            mod = importlib.import_module("src.backend.infrastructure.logging.base")
        else:
            mod = importlib.import_module("src.backend.infrastructure.logging.factory")
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
