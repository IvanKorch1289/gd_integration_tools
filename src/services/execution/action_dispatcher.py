"""Реализация ActionDispatcher (W14.1).

Тонкая обёртка над существующим ``ActionHandlerRegistry``. Цель —
выровнять контракт под Protocol :class:`ActionDispatcher` и оставить
запас под политики (idempotency, rate-limit, side-effect classification),
которые подключаются в W14.2/W14.4.
"""

from __future__ import annotations

from typing import Any

from src.core.interfaces.action_dispatcher import ActionDispatcher
from src.dsl.commands.action_registry import (
    ActionHandlerRegistry,
    action_handler_registry,
)
from src.schemas.invocation import ActionCommandSchema

__all__ = ("DefaultActionDispatcher", "get_action_dispatcher")


class DefaultActionDispatcher(ActionDispatcher):
    """Делегирует диспетчеризацию singleton-реестру.

    Конструктор принимает реестр явно — чтобы тесты могли подменить
    его на изолированный экземпляр без обращения к global state.
    """

    def __init__(self, registry: ActionHandlerRegistry | None = None) -> None:
        self._registry = registry or action_handler_registry

    async def dispatch(self, command: ActionCommandSchema) -> Any:
        return await self._registry.dispatch(command)

    def is_registered(self, action: str) -> bool:
        return self._registry.is_registered(action)

    def list_actions(self) -> tuple[str, ...]:
        return self._registry.list_actions()


_default_dispatcher: DefaultActionDispatcher | None = None


def get_action_dispatcher() -> DefaultActionDispatcher:
    """Singleton-доступ к диспетчеру (для DI и DSL processors)."""
    global _default_dispatcher
    if _default_dispatcher is None:
        _default_dispatcher = DefaultActionDispatcher()
    return _default_dispatcher
