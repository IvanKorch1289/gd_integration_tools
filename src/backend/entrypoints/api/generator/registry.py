"""Re-export action-реестра для entrypoints.

Канонический модуль: ``app.dsl.commands.action_registry``.
"""

from src.backend.dsl.commands.action_registry import (
    ActionHandlerRegistry,
    ActionHandlerSpec,
    action_handler_registry,
)

__all__ = ("ActionHandlerRegistry", "ActionHandlerSpec", "action_handler_registry")
