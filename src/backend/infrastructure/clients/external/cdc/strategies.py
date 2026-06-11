from __future__ import annotations

"""S60 W2 — strategies.py part of cdc decomp.

Classes: _CDCStrategy, _PollingStrategy, _ListenNotifyStrategy, _LogMinerStrategy.

4 strategies: base _CDCStrategy + 3 concrete (Polling/ListenNotify/LogMiner).
"""

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from src.backend.infrastructure.clients.external.cdc.events import (
    CDCEvent,  # S60 W2: cross-import
)


class _CDCStrategy(ABC):
    """Базовый класс стратегии обнаружения изменений."""

    @abstractmethod
    async def run(
        self,
        sub: CDCSubscription,
        dispatch: Callable[[CDCSubscription, CDCEvent], Awaitable[None]],
    ) -> None: ...


class _PollingStrategy(_CDCStrategy):
    """Polling-based CDC: запрос по timestamp_column.

    Работает с любой БД (PostgreSQL, Oracle, MySQL и т.д.).
    Не различает INSERT от UPDATE — оба попадают как UPSERT.
    Не обнаруживает DELETE.

    Multi-instance safety (MI-4):
    - Cursor _last_check хранится в Redis через RedisCursor (CAS)
    - Несколько инстансов могут безопасно подписываться на одну таблицу
    - Дублирование событий предотвращается atomic try_advance()
    """

    def __init__(self) -> None:
        self._last_check_local: dict[str, datetime] = {}

    async def _get_cursor(self, key: str, default: datetime) -> datetime:
        """Загружает cursor из Redis (или возвращает default при недоступности)."""
        try:
            from src.backend.infrastructure.clients.storage.redis_coordinator import (
                RedisCursor,
            )

            cursor = RedisCursor(f"cdc:cursor:{key}")
            stored = await cursor.get_or_init(default.isoformat())
            return datetime.fromisoformat(stored)
        except ImportError, ValueError, Exception:
            return self._last_check_local.get(key, default)

    async def _advance_cursor(self, key: str, new_value: datetime) -> None:
        """Atomic advance cursor через Redis CAS."""
        try:
            from src.backend.infrastructure.clients.storage.redis_coordinator import (
                RedisCursor,
            )

            cursor = RedisCursor(f"cdc:cursor:{key}")
            await cursor.try_advance(new_value.isoformat())
        except ImportError, Exception:
            logger.debug("CDC cursor advance via Redis failed", exc_info=True)
        self._last_check_local[key] = new_value

    async def run(
        self,
        sub: CDCSubscription,
        dispatch: Callable[[CDCSubscription, CDCEvent], Awaitable[None]],
    ) -> None:
        try:
            from sqlalchemy import text

            from src.backend.infrastructure.database.database import (
                get_external_db_manager,
            )
        except ImportError:
            logger.error("CDC polling: SQLAlchemy or external DB manager unavailable")
            return

        try:
            db = get_external_db_manager(sub.profile)
        except (ValueError, KeyError, AttributeError) as exc:
            logger.error("CDC polling: profile '%s' not found: %s", sub.profile, exc)
            return

        engine = db.get_async_engine()

        while sub.active:
            for table in sub.tables:
                key = f"{sub.profile}:{table}"
                last = await self._get_cursor(key, datetime.now(UTC))

                try:
                    async with engine.connect() as conn:
                        query = text(
                            f"SELECT * FROM {table} "  # table/timestamp_column — DSL/config параметры подписки, не runtime user input  # noqa: S608  # internal query with controlled parameters
                            f"WHERE {sub.timestamp_column} > :last "
                            f"ORDER BY {sub.timestamp_column} "
                            f"LIMIT :limit"
                        )
                        result = await conn.execute(
                            query, {"last": last, "limit": sub.batch_size}
                        )
                        rows = [dict(row._mapping) for row in result.fetchall()]

                    if rows:
                        max_ts = last
                        for row in rows:
                            ts_val = row.get(sub.timestamp_column)
                            if isinstance(ts_val, datetime) and ts_val > max_ts:
                                max_ts = ts_val

                            event = CDCEvent(
                                operation="UPSERT",
                                table=table,
                                timestamp=(
                                    ts_val.isoformat()
                                    if isinstance(ts_val, datetime)
                                    else datetime.now(UTC).isoformat()
                                ),
                                profile=sub.profile,
                                new=row,
                            )
                            await dispatch(sub, event)

                        await self._advance_cursor(key, max_ts)

                except Exception as exc:
                    logger.warning(
                        "CDC polling error [%s/%s]: %s", sub.profile, table, exc
                    )

            await asyncio.sleep(sub.interval)


