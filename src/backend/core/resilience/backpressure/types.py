from __future__ import annotations
"""S67 W1 - types.py part of backpressure decomp.

core types (protocol + state dataclass).

Classes: ConsumerControlProtocol, BackpressureState.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from src.backend.core.logging import get_logger

# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------

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

