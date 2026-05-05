"""W14.5 — Protocol персистентного хранилища ``WatermarkState``.

Цель — пережить рестарт сервиса: после старта оконные процессоры
загружают последний известный watermark по ``(route_id, processor_name)``
и не дропают исторически late events после рестарта без необходимости.

Async-Protocol: PG-реализация делает ``await session.execute(...)``;
in-memory не требует await внутри, но соответствует контракту.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.core.types.watermark import WatermarkState

__all__ = ("WatermarkStore",)


@runtime_checkable
class WatermarkStore(Protocol):
    """Персистентное хранилище watermark-состояний.

    Реализации:

    * ``infrastructure.watermark.postgres_store.PostgresWatermarkStore`` —
      production (таблица ``streaming_watermarks``).
    * ``infrastructure.watermark.memory_store.MemoryWatermarkStore`` —
      dev_light / unit-тесты.

    Идентификатор записи — пара ``(route_id, processor_name)``.
    """

    async def load(self, route_id: str, processor_name: str) -> WatermarkState | None:
        """Загрузить состояние, если оно ранее сохранялось.

        Args:
            route_id: Идентификатор маршрута.
            processor_name: Имя процессора (``BaseProcessor.name``).

        Returns:
            ``WatermarkState`` или ``None``, если записи нет.
        """
        ...

    async def save(
        self, route_id: str, processor_name: str, state: WatermarkState
    ) -> None:
        """Сохранить (upsert) текущее состояние.

        Args:
            route_id: Идентификатор маршрута.
            processor_name: Имя процессора.
            state: Снимок ``WatermarkState`` для сохранения.
        """
        ...
