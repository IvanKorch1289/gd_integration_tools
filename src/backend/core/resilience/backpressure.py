"""Sprint 6 K2 — backpressure model для streaming-сценариев.

Назначение:
    Управление backpressure для high-RPS streaming (FastStream Kafka,
    Redis Streams, NATS). Защита от OOM при 10× load spike через:

    * ``StreamingBackpressureController`` — координатор pause/resume для
      consumer'ов (FastStream Kafka ``consumer.pause/resume``).
    * ``AdaptiveStreamReader`` — adaptive batch size для Redis Streams
      ``XREAD count`` (увеличивает count при низкой нагрузке, уменьшает
      при backpressure).
    * ``AdaptiveBulkhead`` — semaphore с динамическим max_concurrent;
      HighWatermark trigger увеличивает лимит, LowWatermark — уменьшает.

Архитектура:
    Все компоненты не зависят от конкретного MQ-SDK — работают через
    Protocol-интерфейсы (V15 GAP-anal). Реальные адаптеры (FastStream,
    Redis Streams) подключаются в ``infrastructure/messaging/`` через DI.

Feature-flag: ``backpressure_streaming_enabled`` (default-OFF). При flag-OFF
все методы — no-op (нулевой overhead).

V15 R-V15-10 — auto-scaling 3 уровня (этот модуль — task-level scaling,
дополняет :class:`BulkheadScaler` в ``core/scaling/``).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

__all__ = (
    "AdaptiveBulkhead",
    "AdaptiveStreamReader",
    "BackpressureState",
    "ConsumerControlProtocol",
    "StreamingBackpressureController",
    "get_streaming_controller",
)

logger = logging.getLogger("core.resilience.backpressure")


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class ConsumerControlProtocol(Protocol):
    """Контракт для consumer'ов с pause/resume.

    Реализуется FastStream Kafka subscriber'ом, kafka-python consumer'ом,
    aiokafka и т.п. Sprint 6 K2 — Protocol-only, реальные адаптеры — Sprint 7.
    """

    async def pause(self) -> None:
        """Приостановить consumer (не fetch новые сообщения)."""
        ...

    async def resume(self) -> None:
        """Возобновить consumer."""
        ...


# ---------------------------------------------------------------------------
# State / metrics
# ---------------------------------------------------------------------------


@dataclass
class BackpressureState:
    """Текущее состояние backpressure.

    Attributes:
        queue_size: Размер in-flight очереди обработки.
        queue_limit: Максимально допустимый размер очереди.
        is_paused: Текущее состояние pause/resume.
        last_state_change_at: Время последнего изменения is_paused (monotonic).
    """

    queue_size: int = 0
    queue_limit: int = 1000
    is_paused: bool = False
    last_state_change_at: float = field(default_factory=time.monotonic)

    @property
    def utilization(self) -> float:
        """Текущая загрузка очереди в долях (0.0 - 1.0+)."""
        if self.queue_limit <= 0:
            return 0.0
        return self.queue_size / self.queue_limit


# ---------------------------------------------------------------------------
# StreamingBackpressureController
# ---------------------------------------------------------------------------


class StreamingBackpressureController:
    """Координатор pause/resume для streaming consumer'ов.

    Применение:
        При HighWatermark (default 0.85 utilization) → pause всех
        зарегистрированных consumer'ов. При LowWatermark (default 0.5) →
        resume. Гистерезис защищает от flapping.

    Args:
        high_watermark: Порог pause (utilization). Default 0.85.
        low_watermark: Порог resume. Default 0.5.
        check_interval_s: Период auto-check loop. Default 0.5s.
    """

    def __init__(
        self,
        *,
        high_watermark: float = 0.85,
        low_watermark: float = 0.5,
        check_interval_s: float = 0.5,
    ) -> None:
        """Создать контроллер с эмпирическими дефолтами."""
        if not (0.0 < low_watermark < high_watermark <= 1.0):
            raise ValueError("Требуется 0 < low_watermark < high_watermark <= 1.0")
        self._high = high_watermark
        self._low = low_watermark
        self._check_interval_s = check_interval_s
        self._consumers: dict[str, ConsumerControlProtocol] = {}
        self._state = BackpressureState()
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None

    @property
    def state(self) -> BackpressureState:
        """Текущее состояние backpressure (read-only)."""
        return self._state

    def register_consumer(self, name: str, consumer: ConsumerControlProtocol) -> None:
        """Зарегистрировать consumer для управления через pause/resume.

        Args:
            name: Логическое имя consumer'а.
            consumer: Объект с async-методами ``pause()`` / ``resume()``.
        """
        self._consumers[name] = consumer
        logger.debug("StreamingBackpressureController: consumer '%s' added", name)

    def update_queue_size(
        self, queue_size: int, queue_limit: int | None = None
    ) -> None:
        """Обновить размер in-flight очереди.

        Вызывается из middleware / DSL pipeline после каждого acquire/release.

        Args:
            queue_size: Текущий размер очереди.
            queue_limit: Опц. новый limit (override).
        """
        self._state.queue_size = queue_size
        if queue_limit is not None:
            self._state.queue_limit = queue_limit

    async def evaluate(self) -> bool:
        """Проверить порог backpressure и переключить pause/resume.

        Returns:
            True если состояние изменилось (pause↔resume).
        """
        if not self._is_flag_enabled():
            return False

        util = self._state.utilization

        if util >= self._high and not self._state.is_paused:
            await self._pause_all()
            self._state.is_paused = True
            self._state.last_state_change_at = time.monotonic()
            logger.info(
                "Backpressure: PAUSE (utilization=%.2f >= %.2f)", util, self._high
            )
            return True
        if util <= self._low and self._state.is_paused:
            await self._resume_all()
            self._state.is_paused = False
            self._state.last_state_change_at = time.monotonic()
            logger.info(
                "Backpressure: RESUME (utilization=%.2f <= %.2f)", util, self._low
            )
            return True
        return False

    async def start(self) -> None:
        """Запустить background-loop с auto-evaluate."""
        if self._task is not None and not self._task.done():
            logger.warning("StreamingBackpressureController: уже запущен")
            return
        self._stop_event = asyncio.Event()
        from src.backend.core.utils.task_registry import get_task_registry

        self._task = get_task_registry().create_task(
            self._loop(), name="streaming-backpressure-loop"
        )

    async def stop(self) -> None:
        """Остановить background-loop + resume всех consumer'ов."""
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except TimeoutError:
                self._task.cancel()
        if self._state.is_paused:
            await self._resume_all()
            self._state.is_paused = False

    async def _pause_all(self) -> None:
        """Pause все зарегистрированные consumer'ы (best-effort)."""
        for name, consumer in self._consumers.items():
            try:
                await consumer.pause()
            except Exception as exc:
                logger.warning("Backpressure pause '%s' failed: %s", name, exc)

    async def _resume_all(self) -> None:
        """Resume все зарегистрированные consumer'ы (best-effort)."""
        for name, consumer in self._consumers.items():
            try:
                await consumer.resume()
            except Exception as exc:
                logger.warning("Backpressure resume '%s' failed: %s", name, exc)

    async def _loop(self) -> None:
        """Background loop с периодическим evaluate."""
        if self._stop_event is None:
            return
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._check_interval_s
                )
            except TimeoutError:
                await self.evaluate()

    @staticmethod
    def _is_flag_enabled() -> bool:
        """Проверить feature-flag backpressure_streaming_enabled."""
        try:
            from src.backend.core.config.features import feature_flags

            return feature_flags.backpressure_streaming_enabled
        except Exception as _:
            return False


