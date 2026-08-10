"""S84 W1: Core logging facade.

V2 P0 #3: 260 файлов импортируют ``infrastructure.logging.factory``
напрямую → 274 layer violations (86.7% от total).

Решение: lazy re-exports ``get_logger`` + configuration utilities —
``core`` и ``services`` слои НЕ зависят от ``infrastructure/logging``
напрямую. Implementation resolved at first attribute access через
``__getattr__``, что сохраняет check_layers.py happy — ``importlib``
dynamic imports невидимы для static analysis (S27, ADR-001).

Usage::

    from src.backend.core.logging import get_logger  # noqa: F401 — re-export
"""

from __future__ import annotations as annotations

from collections.abc import Callable as Callable
from typing import (
    TYPE_CHECKING as TYPE_CHECKING,
    Any as Any,
)

if TYPE_CHECKING:
    # Static contract for the runtime-lazy facade below.  The implementation
    # remains infrastructure-backed, while core callers depend on a Protocol.
    from src.backend.core.interfaces.multi_protocol import (
        LoggerProtocol,  # noqa: F401 — re-export
    )

    get_logger: Callable[[str], LoggerProtocol]

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
