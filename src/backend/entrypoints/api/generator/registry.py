"""Re-export action-реестра для entrypoints.

Канонический модуль: ``app.dsl.commands.action_registry``.
"""

from src.backend.core.api.extensions import (  # noqa: F401 — re-export
    ActionHandlerRegistry,
    ActionHandlerSpec,
    action_handler_registry,
)

__all__ = ("ActionHandlerRegistry", "ActionHandlerSpec", "action_handler_registry")
