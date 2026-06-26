"""Oracle CDC source без Kafka (S171 M18.2, D249).

Polling-based CDC для Oracle через oracledb (async).
Использует watermark (SCN или timestamp) для tracking изменений.

Per user directive: "возможность запустить CDC к Oracle и без Kafka".
Pattern (D249, Ponytail): thin wrapper, no abstractions.

ПРЕИМУЩЕСТВА над Debezium+Kafka:
- Не требует Kafka (lower infra cost)
- Не требует отдельного Debezium connector
- Работает через polling (без streaming)

ОГРАНИЧЕНИЯ:
- Polling latency (настраивается poll_interval_seconds, default 5s)
- Не получает DDL (только DML через watermark)
- Требует oracledb (>= 2.0) с async support
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from src.backend.core.logging import get_logger

_logger = get_logger("infra.cdc.oracle")

__all__ = ("OracleCDCSource",)


class OracleCDCSource:
    """Polling-based CDC source для Oracle.

    Args:
        dsn: Oracle DSN (Data Source Name), например
            ``oracle://user:pass@host:1521/ORCLPDB1``.
        schema: Schema name для отслеживания.
        tables: Tuple с именами таблиц.
        poll_interval_seconds: Интервал polling (default 5s).
        watermark_column: Колонка для tracking (default ``updated_at``).
    """

    def __init__(
        self,
        *,
        dsn: str,
        schema: str,
        tables: tuple[str, ...],
        poll_interval_seconds: float = 5.0,
        watermark_column: str = "updated_at",
    ) -> None:
        self.dsn = dsn
        self.schema = schema
        self.tables = tables
        self.poll_interval_seconds = poll_interval_seconds
        self.watermark_column = watermark_column

    async def _fetch_changes_since(
        self, table: str, *, watermark: int | float
    ) -> list[dict[str, Any]]:
        """Получить изменения с момента watermark.

        Args:
            table: Полное имя таблицы (schema.table).
            watermark: Последний SCN (для SCN-based) или timestamp epoch.

        Returns:
            Список dict'ов с новыми/изменёнными строками.
        """
        try:
            import oracledb  # lazy
        except ImportError as exc:
            raise ImportError(
                "oracledb не установлен. "
                "Установите: pip install oracledb>=2.0"
            ) from exc

        loop = asyncio.get_event_loop()
        rows = await asyncio.to_thread(
            self._sync_fetch, oracledb, table, watermark
        )
        _logger.debug(
            "cdc.oracle.fetch table=%s watermark=%s count=%d",
            table, watermark, len(rows),
        )
        return rows

    def _sync_fetch(
        self,
        oracledb: Any,
        table: str,
        watermark: int | float,
    ) -> list[dict[str, Any]]:
        """Sync часть: oracledb.connect + execute."""
        conn = oracledb.connect(self.dsn)
        try:
            cursor = conn.cursor()
            query = (
                f"SELECT * FROM {table} "
                f"WHERE {self.watermark_column} > :watermark "
                f"ORDER BY {self.watermark_column} ASC"
            )
            cursor.execute(query, watermark=watermark)
            columns = [c[0].lower() for c in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            conn.close()

    async def poll(self, last_watermark: int | float = 0) -> list[dict[str, Any]]:
        """Один polling cycle: fetch changes для всех tables.

        Returns:
            Combined список изменений со всех tables.
        """
        all_changes: list[dict[str, Any]] = []
        for table in self.tables:
            full_table = f"{self.schema}.{table}"
            changes = await self._fetch_changes_since(
                full_table, watermark=last_watermark
            )
            for ch in changes:
                ch["_table"] = full_table
            all_changes.extend(changes)
        return all_changes

    async def stream(self) -> Any:
        """Async generator для непрерывного polling.

        Yields:
            Список изменений каждый poll_interval_seconds.
        """
        last_watermark: int | float = 0
        while True:
            changes = await self.poll(last_watermark=last_watermark)
            if changes:
                # Update watermark до max(updated_at) в batch
                timestamps = [
                    ch.get(self.watermark_column) for ch in changes
                ]
                timestamps = [t for t in timestamps if t is not None]
                if timestamps:
                    last_watermark = max(
                        t.timestamp() if isinstance(t, datetime) else t
                        for t in timestamps
                    )
                yield changes
            await asyncio.sleep(self.poll_interval_seconds)
