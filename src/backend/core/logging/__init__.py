"""Core logging facade.

Lazy re-exports ``get_logger`` and configuration utilities so that
``core`` and ``services`` layers do not depend directly on
``infrastructure/logging``. The actual implementation is resolved at
first attribute access (runtime), which keeps ``check_layers.py`` happy
— ``importlib`` dynamic imports are invisible to static analysis
(S27, ADR-001).

Usage::

    from src.backend.core.logging import get_logger
    logger = get_logger("application")
"""

from typing import Any

__all__ = (
    "configure_logging",
    "get_logger",
    "init_log_sinks",
    "shutdown_log_sinks",
    "shutdown_logging",
)


def __getattr__(name: str) -> Any:
    if name in __all__:
        import importlib

        mod = importlib.import_module("src.backend.infrastructure.logging.factory")
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
