"""TaskRegistry — central control над фоновыми ``asyncio.Task`` (V15 R-V15-11).

Назначение:

* единая точка регистрации всех ``asyncio.create_task`` в проекте;
* graceful cancel всех висящих задач при shutdown lifespan;
* propagation ``correlation_id``/``tenant_id``/``request_id`` в фоновую
  таску через ``contextvars.copy_context().run`` (значения берутся из
  ``infrastructure.observability.correlation``);
* deadline-эскалация через ``Watchdog`` при необходимости.

Использование::

    registry = get_task_registry()
    task = registry.create_task(worker(), name="audit-replay-flush")
    ...
    await registry.shutdown_all(timeout=10)

Все ``asyncio.create_task``/``asyncio.ensure_future`` callsite'ы в
``src/backend`` мигрируются на ``registry.create_task``. ``tests/`` могут
сохранять raw ``create_task`` — там нужны прямые assertion'ы на task-объекты.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
from collections.abc import Awaitable, Coroutine
from typing import Any, TypeVar

from src.backend.core.utils.watchdog import Watchdog

__all__ = (
    "TaskRegistry",
    "get_task_registry",
    "reset_task_registry",
)

_T = TypeVar("_T")
_logger = logging.getLogger(__name__)


class TaskRegistry:
    """Регистрирует фоновые задачи для graceful shutdown и трассировки.

    Хранит ``set[asyncio.Task]`` живых задач: каждая зарегистрированная
    таска снимается из множества при завершении (success или exception)
    через ``add_done_callback``. ``shutdown_all`` отменяет все живые
    задачи и ждёт их завершения с таймаутом.
    """

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[Any]] = set()
        self._named: dict[str, asyncio.Task[Any]] = {}
        self._closed: bool = False

    def create_task(
        self,
        coro: Coroutine[Any, Any, _T] | Awaitable[_T],
        *,
        name: str,
        deadline_seconds: float | None = None,
    ) -> asyncio.Task[_T]:
        """Создаёт ``asyncio.Task`` под управлением реестра.

        Args:
            coro: корутина или awaitable.
            name: уникальный descriptor места создания.
            deadline_seconds: если задано — оборачивает корутину в
                ``Watchdog`` с deadline-эскалацией.

        Returns:
            Зарегистрированная ``asyncio.Task``.

        Raises:
            RuntimeError: при попытке создать задачу после shutdown.
        """
        if self._closed:
            raise RuntimeError(
                "TaskRegistry уже закрыт — нельзя создавать новые задачи"
            )

        ctx = contextvars.copy_context()

        async def _runner() -> _T:
            return await coro

        if deadline_seconds is not None:
            watchdog = Watchdog(name=name, deadline_seconds=deadline_seconds)
            wrapped = watchdog.wrap(_runner())
        else:
            wrapped = _runner()

        loop = asyncio.get_event_loop()
        task: asyncio.Task[_T] = loop.create_task(
            self._with_context(ctx, wrapped),
            name=name,
        )
        self._tasks.add(task)
        self._named[name] = task
        task.add_done_callback(self._on_done)
        return task

    @staticmethod
    async def _with_context(
        ctx: contextvars.Context,
        coro: Coroutine[Any, Any, _T] | Awaitable[_T],
    ) -> _T:
        """Выполняет ``coro`` в копии context'а вызывающего."""
        # ``ctx.run`` — для синхронного кода; для async используем
        # явный re-bind значений в текущий контекст. Read-only var из
        # сторонних библиотек глушим — это диагностический no-op.
        for var, value in ctx.items():
            try:
                var.set(value)
            except (LookupError, RuntimeError, TypeError):  # noqa: S110
                continue
        return await coro

    def _on_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        name = task.get_name()
        if self._named.get(name) is task:
            self._named.pop(name, None)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None and not isinstance(exc, asyncio.CancelledError):
            _logger.warning(
                "task_registry.task_failed",
                extra={"task_name": name, "error": repr(exc)},
            )

    def cancel(self, name: str) -> bool:
        """Отменяет задачу по имени. Возвращает ``True``, если найдена."""
        task = self._named.get(name)
        if task is None:
            return False
        if not task.done():
            task.cancel()
        return True

    async def shutdown_all(self, timeout: float = 10.0) -> None:
        """Отменяет все живые задачи и ждёт их завершения.

        Args:
            timeout: общий timeout на graceful shutdown в секундах.
        """
        self._closed = True
        live = [t for t in self._tasks if not t.done()]
        for task in live:
            task.cancel()
        if not live:
            return
        try:
            await asyncio.wait_for(
                asyncio.gather(*live, return_exceptions=True),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            _logger.warning(
                "task_registry.shutdown_timeout",
                extra={"pending": [t.get_name() for t in live if not t.done()]},
            )

    def list_tasks(self) -> list[asyncio.Task[Any]]:
        """Снимок живых задач (для диагностики)."""
        return [t for t in self._tasks if not t.done()]

    def reset_for_tests(self) -> None:
        """Сбрасывает state — только для unit-тестов."""
        self._tasks.clear()
        self._named.clear()
        self._closed = False


_registry: TaskRegistry | None = None


def get_task_registry() -> TaskRegistry:
    """Singleton-аксессор. Создаёт реестр при первом обращении."""
    global _registry
    if _registry is None:
        _registry = TaskRegistry()
    return _registry


def reset_task_registry() -> None:
    """Сбрасывает singleton (для unit-тестов и lifespan-тестов)."""
    global _registry
    _registry = None
