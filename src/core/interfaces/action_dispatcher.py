"""Контракт ActionDispatcher (W14.1).

Action отделён от транспорта: одна и та же бизнес-команда может быть
запущена из HTTP/gRPC/Queue/WS/Schedule. Реализация — в
``services/execution/action_dispatcher.py``.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from src.core.types.invocation_command import ActionCommandSchema

__all__ = ("ActionDispatcher",)


@runtime_checkable
class ActionDispatcher(Protocol):
    """Главный диспетчер бизнес-команд (W14.1 Gateway).

    Контракт минимален и стабилен: транспорт-агностичный вызов action'а
    с произвольным payload. Все политики (idempotency, rate-limit,
    side-effect classification) применяются внутри реализации.
    """

    async def dispatch(self, command: ActionCommandSchema) -> Any:
        """Выполнить бизнес-команду и вернуть её результат."""
        ...

    def is_registered(self, action: str) -> bool:
        """Проверить наличие зарегистрированного обработчика."""
        ...

    def list_actions(self) -> tuple[str, ...]:
        """Список зарегистрированных action-имён (отсортированный)."""
        ...