# ---------------------------------------------------------------------------
# AdaptiveStreamReader (Redis Streams)
# ---------------------------------------------------------------------------


class AdaptiveStreamReader:
    """Adaptive ``XREAD count`` для Redis Streams.

    При низкой нагрузке (utilization < adjust_low_threshold) batch size
    увеличивается, при высокой (> adjust_high_threshold) — уменьшается.
    Защищает от OOM при spike: чтение мелкими порциями.

    Args:
        initial_count: Начальный batch size (default 10).
        min_count: Минимум при backpressure (default 1).
        max_count: Максимум при низкой нагрузке (default 100).
        adjust_factor: Множитель изменения (default 1.5).
        adjust_high_threshold: Порог уменьшения (default 0.7 utilization).
        adjust_low_threshold: Порог увеличения (default 0.3 utilization).
    """

    def __init__(
        self,
        *,
        initial_count: int = 10,
        min_count: int = 1,
        max_count: int = 100,
        adjust_factor: float = 1.5,
        adjust_high_threshold: float = 0.7,
        adjust_low_threshold: float = 0.3,
    ) -> None:
        """Инициализировать с эмпирическими дефолтами."""
        if min_count < 1 or max_count < min_count:
            raise ValueError("min_count >= 1 и max_count >= min_count обязательны")
        if not (0.0 < adjust_low_threshold < adjust_high_threshold < 1.0):
            raise ValueError("Требуется 0 < adjust_low < adjust_high < 1.0")
        self._current_count = initial_count
        self._min_count = min_count
        self._max_count = max_count
        self._adjust_factor = adjust_factor
        self._adjust_high = adjust_high_threshold
        self._adjust_low = adjust_low_threshold

    @property
    def current_count(self) -> int:
        """Текущий batch size для XREAD."""
        return self._current_count

    def adjust(self, utilization: float) -> int:
        """Adaptive-корректировка batch size.

        Args:
            utilization: Текущая загрузка очереди (0.0 - 1.0).

        Returns:
            Новый batch size после корректировки.
        """
        if utilization >= self._adjust_high:
            # Backpressure — уменьшить batch
            new_count = max(
                self._min_count, int(self._current_count / self._adjust_factor)
            )
        elif utilization <= self._adjust_low:
            # Низкая нагрузка — увеличить batch
            new_count = min(
                self._max_count, int(self._current_count * self._adjust_factor)
            )
        else:
            # В норме — без изменений
            new_count = self._current_count

        if new_count != self._current_count:
            logger.debug(
                "AdaptiveStreamReader: count %d → %d (util=%.2f)",
                self._current_count,
                new_count,
                utilization,
            )
            self._current_count = new_count
        return self._current_count


