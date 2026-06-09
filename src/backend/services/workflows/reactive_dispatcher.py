"""Reactive Workflow Dispatcher — Sprint 12 K3 W4.

Event-driven triggers без polling:

* :class:`ReactiveTrigger` — декларация триггера
  (channel + filter_expr + debounce_seconds + dedup_key).
* :class:`ReactiveWorkflowDispatcher`:
    - ``register_trigger(workflow_id, trigger)``;
    - на startup подписывается через ``EventBus.subscribe(channel, handler)``;
    - на event: debounce (asyncio task per dedup_key + sleep), dedup
      (Redis SET NX EX 60), filter (simpleeval) → start workflow.

Безопасность:
    * ``simpleeval.SimpleEval`` ограничивает expressions;
    * Bulkhead через ``max_concurrent_starts=100``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from src.backend.core.logging import get_logger

__all__ = ("ReactiveTrigger", "ReactiveWorkflowDispatcher")

_logger = get_logger("services.workflows.reactive_dispatcher")


@dataclass(frozen=True, slots=True)
class ReactiveTrigger:
    """Декларация trigger для одного workflow."""

    channel: str
    filter_expr: str | None = None
    debounce_seconds: int = 5
    dedup_key: str | None = None
    workflow_namespace: str = "default"
    task_queue: str = "default"


@dataclass(slots=True)
class _PendingDebounce:
    task: asyncio.Task[Any]
    last_event: dict[str, Any]


class ReactiveWorkflowDispatcher:
    """Dispatches events to workflows с debounce + dedup.

    Args:
        workflow_facade: для старта workflow через capability gate.
        event_bus: :class:`EventBus`-instance (FastStream Redis under the hood).
        redis_client: для dedup ``SET NX EX 60`` (опц.).
        max_concurrent_starts: bulkhead (default 100).
    """

    def __init__(
        self,
        *,
        workflow_facade: Any,
        event_bus: Any,
        redis_client: Any | None = None,
        max_concurrent_starts: int = 100,
    ) -> None:
        self._facade = workflow_facade
        self._bus = event_bus
        self._redis = redis_client
        self._triggers: dict[str, list[tuple[str, ReactiveTrigger]]] = {}
        self._pending: dict[str, _PendingDebounce] = {}
        self._sem = asyncio.Semaphore(max_concurrent_starts)
        self._started = False

    def register_trigger(self, workflow_id: str, trigger: ReactiveTrigger) -> None:
        """Регистрирует trigger для workflow."""
        self._triggers.setdefault(trigger.channel, []).append((workflow_id, trigger))

    async def start(self) -> None:
        """Subscribe ко всем каналам через EventBus."""
        if self._started:
            return
        for channel, _ in self._triggers.items():
            await self._subscribe_channel(channel)
        self._started = True
        _logger.info(
            "ReactiveWorkflowDispatcher started, %d unique channels",
            len(self._triggers),
        )

    async def stop(self) -> None:
        """Cancel all pending debounce tasks (graceful shutdown)."""
        for pending in self._pending.values():
            if not pending.task.done():
                pending.task.cancel()
        await asyncio.gather(
            *[p.task for p in self._pending.values()], return_exceptions=True
        )
        self._pending.clear()
        self._started = False

    async def _subscribe_channel(self, channel: str) -> None:
        """Подписаться на channel через EventBus.subscribe (FastStream)."""
        if hasattr(self._bus, "subscribe"):
            await self._bus.subscribe(channel, self._make_handler(channel))
        else:
            _logger.warning(
                "EventBus.subscribe unavailable — trigger %s skipped", channel
            )

    def _make_handler(
        self, channel: str
    ) -> Callable[[dict[str, Any]], Awaitable[None]]:
        async def handler(event: dict[str, Any]) -> None:
            await self._on_event(channel, event)

        return handler

    async def _on_event(self, channel: str, event: dict[str, Any]) -> None:
        """Обрабатывает event: filter → debounce → dedup → start workflow."""
        triggers = self._triggers.get(channel, [])
        for workflow_id, trigger in triggers:
            if trigger.filter_expr and not self._apply_filter(
                trigger.filter_expr, event
            ):
                continue

            dedup_key = trigger.dedup_key
            if dedup_key:
                resolved_key = (
                    f"reactive:dedup:{workflow_id}:{event.get(dedup_key, dedup_key)}"
                )
                if not await self._check_dedup(resolved_key):
                    _logger.debug("Dedup hit for %s", resolved_key)
                    continue

            if trigger.debounce_seconds > 0:
                self._schedule_debounce(workflow_id, trigger, event)
            else:
                await self._start_workflow(workflow_id, trigger, event)

    def _schedule_debounce(
        self, workflow_id: str, trigger: ReactiveTrigger, event: dict[str, Any]
    ) -> None:
        """Запускает debounce timer; при повторном event перезапускает."""
        debounce_key = f"{workflow_id}:{trigger.channel}"
        existing = self._pending.get(debounce_key)
        if existing and not existing.task.done():
            existing.task.cancel()

        async def _delayed_start() -> None:
            try:
                await asyncio.sleep(trigger.debounce_seconds)
                last = self._pending.get(debounce_key)
                if last is not None:
                    await self._start_workflow(workflow_id, trigger, last.last_event)
                self._pending.pop(debounce_key, None)
            except asyncio.CancelledError:
                pass

        from src.backend.core.utils.task_registry import get_task_registry

        task = get_task_registry().create_task(
            _delayed_start(), name=f"reactive-debounce-{workflow_id}"
        )
        self._pending[debounce_key] = _PendingDebounce(task=task, last_event=event)

    async def _start_workflow(
        self, workflow_id: str, trigger: ReactiveTrigger, event: dict[str, Any]
    ) -> None:
        """Старт workflow через capability gated facade."""
        async with self._sem:
            try:
                await self._facade.start(
                    caller="reactive_dispatcher",
                    workflow_name=workflow_id,
                    workflow_id=f"{workflow_id}:{event.get('event_id', '')}",
                    input=event,
                    namespace=trigger.workflow_namespace,
                    task_queue=trigger.task_queue,
                )
            except Exception as exc:
                _logger.error(
                    "Failed to start reactive workflow %s: %s", workflow_id, exc
                )

    @staticmethod
    def _apply_filter(expression: str, event: dict[str, Any]) -> bool:
        """Применяет filter через simpleeval. На любую ошибку → False."""
        try:
            from simpleeval import SimpleEval

            evaluator = SimpleEval(names=dict(event))
            return bool(evaluator.eval(expression))
        except ImportError:
            msg = (
                "simpleeval not available — expression evaluation requires it. "
                "Install via: pip install simpleeval"
            )
            raise RuntimeError(msg) from None
        except Exception as _:
            return False

    async def _check_dedup(self, key: str) -> bool:
        """Возвращает ``True`` если событие первое (Redis SET NX EX 60).

        При отсутствии Redis всегда True (no dedup).
        """
        if self._redis is None:
            return True
        try:
            result = await self._redis.set(key, "1", nx=True, ex=60)
            return bool(result)
        except Exception as _:
            return True
