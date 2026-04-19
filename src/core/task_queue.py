"""Task Queue bridge — taskiq (modern async Celery replacement).

taskiq — native async distributed task queue. Поддерживает:
- Redis / RabbitMQ brokers
- Labels для routing
- Retries с exponential backoff
- Middleware (metrics, logging)
- Scheduled tasks (рядом с APScheduler)

Нативный async — идеально для этого проекта (vs Celery с eventlet).

Usage::

    from app.core.task_queue import task_queue

    @task_queue.task(retries=3)
    async def process_order(order_id: int) -> dict:
        # ... work
        return {"status": "ok"}

    # Client side:
    await process_order.kiq(order_id=123)  # enqueue
    result = await process_order.kiq(order_id=123).wait_result()

Graceful fallback: если taskiq не установлен, декоратор превращается
в no-op wrapper (task выполняется synchronously).
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, TypeVar

__all__ = ("task_queue", "TASKIQ_AVAILABLE")

logger = logging.getLogger("core.task_queue")

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


try:
    from taskiq import TaskiqScheduler  # noqa: F401
    from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

    TASKIQ_AVAILABLE = True
except ImportError:
    TASKIQ_AVAILABLE = False


class _TaskQueueFacade:
    """Фасад над taskiq. Если taskiq недоступен — работает в-process."""

    def __init__(self) -> None:
        self._broker: Any = None
        if TASKIQ_AVAILABLE:
            import os
            redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            try:
                result_backend = RedisAsyncResultBackend(redis_url)
                self._broker = ListQueueBroker(redis_url).with_result_backend(result_backend)
                logger.info("taskiq broker initialized: %s", redis_url)
            except Exception as exc:
                logger.warning("taskiq broker init failed: %s, using in-process", exc)
                self._broker = None

    def task(
        self,
        *,
        retries: int = 0,
        retry_on_error: bool = True,
        task_name: str | None = None,
    ) -> Callable[[F], Any]:
        """Декоратор для регистрации task."""

        def decorator(fn: F) -> Any:
            if self._broker is None:
                # Fallback: sync wrapper (прямой вызов)
                return fn

            task_obj = self._broker.task(
                task_name=task_name or fn.__name__,
                retry_on_error=retry_on_error,
                max_retries=retries,
            )(fn)
            return task_obj

        return decorator

    async def startup(self) -> None:
        """Startup broker (вызывается в app lifecycle)."""
        if self._broker is not None and not self._broker.is_worker_process:
            await self._broker.startup()

    async def shutdown(self) -> None:
        """Shutdown broker."""
        if self._broker is not None:
            try:
                await self._broker.shutdown()
            except Exception as exc:
                logger.warning("taskiq shutdown failed: %s", exc)


task_queue = _TaskQueueFacade()
