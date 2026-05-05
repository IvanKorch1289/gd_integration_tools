"""Priority routing для уведомлений — tx vs marketing (IL2.2).

Transactional уведомления (код подтверждения для банковской операции,
KYC approved, приём платежа) имеют строгий SLO: p99 < 5s, zero-loss.
Marketing (рассылки, уведомления о новых фичах) — eventually-consistent,
допускается батчинг + throttling.

`PriorityRouter` держит две независимые asyncio.Queue с размерами из
отдельных `PoolingProfile`. При saturation marketing-потока tx продолжает
обрабатываться; при saturation tx-потока emit'ится alert (IL3.8
``NotificationPriorityBacklog``).

Воркеры — coroutines. Количество worker'ов per priority — из
`PoolingProfile.max_size`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Final, Literal

from src.backend.core.config.pooling import PoolingProfile

_logger = logging.getLogger(__name__)


Priority = Literal["tx", "marketing"]
ALL_PRIORITIES: Final = ("tx", "marketing")


#: Разумные дефолты для двух уровней. Могут быть перегружены через
#: `PoolingProfile.named("...")` или явно при инициализации.
DEFAULT_TX_POOL = PoolingProfile(min_size=4, max_size=32, circuit_threshold=3)
DEFAULT_MARKETING_POOL = PoolingProfile(min_size=1, max_size=8, circuit_threshold=10)


@dataclass(slots=True)
class _QueueItem:
    """Внутренний envelope для item-а в priority queue."""

    priority: Priority
    payload: Any
    callback: Callable[[Any], Awaitable[None]]


@dataclass(slots=True)
class PriorityRouter:
    """Двуступенчатый queueing для уведомлений.

    Использование:

        router = PriorityRouter()
        await router.start()

        await router.submit(
            priority="tx",
            payload=send_request,
            callback=send_via_adapter,  # async fn(payload)
        )

        await router.stop()

    Внутри — два asyncio.Queue + `max_size` worker'ов для каждого; `stop()`
    ждёт, пока текущие worker'ы закончат, но не принимает новые.
    """

    tx_profile: PoolingProfile = field(default_factory=lambda: DEFAULT_TX_POOL)
    marketing_profile: PoolingProfile = field(
        default_factory=lambda: DEFAULT_MARKETING_POOL
    )

    #: Приватные поля — заполняются в `start()`.
    _tx_queue: asyncio.Queue[_QueueItem] = field(
        init=False, default_factory=asyncio.Queue
    )
    _marketing_queue: asyncio.Queue[_QueueItem] = field(
        init=False, default_factory=asyncio.Queue
    )
    _workers: list[asyncio.Task[None]] = field(init=False, default_factory=list)
    _started: bool = field(init=False, default=False)

    async def start(self) -> None:
        if self._started:
            return
        for i in range(self.tx_profile.max_size):
            t = asyncio.create_task(self._worker_loop("tx", self._tx_queue))
            t.set_name(f"notif-worker-tx-{i}")
            self._workers.append(t)
        for i in range(self.marketing_profile.max_size):
            t = asyncio.create_task(
                self._worker_loop("marketing", self._marketing_queue)
            )
            t.set_name(f"notif-worker-mkt-{i}")
            self._workers.append(t)
        self._started = True
        _logger.info(
            "notification priority router started",
            extra={
                "tx_workers": self.tx_profile.max_size,
                "marketing_workers": self.marketing_profile.max_size,
            },
        )

    async def stop(self) -> None:
        if not self._started:
            return
        # Сигнал завершения — sentinels. Каждому worker по одному.
        for _ in range(self.tx_profile.max_size):
            await self._tx_queue.put(_SENTINEL)
        for _ in range(self.marketing_profile.max_size):
            await self._marketing_queue.put(_SENTINEL)
        # Дождёмся; grace-timeout на каждого.
        for w in self._workers:
            try:
                await asyncio.wait_for(w, timeout=5.0)
            except asyncio.TimeoutError:
                w.cancel()
        self._workers.clear()
        self._started = False
        _logger.info("notification priority router stopped")

    async def submit(
        self,
        *,
        priority: Priority,
        payload: Any,
        callback: Callable[[Any], Awaitable[None]],
        wait: bool = False,
    ) -> None:
        """Поставить item в очередь по приоритету.

        * ``wait=False`` (default) — fire-and-forget, put_nowait (QueueFull
          → `NotificationBacklogError`).
        * ``wait=True`` — блокируется, пока в queue есть место.
        """
        if priority not in ALL_PRIORITIES:
            raise ValueError(
                f"Unknown priority '{priority}'. Use: {', '.join(ALL_PRIORITIES)}"
            )
        queue = self._tx_queue if priority == "tx" else self._marketing_queue
        item = _QueueItem(priority=priority, payload=payload, callback=callback)
        if wait:
            await queue.put(item)
        else:
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull as exc:
                raise NotificationBacklogError(
                    f"Notification queue full for priority='{priority}' — "
                    f"backlog at qsize={queue.qsize()}"
                ) from exc

    async def _worker_loop(
        self, priority: Priority, queue: asyncio.Queue[_QueueItem]
    ) -> None:
        while True:
            item = await queue.get()
            if item is _SENTINEL:
                return
            try:
                await item.callback(item.payload)
            except Exception as exc:  # noqa: BLE001
                _logger.error(
                    "notification callback failed",
                    extra={
                        "priority": priority,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
            finally:
                queue.task_done()

    def stats(self) -> dict[str, Any]:
        """Для health-дашборда: размер очередей."""
        return {
            "started": self._started,
            "tx_qsize": self._tx_queue.qsize(),
            "marketing_qsize": self._marketing_queue.qsize(),
            "tx_workers": self.tx_profile.max_size,
            "marketing_workers": self.marketing_profile.max_size,
        }


# Маркер для shutdown.
_SENTINEL: Any = object()


class NotificationBacklogError(RuntimeError):
    """Queue для соответствующего priority полная — backlog."""


__all__ = (
    "Priority",
    "PriorityRouter",
    "DEFAULT_TX_POOL",
    "DEFAULT_MARKETING_POOL",
    "NotificationBacklogError",
)
