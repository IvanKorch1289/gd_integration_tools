"""W14.3 — состояние watermark для оконных процессоров.

Watermark — wall-clock секунды (Unix epoch), маркирующий граничное время
"не позже которого ждём событий". Сообщение с ``event_time < watermark``
считается *late event*.

Определены типы:

* :class:`WatermarkState` — текущее состояние одного потока (источника или
  процессора). Хранит ``current``, ``advanced_at`` (Wall) и счётчик
  ``late_events_total`` для метрик.
* :class:`LatePolicy` — политика обработки late events.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = ("WatermarkState", "LatePolicy")


class LatePolicy(str, Enum):
    """Политика обработки late events.

    * ``DROP`` — отбросить, инкрементировать метрику.
    * ``SIDE_OUTPUT`` — направить в side-channel (DLQ через ReplyChannel
      или отдельный sink).
    * ``REPROCESS`` — пересчитать окно (дорого, только если бизнес-логика
      допускает мутации aggregate).
    """

    DROP = "drop"
    SIDE_OUTPUT = "side_output"
    REPROCESS = "reprocess"


@dataclass(slots=True)
class WatermarkState:
    """Снимок состояния watermark одного потока.

    Attributes:
        current: Текущее значение watermark (wall-clock секунды).
            Монотонно неубывающее.
        advanced_at: Когда watermark был обновлён последний раз
            (wall-clock из ``Clock.time()``); используется для
            детекции stall-партиций.
        late_events_total: Счётчик отброшенных/перенаправленных late
            events с момента старта процесса (для Prometheus gauge/counter).
    """

    current: float = float("-inf")
    advanced_at: float = 0.0
    late_events_total: int = 0

    def advance(self, new_value: float, *, now: float) -> bool:
        """Попытаться продвинуть watermark.

        Args:
            new_value: Кандидат на новое значение.
            now: Текущий wall-clock (``Clock.time()``).

        Returns:
            ``True`` если watermark продвинулся, ``False`` если
            ``new_value <= current`` (монотонность).
        """
        if new_value <= self.current:
            return False
        self.current = new_value
        self.advanced_at = now
        return True

    def is_late(self, event_time: float, *, allowed_lateness: float = 0.0) -> bool:
        """Проверить, является ли событие late.

        Args:
            event_time: Wall-clock секунды события.
            allowed_lateness: Дополнительный допуск в секундах.

        Returns:
            ``True`` если ``event_time + allowed_lateness < current``.
        """
        return (event_time + allowed_lateness) < self.current