class _ListenNotifyStrategy(_CDCStrategy):
    """PostgreSQL LISTEN/NOTIFY — low-latency CDC.

    Требует триггер на таблице, который вызывает pg_notify() с JSON payload:
        CREATE OR REPLACE FUNCTION notify_cdc() RETURNS TRIGGER AS $$
        BEGIN
            PERFORM pg_notify('cdc_orders', json_build_object(
                'operation', TG_OP,
                'table', TG_TABLE_NAME,
                'new', row_to_json(NEW),
                'old', row_to_json(OLD)
            )::text);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """

    async def run(
        self,
        sub: CDCSubscription,
        dispatch: Callable[[CDCSubscription, CDCEvent], Awaitable[None]],
    ) -> None:
        try:
            import asyncpg
            import orjson

            from src.backend.core.config.external_databases.registry import (
                external_databases_settings,
            )
        except ImportError:
            logger.error("CDC listen/notify: asyncpg not installed")
            return

        try:
            profile = external_databases_settings.get_profile(sub.profile)
        except ValueError as exc:
            logger.error("CDC listen/notify: %s", exc)
            return

        channel = sub.channel or f"cdc_{sub.tables[0]}" if sub.tables else "cdc_events"

        try:
            conn = await asyncpg.connect(
                host=profile.host,
                port=profile.port,
                user=profile.username,
                password=profile.password.get_secret_value(),
                database=profile.db_name,
            )
        except Exception as exc:
            logger.error("CDC listen/notify: connection failed: %s", exc)
            return

        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1000)

        def _notify_handler(_conn_: Any, _pid: int, _chan: str, payload: str) -> None:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning("CDC notify queue full, dropping event")

        try:
            await conn.add_listener(channel, _notify_handler)
            logger.info("CDC LISTEN on channel '%s' (profile=%s)", channel, sub.profile)

            while sub.active:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=1.0)
                except TimeoutError:
                    continue

                try:
                    data = orjson.loads(payload)
                    event = CDCEvent(
                        operation=str(data.get("operation", "UNKNOWN")).upper(),
                        table=str(data.get("table", "")),
                        timestamp=data.get("timestamp")
                        or datetime.now(UTC).isoformat(),
                        profile=sub.profile,
                        new=data.get("new"),
                        old=data.get("old"),
                    )
                    await dispatch(sub, event)
                except (orjson.JSONDecodeError, ValueError, TypeError) as exc:
                    logger.warning(
                        "CDC notify parse error: %s | payload=%s", exc, payload[:200]
                    )
        finally:
            try:
                await conn.remove_listener(channel, _notify_handler)
                await conn.close()
            except Exception as _:
                logger.debug("CDC LISTEN connection cleanup failed", exc_info=True)


class _LogMinerStrategy(_CDCStrategy):
    """Oracle LogMiner — читает V$LOGMNR_CONTENTS.

    Требует привилегии SELECT ANY TRANSACTION, EXECUTE_CATALOG_ROLE.
    Производит базовый парсинг SQL_REDO для определения операции.
    """

    def __init__(self) -> None:
        self._last_scn: dict[str, int] = {}

    async def run(
        self,
        sub: CDCSubscription,
        dispatch: Callable[[CDCSubscription, CDCEvent], Awaitable[None]],
    ) -> None:
        try:
            from sqlalchemy import text

            from src.backend.infrastructure.database.database import (
                get_external_db_manager,
            )
        except ImportError:
            logger.error("CDC LogMiner: SQLAlchemy unavailable")
            return

        try:
            db = get_external_db_manager(sub.profile)
        except (ValueError, KeyError, AttributeError) as exc:
            logger.error("CDC LogMiner: profile '%s' not found: %s", sub.profile, exc)
            return

        engine = db.get_async_engine()
        table_list = ", ".join(f"'{t.upper()}'" for t in sub.tables)

        while sub.active:
            last_scn = self._last_scn.get(sub.profile, 0)

            try:
                async with engine.connect() as conn:
                    query = text(f"""
                        SELECT SCN, OPERATION, TABLE_NAME, SQL_REDO, TIMESTAMP
                        FROM V$LOGMNR_CONTENTS
                        WHERE SCN > :last_scn
                          AND TABLE_NAME IN ({table_list})
                          AND OPERATION IN ('INSERT', 'UPDATE', 'DELETE')
                        ORDER BY SCN
                        FETCH FIRST :limit ROWS ONLY
                    """)  # table_list собран из sub.tables (DSL config), upper-cased  # noqa: S608  # internal query with controlled parameters
                    result = await conn.execute(
                        query, {"last_scn": last_scn, "limit": sub.batch_size}
                    )
                    rows = result.fetchall()

                for row in rows:
                    scn = row[0]
                    operation = row[1]
                    table_name = row[2]
                    sql_redo = row[3]
                    ts = row[4]

                    event = CDCEvent(
                        operation=operation,
                        table=table_name,
                        timestamp=(
                            ts.isoformat()
                            if isinstance(ts, datetime)
                            else datetime.now(UTC).isoformat()
                        ),
                        profile=sub.profile,
                        new={"_sql_redo": sql_redo, "_scn": scn},
                    )
                    await dispatch(sub, event)

                    if scn > last_scn:
                        last_scn = scn

                self._last_scn[sub.profile] = last_scn

            except Exception as exc:
                logger.warning("CDC LogMiner error [%s]: %s", sub.profile, exc)

            await asyncio.sleep(sub.interval)
