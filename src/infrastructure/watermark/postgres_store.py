"""PostgreSQL-реализация :class:`WatermarkStore` (W14.5).

Используется в prod-профилях. Запись/чтение идут через
:class:`DatabaseSessionManager`. Таблица создаётся миграцией
``a7b8c9d0e1f2_streaming_watermarks``.

Конкуренция: один процессор пишет одну строку (``route_id``, ``name``);
конкурентный апдейт между процессами — last-write-wins на стороне SQL.
``current`` watermark монотонно неубывает в коде ``WatermarkState.advance``,
поэтому на уровне таблицы дополнительный CAS не нужен (state, который
персистится, уже не откатится назад в одном процессе).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.types.watermark import WatermarkState
from src.infrastructure.database.session_manager import DatabaseSessionManager

__all__ = ("PostgresWatermarkStore",)


_LOAD_SQL = text(
    """
    SELECT current_watermark, advanced_at, late_events_total
    FROM streaming_watermarks
    WHERE route_id = :route_id AND processor_name = :processor_name
    """
)

_UPSERT_SQL = text(
    """
    INSERT INTO streaming_watermarks
        (route_id, processor_name, current_watermark, advanced_at,
         late_events_total, updated_at)
    VALUES (:route_id, :processor_name, :current, :advanced_at,
            :late_events_total, NOW())
    ON CONFLICT (route_id, processor_name) DO UPDATE SET
        current_watermark = EXCLUDED.current_watermark,
        advanced_at       = EXCLUDED.advanced_at,
        late_events_total = EXCLUDED.late_events_total,
        updated_at        = NOW()
    """
)


class PostgresWatermarkStore:
    """PG-реализация ``WatermarkStore``.

    Args:
        session_manager: ``DatabaseSessionManager`` (как правило, главный).
    """

    def __init__(self, session_manager: DatabaseSessionManager) -> None:
        self._sm = session_manager

    async def load(
        self, route_id: str, processor_name: str
    ) -> WatermarkState | None:
        async with self._sm.create_session() as session:
            row = await self._fetch_row(session, route_id, processor_name)
        if row is None:
            return None
        current, advanced_at, late_total = row
        return WatermarkState(
            current=float(current),
            advanced_at=float(advanced_at),
            late_events_total=int(late_total),
        )

    async def save(
        self, route_id: str, processor_name: str, state: WatermarkState
    ) -> None:
        # ``-inf`` не сериализуется в double precision у части драйверов; в
        # этом случае персистить нечего (advance ещё не происходил).
        if state.current == float("-inf"):
            return
        async with self._sm.create_session() as session:
            async with self._sm.transaction(session):
                await session.execute(
                    _UPSERT_SQL,
                    {
                        "route_id": route_id,
                        "processor_name": processor_name,
                        "current": state.current,
                        "advanced_at": state.advanced_at,
                        "late_events_total": state.late_events_total,
                    },
                )

    @staticmethod
    async def _fetch_row(
        session: AsyncSession, route_id: str, processor_name: str
    ) -> tuple[float, float, int] | None:
        result = await session.execute(
            _LOAD_SQL,
            {"route_id": route_id, "processor_name": processor_name},
        )
        row = result.first()
        if row is None:
            return None
        return (row[0], row[1], row[2])
