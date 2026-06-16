"""S67 W1 - bulkhead.py part of backpressure decomp.

AdaptiveBulkhead (7 methods).

Classes: AdaptiveBulkhead.
"""

from __future__ import annotations

import asyncio

from src.backend.core.logging import get_logger

_logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Protocols
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
            _logger.info("AdaptiveBulkhead: scale_up → %d", self._current)
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
            _logger.info("AdaptiveBulkhead: scale_down → %d", self._current)
        return self._current
