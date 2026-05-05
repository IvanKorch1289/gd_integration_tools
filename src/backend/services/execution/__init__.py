"""Execution services — единая точка запуска бизнес-команд (W14.1, W22).

Содержит:

* :mod:`services.execution.action_dispatcher` — реализация
  :class:`core.interfaces.action_dispatcher.ActionDispatcher` поверх
  существующего ``ActionHandlerRegistry``.
* :mod:`services.execution.invoker` — :class:`Invoker`, главный Gateway
  проекта (W22): любая функция вызывается через него с режимом
  sync/async-api/async-queue/deferred/background/streaming.
"""

from src.services.execution.action_dispatcher import (
    DefaultActionDispatcher,
    get_action_dispatcher,
)
from src.services.execution.invoker import InvocationMode, Invoker, get_invoker
from src.services.execution.middlewares import (
    AuditMiddleware,
    IdempotencyMiddleware,
    RateLimitMiddleware,
)

__all__ = (
    "DefaultActionDispatcher",
    "get_action_dispatcher",
    "Invoker",
    "InvocationMode",
    "get_invoker",
    "AuditMiddleware",
    "IdempotencyMiddleware",
    "RateLimitMiddleware",
)
