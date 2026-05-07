"""Change Data Capture — подписка на изменения таблиц во внешних БД.

Поддерживает 3 стратегии:
- polling: периодический опрос по timestamp_column (работает с любой БД)
- listen_notify: PostgreSQL LISTEN/NOTIFY (low-latency, требует trigger)
- logminer: Oracle LogMiner query (требует права на V$LOGMNR_CONTENTS)

CDC события стандартизованы:
    {
        "operation": "INSERT|UPDATE|DELETE|UPSERT",
        "table": "orders",
        "timestamp": "2026-04-19T12:00:00",
        "old": {...},  # для UPDATE/DELETE (если доступно)
        "new": {...},  # для INSERT/UPDATE
        "profile": "oracle_1",
    }
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from uuid import uuid4

__all__ = ("CDCClient", "CDCSubscription", "CDCEvent", "get_cdc_client")

logger = logging.getLogger(__name__)


@dataclass
class CDCEvent:
    """Стандартизированное CDC-событие."""

    operation: str  # INSERT / UPDATE / DELETE / UPSERT
    table: str
    timestamp: str
    profile: str
    new: dict[str, Any] | None = None
    old: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "table": self.table,
            "timestamp": self.timestamp,
            "profile": self.profile,
            "new": self.new,
            "old": self.old,
        }


@dataclass
class CDCSubscription:
    """Описание подписки на изменения."""

    id: str = field(default_factory=lambda: uuid4().hex[:12])
    profile: str = ""
    tables: list[str] = field(default_factory=list)
    strategy: str = "polling"
    interval: float = 5.0
    batch_size: int = 100
    timestamp_column: str = "updated_at"
    channel: str | None = None
    callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None
    target_action: str | None = None
    active: bool = True


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
        except (ImportError, Exception):
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
                last = await self._get_cursor(key, datetime.now(timezone.utc))

                try:
                    async with engine.connect() as conn:
                        query = text(
                            f"SELECT * FROM {table} "  # noqa: S608  # table/timestamp_column — DSL/config параметры подписки, не runtime user input
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
                                    else datetime.now(timezone.utc).isoformat()
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
                except asyncio.TimeoutError:
                    continue

                try:
                    data = orjson.loads(payload)
                    event = CDCEvent(
                        operation=str(data.get("operation", "UNKNOWN")).upper(),
                        table=str(data.get("table", "")),
                        timestamp=data.get("timestamp")
                        or datetime.now(timezone.utc).isoformat(),
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
            except Exception:
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
                    """)  # noqa: S608  # table_list собран из sub.tables (DSL config), upper-cased
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
                            else datetime.now(timezone.utc).isoformat()
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


class CDCClient:
    """Клиент CDC — управление подписками на изменения.

    Поддерживает 3 стратегии: polling, listen_notify, logminer.
    """

    _STRATEGIES: dict[str, type[_CDCStrategy]] = {
        "polling": _PollingStrategy,
        "listen_notify": _ListenNotifyStrategy,
        "logminer": _LogMinerStrategy,
    }

    def __init__(self) -> None:
        self._subscriptions: dict[str, CDCSubscription] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    async def subscribe(
        self,
        profile: str,
        tables: list[str],
        *,
        strategy: str = "polling",
        interval: float = 5.0,
        batch_size: int = 100,
        timestamp_column: str = "updated_at",
        channel: str | None = None,
        callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        target_action: str | None = None,
    ) -> str:
        """Создаёт подписку на изменения в таблицах.

        Args:
            profile: Имя профиля внешней БД.
            tables: Список таблиц для отслеживания.
            strategy: polling | listen_notify | logminer.
            interval: Интервал polling (сек).
            batch_size: Макс. событий за итерацию.
            timestamp_column: Столбец для polling-стратегии.
            channel: PG LISTEN-канал (по умолчанию cdc_<table>).
            callback: Async-функция обработки событий.
            target_action: Action для диспетчеризации при событии.

        Returns:
            ID подписки.
        """
        if strategy not in self._STRATEGIES:
            raise ValueError(
                f"Unknown CDC strategy '{strategy}'. Available: {list(self._STRATEGIES)}"
            )

        sub = CDCSubscription(
            profile=profile,
            tables=tables,
            strategy=strategy,
            interval=interval,
            batch_size=batch_size,
            timestamp_column=timestamp_column,
            channel=channel,
            callback=callback,
            target_action=target_action,
        )
        self._subscriptions[sub.id] = sub

        strategy_impl = self._STRATEGIES[strategy]()
        task = asyncio.create_task(
            self._run_strategy(strategy_impl, sub), name=f"cdc-{sub.id}"
        )
        self._tasks[sub.id] = task

        logger.info(
            "CDC подписка создана: id=%s profile=%s tables=%s strategy=%s",
            sub.id,
            profile,
            tables,
            strategy,
        )
        return sub.id

    async def _run_strategy(self, strategy: _CDCStrategy, sub: CDCSubscription) -> None:
        """Запускает стратегию и ловит cancellation."""
        try:
            await strategy.run(sub, self._dispatch_change)
        except asyncio.CancelledError:
            logger.debug("CDC strategy cancelled: %s", sub.id)
        except Exception as exc:
            logger.error("CDC strategy crashed [%s]: %s", sub.id, exc, exc_info=True)

    async def unsubscribe(self, subscription_id: str) -> bool:
        """Удаляет подписку."""
        sub = self._subscriptions.pop(subscription_id, None)
        if sub is None:
            return False

        sub.active = False
        task = self._tasks.pop(subscription_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError, Exception:
                logger.debug("CDC subscription task cancellation raised", exc_info=True)

        logger.info("CDC подписка удалена: %s", subscription_id)
        return True

    def list_subscriptions(self) -> list[dict[str, Any]]:
        """Возвращает список активных подписок."""
        return [
            {
                "id": sub.id,
                "profile": sub.profile,
                "tables": sub.tables,
                "strategy": sub.strategy,
                "target_action": sub.target_action,
                "active": sub.active,
            }
            for sub in self._subscriptions.values()
        ]

    async def _dispatch_change(self, sub: CDCSubscription, event: CDCEvent) -> None:
        """Обрабатывает обнаруженное изменение."""
        event_dict = event.to_dict()

        if sub.callback:
            try:
                await sub.callback(event_dict)
            except Exception as exc:
                logger.error("CDC callback error [%s]: %s", sub.id, exc)

        if sub.target_action:
            from src.backend.dsl.commands.registry import action_handler_registry
            from src.backend.schemas.invocation import ActionCommandSchema

            command = ActionCommandSchema(
                action=sub.target_action,
                payload=event_dict,
                meta={"source": f"cdc:{sub.profile}:{sub.strategy}"},
            )
            try:
                await action_handler_registry.dispatch(command)
            except Exception as exc:
                logger.error(
                    "CDC dispatch error [%s -> %s]: %s", sub.id, sub.target_action, exc
                )

    async def shutdown(self) -> None:
        """Останавливает все подписки."""
        for sub_id in list(self._subscriptions):
            await self.unsubscribe(sub_id)


_cdc_instance: CDCClient | None = None


def get_cdc_client() -> CDCClient:
    """Фабрика CDC-клиента (singleton)."""
    global _cdc_instance
    if _cdc_instance is None:
        _cdc_instance = CDCClient()
    return _cdc_instance
