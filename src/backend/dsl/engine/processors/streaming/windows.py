"""Streaming- и expiration-процессоры для DSL.

Реализация недостающих EIP-паттернов банковской интеграционной шины:

* :class:`MessageExpirationProcessor` — TTL на сообщение (EIP Message Expiration).
* :class:`CorrelationIdProcessor` — пропагация correlation-id (EIP Correlation Identifier).
* :class:`TumblingWindowProcessor` — фиксированное окно по времени (streaming).
* :class:`SlidingWindowProcessor` — скользящее окно с перекрытием (streaming).
* :class:`SessionWindowProcessor` — окно по простою (gap-based).
* :class:`GroupByKeyProcessor` — агрегация по ключу в пределах окна.
* :class:`SchemaRegistryValidator` — Avro/JSON Schema валидация.
* :class:`ReplyToProcessor` — request-reply поверх очередей.
* :class:`ExactlyOnceProcessor` — dedup через storage + outbox.
* :class:`DurableSubscriberProcessor` — persistent fan-out к нескольким подписчикам.
* :class:`ChannelPurgerProcessor` — очистка DLQ/стрима.
* :class:`SamplingProcessor` — вероятностный сэмплинг (A/B-testing, canary).

Все процессоры наследуют :class:`BaseProcessor` и подчиняются жизненному циклу
Exchange/ExecutionContext.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from typing import Any

from src.backend.core.clock import RealClock
from src.backend.core.interfaces.clock import Clock
from src.backend.core.interfaces.watermark_store import WatermarkStore
from src.backend.core.logging import get_logger
from src.backend.core.types.watermark import LatePolicy, WatermarkState
from src.backend.core.utils.task_registry import get_task_registry
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.late_event_policy import apply_late_policy
from src.backend.dsl.engine.processors.base import BaseProcessor

logger = get_logger("dsl.streaming")


# ──────────────────── Message Expiration ────────────────────


# ── windowing (Tumbling/Sliding/Session/GroupBy) — _BaseWindow + 4 window processors ──


class _BaseWindow(BaseProcessor):
    """Общая логика для оконных процессоров.

    Args:
        sink: Callable, получающий список накопленных сообщений.
        name: Имя процессора (для логирования и метрик).
        clock: Источник времени; default ``RealClock`` (production).
            В тестах подменяется на ``FakeClock``.
        allowed_lateness_seconds: Дополнительный допуск для late events
            (W14.3). 0 = строгий watermark.
        late_policy: Что делать с late events: ``DROP`` (default),
            ``SIDE_OUTPUT``, ``REPROCESS``.
        watermark_store: Опциональный персистентный backend (W14.5).
            При наличии вместе с ``route_id`` watermark переживает рестарт.
        route_id: Идентификатор DSL-маршрута; обязателен совместно с
            ``watermark_store`` для уникальности ключа в store.
        persist_min_interval: Минимальный интервал между сохранениями в
            store (секунды wall-clock). Дебаунс защищает горячий путь.
    """

    def __init__(
        self,
        *,
        sink: Any,
        name: str,
        clock: Clock | None = None,
        allowed_lateness_seconds: float = 0.0,
        late_policy: LatePolicy = LatePolicy.DROP,
        watermark_store: WatermarkStore | None = None,
        route_id: str | None = None,
        persist_min_interval: float = 1.0,
    ) -> None:
        super().__init__(name=name)
        # ``sink`` — callable, которому передаём список собранных сообщений
        self._sink = sink
        self._lock = asyncio.Lock()
        self._clock: Clock = clock or RealClock()
        self._allowed_lateness = allowed_lateness_seconds
        self._late_policy = late_policy
        self._watermark = WatermarkState()
        self._store = watermark_store
        self._route_id = route_id
        self._persist_min_interval = persist_min_interval
        self._last_persisted_at: float = 0.0
        self._loaded_from_store: bool = False

    @property
    def watermark_state(self) -> WatermarkState:
        """Снимок текущего watermark (для тестов и метрик)."""
        return self._watermark

    async def _ensure_loaded(self) -> None:
        """Lazy-загрузка watermark из store при первом обращении.

        Вызов идемпотентен. Если store/route_id не заданы — no-op.
        """
        if self._loaded_from_store or self._store is None or self._route_id is None:
            return
        loaded = await self._store.load(self._route_id, self.name)
        if loaded is not None and loaded.current > self._watermark.current:
            self._watermark = loaded
        self._loaded_from_store = True

    async def _maybe_persist(self) -> None:
        """Сохранить watermark в store с дебаунсом.

        Persist выполняется не чаще, чем раз в ``persist_min_interval``
        секунд wall-clock. ``-inf`` (advance ещё не происходил) пропускаем
        — состояние не несёт информации.
        """
        if self._store is None or self._route_id is None:
            return
        if self._watermark.current == float("-inf"):
            return
        now = self._clock.time()
        if (now - self._last_persisted_at) < self._persist_min_interval:
            return
        try:
            await self._store.save(self._route_id, self.name, self._watermark)
            self._last_persisted_at = now
        except Exception as exc:
            logger.error("Watermark persist failed: %s", exc)

    async def _is_late_and_handle(self, exchange: Exchange[Any]) -> bool:
        """Проверить exchange на late event и применить политику.

        Returns:
            ``True`` если событие отброшено (engine должен прекратить
            обработку), ``False`` если можно класть в bucket.
        """
        await self._ensure_loaded()
        msg_watermark = exchange.in_message.watermark
        if msg_watermark is None:
            return False
        # Продвигаем watermark процессора до значения из сообщения.
        advanced = self._watermark.advance(msg_watermark, now=self._clock.time())
        if advanced:
            await self._maybe_persist()
        # event_time = заголовок x-event-time или wall-clock.
        event_time_raw = exchange.in_message.headers.get("x-event-time")
        try:
            event_time = float(event_time_raw) if event_time_raw is not None else None
        except (TypeError, ValueError):
            event_time = None
        if event_time is None:
            return False
        if not self._watermark.is_late(
            event_time, allowed_lateness=self._allowed_lateness
        ):
            return False
        keep = await apply_late_policy(
            exchange, state=self._watermark, policy=self._late_policy
        )
        # Late-counter изменился — пробуем персистнуть (тоже под дебаунсом).
        await self._maybe_persist()
        return not keep

    async def _emit(self, bucket: list[Any]) -> None:
        if not bucket:
            return
        try:
            result = self._sink(bucket)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            logger.error("Window sink failed: %s", exc)


class TumblingWindowProcessor(_BaseWindow):
    """Tumbling-окно: фиксированный размер, без перекрытия.

    Накапливает сообщения в буфере. При достижении ``size`` или по таймауту
    ``interval_seconds`` — вызывает ``sink(messages)``.
    """

    def __init__(
        self,
        *,
        sink: Any,
        size: int = 100,
        interval_seconds: float = 10.0,
        name: str | None = None,
        clock: Clock | None = None,
        allowed_lateness_seconds: float = 0.0,
        late_policy: LatePolicy = LatePolicy.DROP,
        watermark_store: WatermarkStore | None = None,
        route_id: str | None = None,
        persist_min_interval: float = 1.0,
    ) -> None:
        super().__init__(
            sink=sink,
            name=name or "tumbling-window",
            clock=clock,
            allowed_lateness_seconds=allowed_lateness_seconds,
            late_policy=late_policy,
            watermark_store=watermark_store,
            route_id=route_id,
            persist_min_interval=persist_min_interval,
        )
        self._size = size
        self._interval = interval_seconds
        self._buffer: list[Any] = []
        self._flush_task: asyncio.Task | None = None

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        # Late event — engine применяет политику и прекращает обработку.
        if await self._is_late_and_handle(exchange):
            return
        async with self._lock:
            self._buffer.append(exchange.in_message.body)
            if self._flush_task is None or self._flush_task.done():
                self._flush_task = get_task_registry().create_task(
                    self._timed_flush(), name=f"tumbling-flush:{self.name}"
                )
            if len(self._buffer) >= self._size:
                bucket = list(self._buffer)
                self._buffer.clear()
                await self._emit(bucket)

    async def _timed_flush(self) -> None:
        await asyncio.sleep(self._interval)
        async with self._lock:
            bucket = list(self._buffer)
            self._buffer.clear()
        await self._emit(bucket)


class SlidingWindowProcessor(_BaseWindow):
    """Sliding-окно: фиксированная длительность, шаг меньше размера.

    Пример: окно 10с, шаг 2с — каждые 2 секунды эмитим все сообщения за последние 10с.

    Late events отбрасываются согласно ``late_policy`` (по аналогии с
    Tumbling). Watermark берётся из ``message.watermark``, event_time —
    из заголовка ``x-event-time``.
    """

    def __init__(
        self,
        *,
        sink: Any,
        window_seconds: float = 10.0,
        step_seconds: float = 2.0,
        name: str | None = None,
        clock: Clock | None = None,
        allowed_lateness_seconds: float = 0.0,
        late_policy: LatePolicy = LatePolicy.DROP,
        watermark_store: WatermarkStore | None = None,
        route_id: str | None = None,
        persist_min_interval: float = 1.0,
    ) -> None:
        super().__init__(
            sink=sink,
            name=name or "sliding-window",
            clock=clock,
            allowed_lateness_seconds=allowed_lateness_seconds,
            late_policy=late_policy,
            watermark_store=watermark_store,
            route_id=route_id,
            persist_min_interval=persist_min_interval,
        )
        self._window = window_seconds
        self._step = step_seconds
        self._buffer: deque[tuple[float, Any]] = deque()
        self._task: asyncio.Task | None = None

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        if await self._is_late_and_handle(exchange):
            return
        now = self._clock.monotonic()
        async with self._lock:
            self._buffer.append((now, exchange.in_message.body))
            if self._task is None or self._task.done():
                self._task = get_task_registry().create_task(
                    self._emit_loop(), name=f"sliding-emit:{self.name}"
                )

    async def _emit_loop(self) -> None:
        # Окно скользит пока есть данные; останавливаемся после пустого шага.
        while True:
            await asyncio.sleep(self._step)
            async with self._lock:
                cutoff = self._clock.monotonic() - self._window
                while self._buffer and self._buffer[0][0] < cutoff:
                    self._buffer.popleft()
                if not self._buffer:
                    return
                bucket = [body for _, body in self._buffer]
            await self._emit(bucket)


class SessionWindowProcessor(_BaseWindow):
    """Session-окно: окно закрывается после паузы ``gap_seconds``.

    Применяется для группировки связанных событий (например, действий
    пользователя в одной сессии).

    Late events отбрасываются согласно ``late_policy``: событие, чей
    ``event_time`` уже отстал от watermark, не попадает в текущую сессию.
    """

    def __init__(
        self,
        *,
        sink: Any,
        gap_seconds: float = 30.0,
        name: str | None = None,
        clock: Clock | None = None,
        allowed_lateness_seconds: float = 0.0,
        late_policy: LatePolicy = LatePolicy.DROP,
        watermark_store: WatermarkStore | None = None,
        route_id: str | None = None,
        persist_min_interval: float = 1.0,
    ) -> None:
        super().__init__(
            sink=sink,
            name=name or "session-window",
            clock=clock,
            allowed_lateness_seconds=allowed_lateness_seconds,
            late_policy=late_policy,
            watermark_store=watermark_store,
            route_id=route_id,
            persist_min_interval=persist_min_interval,
        )
        self._gap = gap_seconds
        self._buffer: list[Any] = []
        self._last_seen: float = 0.0
        self._task: asyncio.Task | None = None

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        if await self._is_late_and_handle(exchange):
            return
        async with self._lock:
            self._last_seen = self._clock.monotonic()
            self._buffer.append(exchange.in_message.body)
            if self._task is None or self._task.done():
                self._task = get_task_registry().create_task(
                    self._gap_watcher(), name=f"session-gap:{self.name}"
                )

    async def _gap_watcher(self) -> None:
        while True:
            await asyncio.sleep(self._gap / 2)
            async with self._lock:
                idle = self._clock.monotonic() - self._last_seen
                if idle >= self._gap and self._buffer:
                    bucket = list(self._buffer)
                    self._buffer.clear()
                else:
                    continue
            await self._emit(bucket)
            return


class GroupByKeyProcessor(_BaseWindow):
    """Группирует события по ключу в пределах окна.

    ``key_path`` — jmespath-выражение для извлечения ключа из body.
    При закрытии окна ``sink`` получает dict ``{key: [events...]}``.
    """

    def __init__(
        self,
        *,
        sink: Any,
        key_path: str,
        window_seconds: float = 60.0,
        name: str | None = None,
        clock: Clock | None = None,
    ) -> None:
        super().__init__(sink=sink, name=name or f"group-by:{key_path}", clock=clock)
        self._key_path = key_path
        self._window = window_seconds
        self._groups: dict[Any, list[Any]] = defaultdict(list)
        self._task: asyncio.Task | None = None

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        try:
            import jmespath

            key = jmespath.search(self._key_path, exchange.in_message.body)
        except Exception as _:
            key = None

        async with self._lock:
            self._groups[key].append(exchange.in_message.body)
            if self._task is None or self._task.done():
                self._task = get_task_registry().create_task(
                    self._flush_after_window(), name=f"group-by-flush:{self.name}"
                )

    async def _flush_after_window(self) -> None:
        await asyncio.sleep(self._window)
        async with self._lock:
            snapshot = dict(self._groups)
            self._groups.clear()
        if snapshot:
            try:
                result = self._sink(snapshot)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.error("GroupBy sink failed: %s", exc)
