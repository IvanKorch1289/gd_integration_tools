"""In-memory реализация :class:`WatermarkStore` (W14.5).

Используется в dev_light-профиле и unit-тестах. Состояние живёт в RAM
текущего процесса и теряется при рестарте — для прода предусмотрен
``PostgresWatermarkStore``.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

from src.core.types.watermark import WatermarkState

__all__ = ("MemoryWatermarkStore",)


class MemoryWatermarkStore:
    """Async in-memory хранилище ``WatermarkState`` (один процесс).

    Каждый ``save`` копирует переданный state, чтобы дальнейшие мутации
    у вызывающего не были видны в хранилище и наоборот при ``load``.
    """

    def __init__(self) -> None:
        self._data: dict[tuple[str, str], WatermarkState] = {}
        self._lock = asyncio.Lock()

    async def load(self, route_id: str, processor_name: str) -> WatermarkState | None:
        async with self._lock:
            stored = self._data.get((route_id, processor_name))
            return replace(stored) if stored is not None else None

    async def save(
        self, route_id: str, processor_name: str, state: WatermarkState
    ) -> None:
        async with self._lock:
            self._data[(route_id, processor_name)] = replace(state)