# ---------------------------------------------------------------------------
# AdaptiveBulkhead
# ---------------------------------------------------------------------------


class AdaptiveBulkhead:
    """Bulkhead с динамическим max_concurrent.

    Дополнение к :class:`core.resilience.bulkhead.Bulkhead`. При устойчивой
    нагрузке выше HighWatermark — увеличивает max_concurrent (до max).
    При устойчиво низкой — уменьшает (до min).

    Args:
        min_concurrent: Минимум одновременных слотов.
        max_concurrent: Максимум одновременных слотов.
        initial_concurrent: Стартовое значение.
        adjust_step: Шаг изменения.
    """

    def __init__(
        self,
        *,
        min_concurrent: int = 2,
        max_concurrent: int = 50,
        initial_concurrent: int = 10,
        adjust_step: int = 2,
    ) -> None:
        """Инициализировать с заданными порогами."""
        if min_concurrent < 1 or max_concurrent < min_concurrent:
            raise ValueError("min >= 1 и max >= min обязательны")
        if not (min_concurrent <= initial_concurrent <= max_concurrent):
            raise ValueError("min <= initial <= max обязательно")
        self._min = min_concurrent
        self._max = max_concurrent
        self._current = initial_concurrent
        self._adjust_step = adjust_step
        self._semaphore = asyncio.Semaphore(initial_concurrent)
        self._in_flight = 0

    @property
    def current_concurrent(self) -> int:
        """Текущий effective max_concurrent."""
        return self._current

    @property
    def in_flight(self) -> int:
        """Сколько слотов сейчас занято."""
        return self._in_flight

    async def acquire(self, timeout: float | None = None) -> bool:
        """Захватить слот в bulkhead.

        Args:
            timeout: Опц. таймаут ожидания (сек).

        Returns:
            True если слот захвачен; False при timeout.
        """
        try:
            if timeout is None:
                await self._semaphore.acquire()
            else:
                await asyncio.wait_for(self._semaphore.acquire(), timeout=timeout)
            self._in_flight += 1
            return True
        except TimeoutError:
            return False
        except asyncio.CancelledError:
            # Если CancelledError дошел сюда, семафор мог быть захвачен
            # внутри wait_for, но _in_flight еще не инкрементирован.
            # Компенсируем возможную утечку слота, но защищаемся от over-release
            # (если CancelledError пришел до фактического захвата).
            if self._semaphore._value < self._current:
                self._semaphore.release()
            raise

    def release(self) -> None:
        """Освободить слот."""
        self._semaphore.release()
        self._in_flight = max(0, self._in_flight - 1)

    def scale_up(self) -> int:
        """Увеличить max_concurrent на adjust_step (не выше max).

        Returns:
            Новое значение current_concurrent.
        """
        new_value = min(self._max, self._current + self._adjust_step)
        if new_value > self._current:
            # Освободить дополнительные слоты в semaphore.
            for _ in range(new_value - self._current):
                self._semaphore.release()
            self._current = new_value
            logger.info("AdaptiveBulkhead: scale_up → %d", self._current)
        return self._current

    def scale_down(self) -> int:
        """Уменьшить max_concurrent на adjust_step (не ниже min).

        NOTE: Реальное уменьшение происходит постепенно через acquire'ы
        без release (текущие in-flight не отзываются).

        Returns:
            Новое значение current_concurrent.
        """
        new_value = max(self._min, self._current - self._adjust_step)
        if new_value < self._current:
            self._current = new_value
            logger.info("AdaptiveBulkhead: scale_down → %d", self._current)
        return self._current


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_controller_instance: StreamingBackpressureController | None = None


def get_streaming_controller() -> StreamingBackpressureController:
    """Singleton — один экземпляр StreamingBackpressureController."""
    global _controller_instance
    if _controller_instance is None:
        _controller_instance = StreamingBackpressureController()
    return _controller_instance
