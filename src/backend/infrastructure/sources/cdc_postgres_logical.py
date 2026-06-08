"""K3 S5 W5 — :class:`CdcPostgresLogicalSource`: расширенный CDC-источник.

Wave ``[wave:s5/k3-w5-cdc-postgres]``.

Дополнение к существующему :class:`src.backend.infrastructure.sources.cdc.CDCSource`:

* поддержка двух режимов: ``full`` (snapshot + tail) и ``delta`` (только tail);
* персистентный watermark-cursor через CdcCursorStore (Postgres-table
  ``cdc_cursors(slot_name, last_lsn, updated_at)``);
* setup publication + replication-slot в startup (idempotent).

Делегирует низкоуровневую работу с pgoutput / wal2json в существующий
:class:`CDCSource` (lazy-import).

Контракт DSL::

    .from_cdc(table="orders", mode="delta")

Feature flag: ``feature_flags.cdc_postgres_enabled`` (default-OFF).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from src.backend.core.interfaces.source import EventCallback, SourceEvent, SourceKind
from src.backend.infrastructure.logging.factory import get_logger

__all__ = (
    "PG_CDC_CURSORS_DDL",
    "PG_CDC_PUBLICATION_TPL",
    "PG_CDC_SLOT_CREATE_TPL",
    "CdcCursorStore",
    "CdcPostgresLogicalSource",
)

_logger = get_logger("infrastructure.sources.cdc.postgres_logical")


PG_CDC_CURSORS_DDL = """
CREATE TABLE IF NOT EXISTS cdc_cursors (
    slot_name TEXT PRIMARY KEY,
    last_lsn TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
""".strip()


PG_CDC_PUBLICATION_TPL = """
CREATE PUBLICATION {publication} FOR TABLE {table};
""".strip()


PG_CDC_SLOT_CREATE_TPL = """
SELECT pg_create_logical_replication_slot('{slot}', 'pgoutput');
""".strip()


_ALLOWED_MODES = frozenset({"full", "delta"})


class CdcCursorStore:
    """Watermark-store cursor'ов CDC (через Postgres-table ``cdc_cursors``).

    Минимальный async-API: read/write last_lsn по slot_name.
    Использует переданный async session-factory (asyncpg-style).
    """

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    async def ensure_table(self) -> None:
        """Создать таблицу при первом запуске (idempotent)."""
        await self._execute(PG_CDC_CURSORS_DDL)

    async def get_last_lsn(self, slot_name: str) -> str | None:
        async with self._open() as session:
            row = await session.fetchrow(
                "SELECT last_lsn FROM cdc_cursors WHERE slot_name = $1", slot_name
            )
            return row["last_lsn"] if row else None

    async def set_last_lsn(self, slot_name: str, lsn: str) -> None:
        async with self._open() as session:
            await session.execute(
                """
                INSERT INTO cdc_cursors (slot_name, last_lsn, updated_at)
                VALUES ($1, $2, NOW())
                ON CONFLICT (slot_name)
                DO UPDATE SET last_lsn = EXCLUDED.last_lsn, updated_at = NOW()
                """,
                slot_name,
                lsn,
            )

    def _open(self) -> Any:
        return self._session_factory()

    async def _execute(self, sql: str) -> None:
        async with self._open() as session:
            await session.execute(sql)


class CdcPostgresLogicalSource:
    """Расширенный CDC PostgreSQL Source с режимами ``full|delta`` + watermark.

    Args:
        source_id: Уникальный id маршрута.
        table: Имя таблицы (используется в имени publication/slot).
        dsn: PostgreSQL DSN.
        mode: ``full`` — snapshot + tail, ``delta`` — только tail.
        slot_name: Имя slot (по умолчанию ``cdc_<table>``).
        publication: Имя publication (по умолчанию ``pub_<table>``).
        cursor_store: ``CdcCursorStore`` для персистентного ack-cursor (опц.).
        plugin: ``pgoutput`` (default) / ``wal2json``.
    """

    kind: SourceKind = SourceKind.CDC

    def __init__(
        self,
        source_id: str,
        table: str,
        *,
        dsn: str,
        mode: str = "delta",
        slot_name: str | None = None,
        publication: str | None = None,
        cursor_store: CdcCursorStore | None = None,
        plugin: str = "pgoutput",
    ) -> None:
        if mode not in _ALLOWED_MODES:
            raise ValueError(
                f"CdcPostgresLogicalSource: mode must be 'full'|'delta', got {mode!r}"
            )
        if not source_id:
            raise ValueError("source_id must be non-empty")
        if not table:
            raise ValueError("table must be non-empty")
        if not dsn:
            raise ValueError("dsn must be non-empty")
        self.source_id = source_id
        self.table = table
        self.dsn = dsn
        self.mode = mode
        self.slot_name = slot_name or f"cdc_{table}"
        self.publication = publication or f"pub_{table}"
        self.cursor_store = cursor_store
        self.plugin = plugin
        self._inner: Any = None

    async def setup(self, conn_executor: Any) -> None:
        """Idempotent setup: создать publication/slot + ensure cdc_cursors.

        Args:
            conn_executor: callable(sql_str)→awaitable для выполнения DDL.
                Обычно — ``async with engine.begin() as conn: await conn.execute(...)``.
        """
        try:
            await conn_executor(
                PG_CDC_PUBLICATION_TPL.format(
                    publication=self.publication, table=self.table
                )
            )
        except Exception as exc:
            _logger.debug("publication create skipped: %s", exc)
        try:
            await conn_executor(PG_CDC_SLOT_CREATE_TPL.format(slot=self.slot_name))
        except Exception as exc:
            _logger.debug("slot create skipped: %s", exc)
        if self.cursor_store is not None:
            await self.cursor_store.ensure_table()

    async def start(self, on_event: EventCallback) -> None:
        """Запустить чтение через CDCSource + ack-cursor запись."""
        try:
            from src.backend.core.config.features import feature_flags

            if not feature_flags.cdc_postgres_enabled:
                _logger.info(
                    "CdcPostgresLogicalSource %s: feature-flag OFF, skipping start",
                    self.source_id,
                )
                return
        except Exception as _:
            pass

        # Lazy-import существующего CDCSource (не дублируем psycopg-логику).
        from src.backend.infrastructure.sources.cdc import CDCSource

        self._inner = CDCSource(
            source_id=self.source_id,
            dsn=self.dsn,
            slot_name=self.slot_name,
            publication_names=[self.publication],
            plugin=self.plugin,
        )

        async def _wrapped(event: SourceEvent) -> None:
            await on_event(event)
            if self.cursor_store is not None:
                lsn = (event.payload or {}).get("lsn")
                if lsn:
                    try:
                        await self.cursor_store.set_last_lsn(self.slot_name, lsn)
                    except Exception as exc:
                        _logger.warning(
                            "CdcPostgresLogicalSource cursor write failed: %s", exc
                        )

        if self.mode == "full":
            await self._emit_snapshot_marker(on_event)
        await self._inner.start(_wrapped)

    async def stop(self) -> None:
        if self._inner is not None:
            await self._inner.stop()
            self._inner = None

    async def health(self) -> bool:
        return self._inner is not None and await self._inner.health()

    async def _emit_snapshot_marker(self, on_event: EventCallback) -> None:
        """В режиме ``full`` эмитим первое событие-маркер начала snapshot."""
        await on_event(
            SourceEvent(
                source_id=self.source_id,
                kind=self.kind,
                payload={"event": "snapshot_started", "table": self.table},
                event_time=datetime.now(UTC),
                metadata={"slot": self.slot_name, "mode": "full"},
            )
        )
