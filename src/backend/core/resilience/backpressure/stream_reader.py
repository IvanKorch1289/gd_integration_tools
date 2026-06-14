from __future__ import annotations

"""S67 W1 - stream_reader.py part of backpressure decomp.

AdaptiveStreamReader (3 methods).

Classes: AdaptiveStreamReader.
"""

from src.backend.core.logging import get_logger

_logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Protocols
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
            _logger.debug(
                "AdaptiveStreamReader: count %d → %d (util=%.2f)",
                self._current_count,
                new_count,
                utilization,
            )
            self._current_count = new_count
        return self._current_count
