# ruff: noqa: S608 — SQL собирается f-string, но все идентификаторы
# (table / timestamp_column / primary_key) проходят allowlist-валидацию
# (см. ``_identifiers.py``, ADR-0112); значения передаются
# bind-параметрами (``:last_ts``, ``:last_pk``, ``:limit``).

"""S60 W2 — strategies.py part of cdc decomp.

Classes: _CDCStrategy, _PollingStrategy, _ListenNotifyStrategy, _LogMinerStrategy.

4 strategies: base _CDCStrategy + 3 concrete (Polling/ListenNotify/LogMiner).

ADR-0384 (волна 16, кластер X5):

* polling — составной курсор ``(timestamp, PK)``: строки с одинаковым
  timestamp не теряются на границе батча;
* polling — naive/aware timestamp нормализуется в UTC-aware до сравнения
  (PG ``timestamp without time zone`` больше не ломает polling);
* диалектные ограничения выборки (``LIMIT`` / ``FETCH FIRST`` / ``TOP``);
* LogMiner — только Oracle + явный вызов ``DBMS_LOGMNR.START_LOGMNR``.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.infrastructure.clients.external.cdc._cursor import (
    PollCursor,
    SeenKeys,
    decode_cursor,
    encode_cursor,
    ensure_utc,
    row_fingerprint,
    to_db_timestamp,
)
from src.backend.infrastructure.clients.external.cdc._identifiers import (
    escape_sql_literal,
    validate_identifier,
    validate_subscription_identifiers,
)
from src.backend.infrastructure.clients.external.cdc.events import (
    CDCEvent,  # S60 W2: cross-import
    CDCSubscription,  # S60 W2: cross-import
)
from src.backend.infrastructure.database.database.initializer import DatabaseInitializer
from src.backend.infrastructure.database.database.registry import (
    ExternalDatabaseRegistry,
)

logger = get_logger("infrastructure.clients.cdc")

#: Диалекты без ``LIMIT`` (нужен ``FETCH FIRST`` / ``TOP``).
_FETCH_FIRST_DIALECTS = frozenset({"oracle", "db2"})

#: PL/SQL-блоки LogMiner: без ``START_LOGMNR`` view ``V$LOGMNR_CONTENTS``
#: недоступна (ADR-0384).
_START_LOGMNR_SQL = (
    "BEGIN DBMS_LOGMNR.START_LOGMNR(DBMS_LOGMNR.V$LOGMNR_CONTENTS, NULL); END;"
)
_END_LOGMNR_SQL = "BEGIN DBMS_LOGMNR.END_LOGMNR; END;"


def resolve_dialect(profile: str, engine: Any = None) -> str | None:
    """Определить диалект внешней БД (для генерации LIMIT-семантики).

    Args:
        profile: Имя профиля внешней БД.
        engine: Async engine (если доступен) — его ``dialect.name`` —
            самый надёжный источник.

    Returns:
        Имя диалекта (``postgresql`` / ``oracle`` / ``mssql`` / ...) либо
        ``None``, если диалект определить не удалось (неизвестный профиль
        без ``dialect.name`` у engine).

    """
    name = getattr(getattr(engine, "dialect", None), "name", None)
    if isinstance(name, str) and name:
        return name.lower()
    try:
        from src.backend.core.config.external_databases.registry import (
            external_databases_settings,
        )
    except Exception as exc:
        logger.debug("CDC: external DB settings unavailable: %s", exc)
        return None
    try:
        return str(external_databases_settings.get_profile(profile).type)
    except Exception as exc:
        logger.debug(
            "CDC: resolved profile '%s' unavailable (%s) — fallback to connections",
            profile,
            exc,
        )
    # Fallback: тип профиля из списка connections (не требует кредов —
    # degraded-профиль без username/password тоже имеет тип СУБД).
    try:
        for connection in external_databases_settings.connections:
            if connection.profile_name == profile:
                return str(connection.type)
    except Exception as exc:
        logger.debug("CDC: dialect for profile '%s' unresolved: %s", profile, exc)
    return None


def limit_clause(dialect: str | None, placeholder: str = ":limit") -> tuple[str, str]:
    """Ограничение выборки под диалект.

    Args:
        dialect: Имя диалекта (см. :func:`resolve_dialect`).
        placeholder: Плейсхолдер ограничения выборки (``:limit`` для
            SQLAlchemy ``text()``, ``%s`` — для позиционных executor'ов).

    Returns:
        Пара ``(prefix, suffix)``: ``prefix`` вставляется сразу после
        ``SELECT`` (``TOP (...)`` для MSSQL), ``suffix`` — в конец
        запроса (``LIMIT ...`` / ``FETCH FIRST ... ROWS ONLY``).
        Для неизвестного диалекта — совместимое с PostgreSQL ``LIMIT``.

    """
    if dialect == "mssql":
        return f"TOP ({placeholder})", ""
    if dialect in _FETCH_FIRST_DIALECTS:
        return "", f"FETCH FIRST {placeholder} ROWS ONLY"
    return "", f"LIMIT {placeholder}"


def detect_primary_key(row: dict[str, Any], table: str) -> str | None:
    """Определить PK-колонку по первой выборке.

    Порядок кандидатов детерминирован: ``id`` → ``<table>_id`` → любая
    колонка с суффиксом ``_id`` (по алфавиту). Имена проверяются
    allowlist-ом — иначе колонка не используется в SQL.

    Args:
        row: Первая строка выборки.
        table: Имя таблицы (может содержать схему).

    Returns:
        Имя PK-колонки либо ``None``.

    """
    short_table = table.split(".")[-1].lower()
    candidates = ["id", f"{short_table}_id"]
    candidates.extend(sorted(k for k in row if k.endswith("_id")))
    for candidate in candidates:
        if candidate not in row:
            continue
        try:
            validate_identifier(candidate, context="cdc.primary_key")
        except ValueError:
            continue
        return candidate
    return None


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

    Граница батча (ADR-0384): курсор — составной ``(timestamp, PK)``,
    условие выборки ``ts >= :last_ts AND (ts > :last_ts OR pk > :last_pk)``,
    порядок ``ORDER BY ts, pk``. Строки с одинаковым timestamp не теряются
    на границе батча. Если PK не задан — он определяется по первой выборке;
    если определить не удалось, используется ts-only режим с ``>=`` и
    дедупликацией по отпечатку строки (см. ADR-0384).

    Multi-instance safety (MI-4):
    - Cursor _last_check хранится в Redis через RedisCursor (CAS)
    - Несколько инстансов могут безопасно подписываться на одну таблицу
    - Дублирование событий предотвращается atomic try_advance()
    """

    def __init__(self) -> None:
        self._last_check_local: dict[str, PollCursor] = {}
        self._pk_columns: dict[str, str] = {}
        self._seen: dict[str, SeenKeys] = {}
        self._pk_warned: set[str] = set()

    async def _get_cursor(self, key: str, default: PollCursor) -> PollCursor:
        """Загрузить cursor из Redis (или вернуть default при недоступности)."""
        try:
            from src.backend.infrastructure.clients.storage.redis_coordinator import (
                RedisCursor,
            )

            cursor = RedisCursor(f"cdc:cursor:{key}")
            stored = await cursor.get_or_init(encode_cursor(default.ts, default.pk))
            return decode_cursor(stored)
        except Exception:
            return self._last_check_local.get(key, default)

    async def _advance_cursor(self, key: str, new_value: PollCursor) -> None:
        """Atomic advance cursor через Redis CAS."""
        try:
            from src.backend.infrastructure.clients.storage.redis_coordinator import (
                RedisCursor,
            )

            cursor = RedisCursor(f"cdc:cursor:{key}")
            await cursor.try_advance(encode_cursor(new_value.ts, new_value.pk))
        except Exception:
            logger.debug("CDC cursor advance via Redis failed", exc_info=True)
        self._last_check_local[key] = new_value

    def _build_sql(
        self,
        sub: CDCSubscription,
        table: str,
        pk_column: str | None,
        limit_prefix: str,
        limit_suffix: str,
        *,
        use_pk_filter: bool,
    ) -> str:
        """Собрать SELECT polling-запрос.

        Args:
            sub: Подписка CDC.
            table: Имя таблицы (уже провалидировано allowlist-ом).
            pk_column: PK-колонка (если известна).
            limit_prefix: Префикс ограничения выборки (``TOP (:limit)``).
            limit_suffix: Суффикс ограничения выборки (``LIMIT :limit``).
            use_pk_filter: Использовать составной курсор ``(ts, PK)``.

        Returns:
            Текст SQL-запроса.

        """
        ts_column = sub.timestamp_column
        select = (
            f"SELECT {limit_prefix} * FROM {table}"
            if limit_prefix
            else f"SELECT * FROM {table}"
        )
        order = f"ORDER BY {ts_column} ASC"
        if pk_column:
            order += f", {pk_column} ASC"
        if use_pk_filter and pk_column:
            where = (
                f"WHERE {ts_column} >= :last_ts "
                f"AND ({ts_column} > :last_ts OR {pk_column} > :last_pk)"
            )
        else:
            where = f"WHERE {ts_column} >= :last_ts"
        parts = [select, where, order]
        if limit_suffix:
            parts.append(limit_suffix)
        return " ".join(parts)

    async def _fetch_rows(
        self,
        conn: Any,
        sub: CDCSubscription,
        table: str,
        cursor: PollCursor,
        key: str,
        limit_prefix: str,
        limit_suffix: str,
    ) -> list[dict[str, Any]]:
        """Выполнить SELECT и вернуть строки батча.

        Если PK неизвестен — определяется по первой выборке, после чего
        запрос повторяется с детерминированным порядком ``(ts, PK)``
        (иначе строки с одинаковым timestamp могли бы потеряться).
        """
        from sqlalchemy import text

        pk_column = self._pk_columns.get(key)
        use_pk_filter = pk_column is not None and cursor.pk is not None
        sql = self._build_sql(
            sub,
            table,
            pk_column,
            limit_prefix,
            limit_suffix,
            use_pk_filter=use_pk_filter,
        )
        params: dict[str, Any] = {
            "last_ts": to_db_timestamp(cursor.ts),
            "limit": sub.batch_size,
        }
        if use_pk_filter and pk_column:
            params["last_pk"] = cursor.pk

        result = await conn.execute(text(sql), params)
        rows = [dict(row._mapping) for row in result.fetchall()]

        if rows and pk_column is None:
            detected = detect_primary_key(rows[0], table)
            if detected:
                self._pk_columns[key] = detected
                logger.info(
                    "CDC polling: primary key detected table=%s pk=%s",
                    table,
                    detected,
                )
                if len(rows) >= sub.batch_size:
                    # Батч заполнен — могли остаться строки с тем же ts.
                    # Перечитываем с детерминированным порядком (ts, PK).
                    sql = self._build_sql(
                        sub,
                        table,
                        detected,
                        limit_prefix,
                        limit_suffix,
                        use_pk_filter=False,
                    )
                    result = await conn.execute(text(sql), params)
                    rows = [dict(row._mapping) for row in result.fetchall()]
        return rows

    async def run(
        self,
        sub: CDCSubscription,
        dispatch: Callable[[CDCSubscription, CDCEvent], Awaitable[None]],
    ) -> None:
        """Polling-based CDC: периодически опрашивает таблицы на новые строки.

        Использует watermark-курсор (Redis CAS, fallback in-memory) по
        timestamp-колонке. На каждой итерации делает SELECT новых строк
        batch'ом и диспатчит их как :class:`CDCEvent`.

        Args:
            sub: Подписка CDC (profile, tables, timestamp_column, batch_size).
            dispatch: Callback для отправки каждого CDC-события.

        Raises:
            ValueError: Если имена таблиц/колонок не проходят allowlist.

        """
        # S-17: fail-fast валидация идентификаторов до обращения к БД —
        # недоверенное имя не должно доходить до SQL (f-string).
        validate_subscription_identifiers(sub)

        try:
            from sqlalchemy import text  # noqa: F401

            from src.backend.infrastructure.database.database.accessors import (
                get_external_db_registry,
            )
        except ImportError:
            logger.error("CDC polling: SQLAlchemy or external DB manager unavailable")
            return

        try:
            registry: ExternalDatabaseRegistry = get_external_db_registry()
            initializer: DatabaseInitializer = registry.get_initializer(sub.profile)
        except (ValueError, KeyError, AttributeError) as exc:
            logger.error("CDC polling: profile '%s' not found: %s", sub.profile, exc)
            return

        engine = initializer.get_async_engine()
        dialect = resolve_dialect(sub.profile, engine)
        limit_prefix, limit_suffix = limit_clause(dialect)

        while sub.active:
            for table in sub.tables:
                key = f"{sub.profile}:{table}"
                cursor = await self._get_cursor(key, PollCursor(ts=datetime.now(UTC)))

                try:
                    async with engine.connect() as conn:
                        rows = await self._fetch_rows(
                            conn,
                            sub,
                            table,
                            cursor,
                            key,
                            limit_prefix,
                            limit_suffix,
                        )
                        pk_column = self._pk_columns.get(key)
                        seen = self._seen.setdefault(key, SeenKeys())
                        new_cursor = cursor

                        for row in rows:
                            ts_raw = row.get(sub.timestamp_column)
                            ts = ensure_utc(ts_raw) if isinstance(ts_raw, datetime) else None
                            pk_value = row.get(pk_column) if pk_column else None
                            if ts is not None:
                                new_cursor = PollCursor(
                                    ts=ts, pk=pk_value if pk_column else None
                                )
                            if pk_column:
                                dedup_key = f"pk:{pk_value!r}"
                            else:
                                dedup_key = f"row:{row_fingerprint(row)}"
                            if not seen.add(dedup_key):
                                continue
                            event = CDCEvent(
                                operation="UPSERT",
                                table=table,
                                timestamp=ts.isoformat() if ts else None,
                                profile=sub.profile,
                                new=row,
                            )
                            await dispatch(sub, event)

                        if rows:
                            await self._advance_cursor(key, new_cursor)
                        elif pk_column is None and key not in self._pk_warned:
                            # Один warning на таблицу (иначе — спам на каждом пустом poll'е).
                            self._pk_warned.add(key)
                            logger.warning(
                                "CDC polling: primary key not detected for table=%s "
                                "(profile=%s) — задайте primary_key, иначе строки "
                                "с одинаковым timestamp сверх batch_size могут "
                                "быть пропущены",
                                table,
                                sub.profile,
                            )

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
        """PostgreSQL LISTEN/NOTIFY CDC — low-latency через pg_notify.

        Подключается к PostgreSQL через asyncpg, слушает канал ``cdc_<table>``
        (или кастомный). Уведомления складываются в bounded queue, затем
        парсятся и диспатчатся как :class:`CDCEvent`.

        Args:
            sub: Подписка CDC (profile, tables, channel).
            dispatch: Callback для отправки каждого CDC-события.

        Note:
            Требует триггер на таблице, вызывающий ``pg_notify()`` с JSON payload.

        """
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
                        # Исходный timestamp сохраняется как есть (ADR-0384).
                        timestamp=data.get("timestamp"),
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

    ADR-0384: стратегия работает **только** с Oracle-профилем (для других
    СУБД — fail-fast с понятным сообщением), а перед чтением view
    вызывается ``DBMS_LOGMNR.START_LOGMNR`` (без него
    ``V$LOGMNR_CONTENTS`` недоступна).
    """

    def __init__(self) -> None:
        self._last_scn: dict[str, int] = {}

    async def run(
        self,
        sub: CDCSubscription,
        dispatch: Callable[[CDCSubscription, CDCEvent], Awaitable[None]],
    ) -> None:
        """Oracle LogMiner CDC — чтение ``V$LOGMNR_CONTENTS``.

        Поллирует LogMiner view по SCN (system change number), фильтрует
        по таблицам подписки и операциям (INSERT/UPDATE/DELETE).
        Производит базовый парсинг ``SQL_REDO`` для определения операции.

        Args:
            sub: Подписка CDC (profile, tables, batch_size).
            dispatch: Callback для отправки каждого CDC-события.

        Raises:
            ValueError: Если имена таблиц не проходят allowlist либо
                профиль не является Oracle.

        """
        # S-17: fail-fast валидация идентификаторов до обращения к БД —
        # имена таблиц подставляются в строковые литералы SQL.
        validate_subscription_identifiers(sub)

        try:
            from sqlalchemy import text

            from src.backend.infrastructure.database.database.accessors import (
                get_external_db_registry,
            )
        except ImportError:
            logger.error("CDC LogMiner: SQLAlchemy unavailable")
            return

        try:
            registry: ExternalDatabaseRegistry = get_external_db_registry()
            initializer: DatabaseInitializer = registry.get_initializer(sub.profile)
        except (ValueError, KeyError, AttributeError) as exc:
            logger.error("CDC LogMiner: profile '%s' not found: %s", sub.profile, exc)
            return

        engine = initializer.get_async_engine()
        dialect = resolve_dialect(sub.profile, engine)
        if dialect is not None and dialect != "oracle":
            raise ValueError(
                "CDC logminer strategy requires an Oracle profile; "
                f"profile '{sub.profile}' resolves to dialect '{dialect}'. "
                "Use strategy='polling' or 'kafka' for other databases."
            )

        # S-17: имена таблиц провалидированы allowlist-ом; escape — второй слой.
        table_list = ", ".join(f"'{escape_sql_literal(t.upper())}'" for t in sub.tables)

        while sub.active:
            last_scn = self._last_scn.get(sub.profile, 0)

            try:
                async with engine.connect() as conn:
                    # ADR-0384: без START_LOGMNR view V$LOGMNR_CONTENTS
                    # недоступна (ORA-00942) — вызываем явно.
                    await conn.execute(text(_START_LOGMNR_SQL))
                    try:
                        query = text(f"""
                            SELECT SCN, OPERATION, TABLE_NAME, SQL_REDO, TIMESTAMP
                            FROM V$LOGMNR_CONTENTS
                            WHERE SCN > :last_scn
                              AND TABLE_NAME IN ({table_list})
                              AND OPERATION IN ('INSERT', 'UPDATE', 'DELETE')
                            ORDER BY SCN
                            FETCH FIRST :limit ROWS ONLY
                        """)  # table_list — валидированные (allowlist) имена таблиц, upper-cased
                        result = await conn.execute(
                            query, {"last_scn": last_scn, "limit": sub.batch_size}
                        )
                        rows = result.fetchall()
                    finally:
                        await conn.execute(text(_END_LOGMNR_SQL))

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
                            ensure_utc(ts).isoformat()
                            if isinstance(ts, datetime)
                            else None
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
