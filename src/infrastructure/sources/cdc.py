"""W23.2 — :class:`CDCSource` (PostgreSQL logical replication).

Подключается к PG через psycopg3 в режиме ``replication=True``,
запускает чтение logical-replication-slot (плагин ``pgoutput`` или
``wal2json``) и эмитит ``SourceEvent`` на каждое сообщение из WAL-стрима.

Зависимость ``psycopg[binary]>=3.1`` опциональная (``sources-cdc`` extra).
Если не установлена — конструктор отрабатывает, но ``start()`` поднимет
понятный ``RuntimeError`` с инструкцией установки.

Slot и publication должны существовать. Их создание — задача миграции
или DBA-инструкции (см. ``docs/reference/dsl/sources.md``).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from src.core.interfaces.source import EventCallback, SourceEvent, SourceKind
from src.infrastructure.sources._lifecycle import graceful_cancel

__all__ = ("CDCSource",)

logger = logging.getLogger("infrastructure.sources.cdc")


class CDCSource:
    """PostgreSQL logical replication Source.

    Args:
        source_id: Уникальный id.
        dsn: PostgreSQL DSN (``postgres://user:pass@host/db``); пользователь
            должен иметь роль ``REPLICATION``.
        slot_name: Имя logical replication slot (создаётся снаружи).
        publication_names: Список ``PUBLICATION`` для plug-in ``pgoutput``.
        plugin: Имя plug-in (``pgoutput`` default; альтернатива — ``wal2json``).
        decode_options: Дополнительные опции декодирования (зависят от plug-in).
        poll_interval_seconds: Интервал опроса слота при отсутствии сообщений.
    """

    kind: SourceKind = SourceKind.CDC

    def __init__(
        self,
        source_id: str,
        *,
        dsn: str,
        slot_name: str,
        publication_names: list[str] | None = None,
        plugin: str = "pgoutput",
        decode_options: dict[str, str] | None = None,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self.source_id = source_id
        self._dsn = dsn
        self._slot = slot_name
        self._publications = publication_names or []
        self._plugin = plugin
        self._decode_options = decode_options or {}
        self._interval = poll_interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def start(self, on_event: EventCallback) -> None:
        if self._task is not None and not self._task.done():
            raise RuntimeError(f"CDCSource(id={self.source_id!r}) уже запущен")
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(on_event))
        logger.info(
            "CDCSource started: id=%s slot=%s plugin=%s",
            self.source_id,
            self._slot,
            self._plugin,
        )

    async def stop(self) -> None:
        self._stop_event.set()
        await graceful_cancel(self._task, source_id=self.source_id)
        self._task = None

    async def health(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _run(self, on_event: EventCallback) -> None:
        try:
            from psycopg import AsyncConnection  # type: ignore[import-not-found]
            from psycopg.replication import (  # type: ignore[import-not-found]
                LogicalReplicationConnection,
            )
        except ImportError as exc:
            raise RuntimeError(
                "psycopg[binary]>=3.1 не установлен; добавь optional extra "
                "`sources-cdc` в pyproject.toml для использования CDCSource."
            ) from exc

        # Опции для pgoutput (требует список publication-names).
        options: dict[str, str] = dict(self._decode_options)
        if self._plugin == "pgoutput" and self._publications:
            options.setdefault("proto_version", "1")
            options.setdefault("publication_names", ",".join(self._publications))

        async with await AsyncConnection.connect(
            self._dsn, autocommit=True, connection_class=LogicalReplicationConnection
        ) as conn:
            try:
                await conn.execute(
                    "SELECT * FROM pg_create_logical_replication_slot(%s, %s)",
                    (self._slot, self._plugin),
                )
            except Exception as exc:
                # Slot уже существует — нормально для повторного запуска.
                logger.debug(
                    "CDCSource %s: slot create skipped: %s", self._slot, exc
                )
            cursor = conn.cursor()
            await cursor.start_replication(
                slot_name=self._slot, options=options, decode=False
            )
            try:
                async for msg in cursor:
                    if self._stop_event.is_set():
                        break
                    await self._emit(on_event, msg)
                    if hasattr(msg, "cursor"):
                        await msg.cursor.send_feedback(flush_lsn=msg.data_start)
            finally:
                try:
                    await cursor.close()
                except Exception as exc:
                    logger.debug(
                        "CDCSource %s: cursor close warning: %s", self._slot, exc
                    )

    async def _emit(self, on_event: EventCallback, msg: Any) -> None:
        try:
            payload = {
                "lsn": str(getattr(msg, "data_start", "")),
                "wal_end": str(getattr(msg, "wal_end", "")),
                "data": (
                    msg.payload.decode(errors="replace")
                    if hasattr(msg, "payload") and isinstance(msg.payload, (bytes, bytearray))
                    else getattr(msg, "payload", None)
                ),
            }
            event = SourceEvent(
                source_id=self.source_id,
                kind=self.kind,
                payload=payload,
                event_time=datetime.now(UTC),
                metadata={"slot": self._slot, "plugin": self._plugin},
            )
            await on_event(event)
        except Exception as exc:
            logger.error("CDCSource on_event failed: %s", exc)


