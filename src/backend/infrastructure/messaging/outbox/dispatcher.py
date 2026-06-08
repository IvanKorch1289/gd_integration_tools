"""OutboxDispatcher — production polling/delivery/retry/DLQ цикл.

Назначение:

* Periodic polling из ``pending_source`` (репозиторий или Fake).
* Delivery в зарегистрированный ``deliverer`` (HTTP webhook / Kafka /
  RabbitMQ / NATS — выбор делает caller).
* Retry per-event поверх ``tenacity`` (exponential backoff).
* При permanent failure (исчерпаны попытки) — handoff в DLQ через
  :class:`DLQHandler` или (при отсутствии) через
  ``OutboxBackend.enqueue`` с ``status=DLQ``.
* Background-task регистрируется в :class:`TaskRegistry` → graceful
  shutdown с дренажом текущей итерации.

Архитектурные принципы V15:

* Capability-gate не требуется на этом слое (infrastructure-уровень).
* Никаких ``time.sleep`` — только ``asyncio.sleep``.
* structlog-совместимый logger ``infrastructure.messaging.outbox``.
* default-OFF через :class:`OutboxSettings.enabled`.

Wave: ``[wave:s8/k2-w2-outbox-dispatcher-impl]``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from src.backend.core.messaging.outbox import (
    OutboxBackend,
    OutboxEvent,
    OutboxEventStatus,
)
from src.backend.core.utils.task_registry import TaskRegistry, get_task_registry
from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("DLQHandler", "OutboxDispatcher")

_logger = get_logger("infrastructure.messaging.outbox")

#: Тип callable для pull-источника pending событий. Принимает ``batch_size``,
#: возвращает упорядоченную последовательность ``OutboxEvent`` со статусом
#: ``PENDING``.
PendingSource = Callable[[int], Awaitable[Sequence[OutboxEvent]]]

#: Тип callable для подтверждения успешной доставки события.
AckHandler = Callable[[OutboxEvent], Awaitable[None]]

#: Тип callable для самой доставки. Должен бросить исключение при ошибке —
#: dispatcher интерпретирует исключение как нужду в retry.
Deliverer = Callable[[OutboxEvent], Awaitable[None]]


@runtime_checkable
class DLQHandler(Protocol):
    """Контракт обёртки для DLQ-handoff.

    Реализация может писать в Postgres-таблицу ``dlq_events`` либо
    делегировать в [OutboxBackend.enqueue] с ``status=DLQ``. Простейшая
    реализация — :class:`_BackendDLQHandler` (см. ниже) — использует
    второй вариант.
    """

    async def send(self, event: OutboxEvent, reason: BaseException) -> None:
        """Поместить событие в DLQ.

        Args:
            event: исходное событие, доставка которого не удалась.
            reason: финальное исключение, вызвавшее переход в DLQ.
        """


class _BackendDLQHandler:
    """Default-реализация [DLQHandler] поверх [OutboxBackend].

    Вызывает ``backend.enqueue`` с обновлённым event (status=DLQ,
    error_class/error_message заполнены из ``reason``).
    """

    def __init__(self, backend: OutboxBackend) -> None:
        """Сохраняет ссылку на backend для последующего enqueue."""
        self._backend = backend

    async def send(self, event: OutboxEvent, reason: BaseException) -> None:
        """Перевести событие в DLQ и сохранить через backend."""
        event.status = OutboxEventStatus.DLQ
        event.error_class = type(reason).__name__
        event.error_message = str(reason)
        event.updated_at = datetime.now(UTC)
        await self._backend.enqueue(event)


class OutboxDispatcher:
    """Production-цикл polling/delivery/retry/DLQ-handoff.

    Использование::

        dispatcher = OutboxDispatcher(
            backend=outbox,                          # OutboxBackend (DLQ-store)
            pending_source=repo.fetch_pending,        # PendingSource
            ack=repo.mark_delivered,                  # AckHandler
            deliverer=kafka_publisher.publish,        # Deliverer
            dlq=None,                                  # default: backend
            poll_interval=1.0,
            batch_size=100,
            max_retries=5,
            retry_backoff_seconds=2.0,
            enabled=True,
        )
        await dispatcher.start()
        ...
        await dispatcher.stop()

    Внутренние инварианты:

    * При ``enabled=False`` ``start()`` — no-op; задача не создаётся.
    * Между итерациями ждём ``poll_interval`` через ``asyncio.sleep``.
    * Per-event retry: до ``max_retries`` попыток с exponential backoff.
    * При исчерпании retry — handoff в DLQ + structured-log WARNING.
    * При ``stop()`` дренажа текущей итерации идёт до её естественного
      завершения (или cancel при timeout).
    """

    def __init__(
        self,
        *,
        backend: OutboxBackend,
        pending_source: PendingSource,
        ack: AckHandler,
        deliverer: Deliverer,
        dlq: DLQHandler | None = None,
        poll_interval: float = 1.0,
        batch_size: int = 100,
        max_retries: int = 5,
        retry_backoff_seconds: float = 2.0,
        enabled: bool = True,
        task_registry: TaskRegistry | None = None,
    ) -> None:
        """Инициализация диспетчера.

        Args:
            backend: [OutboxBackend] для DLQ-handoff при отсутствии ``dlq``.
            pending_source: callable пуллер pending событий.
            ack: callable подтверждения успешной доставки.
            deliverer: callable доставки в реальный транспорт.
            dlq: опциональный DLQ-handler; при ``None`` — обёртка над
                ``backend.enqueue`` с ``status=DLQ``.
            poll_interval: пауза между итерациями в секундах.
            batch_size: размер пачки за одну итерацию.
            max_retries: максимум попыток доставки (включая первую).
            retry_backoff_seconds: начальный backoff между retry-попытками.
            enabled: feature-flag; ``False`` → ``start`` no-op.
            task_registry: реестр фоновых задач; ``None`` → singleton.
        """
        self._backend = backend
        self._pending_source = pending_source
        self._ack = ack
        self._deliverer = deliverer
        self._dlq: DLQHandler = dlq if dlq is not None else _BackendDLQHandler(backend)
        self._poll_interval = poll_interval
        self._batch_size = batch_size
        self._max_retries = max(1, max_retries)
        self._retry_backoff_seconds = retry_backoff_seconds
        self._enabled = enabled
        self._task_registry = task_registry or get_task_registry()
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()
        self._running = False

    @property
    def is_running(self) -> bool:
        """Возвращает True, если диспетчер активно опрашивает источник."""
        return self._running and self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Запускает background polling-задачу.

        При ``enabled=False`` метод — no-op (диспетчер выключен фичефлагом).
        Повторный вызов идемпотентен: если задача уже жива, ничего не
        делаем.
        """
        if not self._enabled:
            _logger.info(
                "outbox.dispatcher.disabled", extra={"reason": "feature_flag_off"}
            )
            return
        if self.is_running:
            return
        self._stopping.clear()
        self._running = True
        self._task = self._task_registry.create_task(
            self._run(), name="outbox-dispatcher-poll"
        )
        _logger.info(
            "outbox.dispatcher.started",
            extra={
                "poll_interval": self._poll_interval,
                "batch_size": self._batch_size,
                "max_retries": self._max_retries,
            },
        )

    async def stop(self, timeout: float = 10.0) -> None:
        """Graceful shutdown: даём дренаж текущей итерации.

        Args:
            timeout: общий timeout на ожидание завершения текущей
                итерации; при превышении — task.cancel().
        """
        if not self._running:
            return
        self._stopping.set()
        self._running = False
        task = self._task
        self._task = None
        if task is None or task.done():
            return
        try:
            await asyncio.wait_for(task, timeout=timeout)
        except TimeoutError:
            _logger.warning(
                "outbox.dispatcher.stop_timeout", extra={"timeout": timeout}
            )
            task.cancel()
        except asyncio.CancelledError:
            pass
        _logger.info("outbox.dispatcher.stopped")

    async def _run(self) -> None:
        """Главный polling-loop. Завершается на ``_stopping.set()``."""
        while not self._stopping.is_set():
            try:
                await self._poll_and_dispatch()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _logger.error(
                    "outbox.dispatcher.iteration_failed", extra={"error": repr(exc)}
                )
            # Пауза с возможностью пробуждения через ``stop``.
            try:
                await asyncio.wait_for(
                    self._stopping.wait(), timeout=self._poll_interval
                )
            except TimeoutError:
                continue

    async def _poll_and_dispatch(self) -> None:
        """Одна итерация polling: pull → deliver → ack/DLQ.

        Возвращает управление сразу же, если pending пуст — это позволяет
        loop'у быстро уйти в sleep и не нагружать CPU.
        """
        pending = await self._pending_source(self._batch_size)
        if not pending:
            return
        for event in pending:
            if self._stopping.is_set():
                # Корректное прерывание дренажа — не ack-аем недоставленные.
                return
            await self._dispatch_one(event)

    async def _dispatch_one(self, event: OutboxEvent) -> None:
        """Доставка одного события с retry-loop'ом.

        Использует in-line tenacity-подобный exponential backoff (без
        декоратора, чтобы сохранить контроль над per-attempt-state и
        транзакционностью). При исчерпании попыток → DLQ-handoff.
        """
        last_exc: BaseException | None = None
        for attempt in range(1, self._max_retries + 1):
            if self._stopping.is_set():
                return
            try:
                await self._deliverer(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_exc = exc
                event.retry_count = attempt
                event.error_class = type(exc).__name__
                event.error_message = str(exc)
                _logger.debug(
                    "outbox.dispatcher.delivery_failed",
                    extra={
                        "event_id": event.event_id,
                        "attempt": attempt,
                        "error": repr(exc),
                    },
                )
                if attempt >= self._max_retries:
                    break
                # Exponential backoff: 2.0 * 2^(attempt-1) — 2, 4, 8, ...
                sleep_for = self._retry_backoff_seconds * (2 ** (attempt - 1))
                try:
                    await asyncio.wait_for(self._stopping.wait(), timeout=sleep_for)
                    # Пробудились по stop — выходим без повторной попытки.
                    return
                except TimeoutError:
                    continue
            else:
                event.status = OutboxEventStatus.DELIVERED
                event.updated_at = datetime.now(UTC)
                await self._ack(event)
                _logger.debug(
                    "outbox.dispatcher.delivered",
                    extra={"event_id": event.event_id, "attempts": attempt},
                )
                return
        # Все попытки исчерпаны — DLQ-handoff.
        if last_exc is None:
            last_exc = RuntimeError("delivery exhausted without exception")
        _logger.warning(
            "outbox.dispatcher.dlq_handoff",
            extra={
                "event_id": event.event_id,
                "error_class": type(last_exc).__name__,
                "error_message": str(last_exc),
                "attempts": self._max_retries,
            },
        )
        try:
            await self._dlq.send(event, last_exc)
        except Exception as exc:
            _logger.error(
                "outbox.dispatcher.dlq_handoff_failed",
                extra={"event_id": event.event_id, "error": repr(exc)},
            )
