from __future__ import annotations

"""S67 W1 - controller.py part of backpressure decomp.

StreamingBackpressureController (main controller, 11 methods).

Classes: StreamingBackpressureController.
"""

import asyncio
import time

from src.backend.core.logging import get_logger
from src.backend.core.resilience.backpressure.types import (
    BackpressureState,
    ConsumerControlProtocol,
)

# Backward-compat alias — original code used bare `logger` name.
logger = get_logger(__name__)
_logger = logger

# ---------------------------------------------------------------------------
# Protocols
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
