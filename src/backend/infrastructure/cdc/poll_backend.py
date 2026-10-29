# ruff: noqa: S608 — SQL собирается f-string, но все идентификаторы
# (table / timestamp_column / primary_key) проходят allowlist-валидацию
# (см. ``clients/external/cdc/_identifiers.py``, ADR-0112/ADR-0384);
# значения передаются bind-параметрами (``%s``).

"""R2.1 + S93 W4 — `PollCDCBackend`: universal polling-based CDC.

Реализация ``CDCSource`` Protocol поверх существующего
``infrastructure.clients.external.cdc._PollingStrategy``. Опционально
принимает ``feed`` (in-memory ``AsyncIterator[dict]``) для test/dev
режима, чтобы CDC-события можно было инжектировать без БД.

Production path: ``ListenNotifyCDCBackend`` (PG) или
``DebeziumEventsCDCBackend`` (multi-DB через Debezium).

Ограничения:
* Не различает INSERT/UPDATE → ``UPSERT``.
* Не обнаруживает DELETE.
* Подходит для любой БД с поддержкой timestamp-колонок.

ADR-0384 (волна 16, кластер X5):

* курсор — составной ``(timestamp, PK)``: строки с одинаковым timestamp
  не теряются на границе батча;
* без ``sql_executor`` backend **честно выключен** (лог-ошибка + health
  ``not_implemented``) — вместо молчаливого scaffold-цикла;
* ограничение выборки учитывает диалект (``LIMIT`` / ``FETCH FIRST`` /
  ``TOP``).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable, Literal

from src.backend.core.cdc.source import CDCCursor, CDCEvent, CDCSource
from src.backend.core.logging import get_logger
from src.backend.core.utils.datetime_utils import ensure_utc
from src.backend.infrastructure.clients.external.cdc._cursor import (
    PollCursor,
    SeenKeys,
    decode_cursor,
    encode_cursor,
    row_fingerprint,
)
from src.backend.infrastructure.clients.external.cdc._identifiers import (
    validate_identifier,
)
from src.backend.infrastructure.clients.external.cdc.strategies import (
    detect_primary_key,
    limit_clause,
    resolve_dialect,
)

__all__ = ("PollCDCBackend",)


_logger = get_logger("cdc.poll_backend")


def _parse_timestamp(value: Any) -> datetime | None:
    """Привести значение timestamp-колонки к UTC-aware datetime.

    Args:
        value: Значение из строки выборки (datetime / ISO-строка / None).

    Returns:
        UTC-aware datetime либо ``None`` (значение не распознано).

    """
    if isinstance(value, datetime):
        return ensure_utc(value)
    if isinstance(value, str) and value:
        try:
            return ensure_utc(datetime.fromisoformat(value))
        except ValueError:
            return None
    return None


def _to_named_params(sql: str, params: list[Any]) -> tuple[str, dict[str, Any]]:
    """Перевести позиционные ``%s``-плейсхолдеры в именованные ``:pN``.

    Нужно для внутреннего executor'а на SQLAlchemy (``text()`` не понимает
    позиционные параметры).

    Args:
        sql: SQL с позиционными плейсхолдерами.
        params: Значения плейсхолдеров (в порядке следования).

    Returns:
        Пара ``(sql, params_dict)``.

    """
    names = [f"p{index}" for index in range(len(params))]
    for name in names:
        sql = sql.replace("%s", f":{name}", 1)
    return sql, dict(zip(names, params, strict=True))


class PollCDCBackend(CDCSource):
    """Polling-based CDC backend для произвольной БД (или test feed).

    Этот backend работает в двух режимах:

    * **Feed mode** (test/dev): ``feed=async_iter_of_dicts`` — события
      читаются из in-memory генератора, полезно для unit-тестов и
      локальной разработки без поднятия Postgres/Kafka/Debezium.
    * **Polling mode**: требует ``sql_executor`` — backend выполняет
      polling-loop с составным курсором ``(timestamp, PK)``. Без
      executor'а режим **не реализован** (ADR-0384): backend пишет
      явную ошибку в лог и завершает подписку, а ``health_check``
      сообщает статус ``not_implemented``.
    """

    def __init__(
        self,
        *,
        profile: str,
        interval_s: float = 5.0,
        timestamp_column: str = "updated_at",
        batch_size: int = 100,
        feed: AsyncIterator[dict[str, Any]] | None = None,
        sql_executor: Callable[
            [str, list[Any]], Awaitable[list[dict[str, Any]]] | None
        ] = None,  # type: ignore[assignment]
        table: str | None = None,
        primary_key: str | None = None,
        dialect: str | None = None,
    ) -> None:
        """Параметры:

        :param profile: имя профиля БД (для resolve через DatabaseGateway).
        :param interval_s: пауза между poll-запросами в секундах.
        :param timestamp_column: имя колонки для cursor-сравнения.
        :param batch_size: максимальное число записей за один poll.
        :param feed: опциональный async iter dict'ов для test/dev mode
            (in-memory event injection без БД).
        :param sql_executor: Sprint 12 P1-4 — optional callable для polling
            mode. Принимает ``(sql: str, params: list)`` и возвращает list of
            dicts (rows). Если None — polling mode не реализован (ADR-0384).
        :param table: имя таблицы для polling. Если None — используется
            ``tables[0]`` из ``subscribe()`` call.
        :param primary_key: PK-колонка для составного курсора. ``None`` —
            определить по первой выборке.
        :param dialect: диалект БД для генерации LIMIT-семантики. ``None`` —
            определить по профилю.
        """
        self._profile = profile
        self._interval_s = interval_s
        self._timestamp_column = timestamp_column
        self._batch_size = batch_size
        self._feed = feed
        self._sql_executor = sql_executor
        self._default_table = table
        self._primary_key = primary_key
        self._dialect = dialect
        self._stopped = asyncio.Event()
        self._cursor_log: list[CDCCursor] = []
        self._engine: Any = None

    def _ensure_engine(self) -> Any:
        """Получить async engine внешней БД по профилю.

        Используется, когда ``sql_executor`` не передан (registry-путь
        ``get_cdc_source("poll", profile=...)``) — иначе backend был бы
        неработоспособным, а ``is_backend_available("poll")`` врал бы.

        Returns:
            Async engine внешней БД.

        Raises:
            ValueError: Если профиль не найден в реестре внешних БД.

        """
        if self._engine is not None:
            return self._engine
        from src.backend.infrastructure.database.database.accessors import (
            get_external_db_registry,
        )

        registry = get_external_db_registry()
        initializer = registry.get_initializer(self._profile)
        self._engine = initializer.get_async_engine()
        return self._engine

    async def _engine_executor(
        self, sql: str, params: list[Any]
    ) -> list[dict[str, Any]]:
        """Executor по умолчанию — SQLAlchemy engine внешней БД.

        Args:
            sql: SQL с позиционными ``%s``-плейсхолдерами.
            params: Значения плейсхолдеров.

        Returns:
            Список строк выборки (dict'ы).

        """
        from sqlalchemy import text

        named_sql, named_params = _to_named_params(sql, params)
        engine = self._ensure_engine()
        async with engine.connect() as conn:
            result = await conn.execute(text(named_sql), named_params)
            return [dict(row._mapping) for row in result.fetchall()]

    async def subscribe(  # type: ignore[override]  # R2.MYPY: CDCSource AsyncIterator vs Coroutine[AsyncIterator]
        self, *, tables: list[str], start_cursor: CDCCursor | None = None
    ) -> AsyncIterator[CDCEvent]:
        """Polling-loop или feed consumption (зависит от режима).

        Feed mode: читает из ``self._feed`` пока не ``stopped`` или
        feed не исчерпан. Каждый dict превращается в ``CDCEvent`` с
        ``operation=UPSERT``.

        Polling mode: SELECT новых строк по составному курсору
        ``(timestamp, PK)`` — строки с одинаковым timestamp не теряются
        на границе батча (ADR-0384).

        Raises:
            ValueError: Если имя таблицы или timestamp-колонки не проходит
                allowlist-валидацию SQL-идентификатора.
        """
        target_table = self._default_table or (tables[0] if tables else "_unknown")
        validate_identifier(target_table, context="cdc.poll_backend.table")
        validate_identifier(
            self._timestamp_column, context="cdc.poll_backend.timestamp_column"
        )
        for index, table in enumerate(tables):
            validate_identifier(table, context=f"cdc.poll_backend.tables[{index}]")
        if self._primary_key:
            validate_identifier(
                self._primary_key, context="cdc.poll_backend.primary_key"
            )

        _logger.info(
            "PollCDCBackend started: profile=%s tables=%s interval_s=%.1f mode=%s",
            self._profile,
            tables,
            self._interval_s,
            "feed" if self._feed is not None else "polling",
        )
        cursor: PollCursor = (
            self._decode_cursor(start_cursor.value)
            if start_cursor is not None
            else PollCursor(ts=datetime.now(UTC))
        )

        if self._feed is not None:
            # Feed mode: consume in-memory events.
            async for raw in self._feed:
                if self._stopped.is_set():
                    return
                if not isinstance(raw, dict):
                    _logger.warning("PollCDCBackend feed: skip non-dict entry: %r", raw)
                    continue
                cursor_value = str(raw.get("timestamp") or raw.get("cursor") or "")
                yield CDCEvent(
                    operation="UPSERT",
                    source=f"poll:{self._profile}",
                    table=str(raw.get("table", tables[0] if tables else "_unknown")),
                    timestamp=datetime.now(UTC),
                    new=raw.get("new"),
                    old=raw.get("old"),
                    cursor=CDCCursor(value=cursor_value or "0", backend="poll"),
                )
            return

        if self._sql_executor is None:
            # ADR-0384: executor по умолчанию — engine внешней БД по профилю
            # (registry-путь). Если профиль не резолвится — режим честно
            # выключен (ошибка в лог, health → not_implemented).
            try:
                self._ensure_engine()
            except Exception as exc:
                _logger.error(
                    "PollCDCBackend: polling mode is not available for profile=%s "
                    "(%s); use feed= or the external CDC client "
                    "(polling/listen_notify/kafka)",
                    self._profile,
                    exc,
                )
                return
            executor = self._engine_executor
        else:
            executor = self._sql_executor

        pk_column = self._primary_key
        seen = SeenKeys()
        limit_prefix, limit_suffix = limit_clause(
            self._dialect or resolve_dialect(self._profile), placeholder="%s"
        )

        while not self._stopped.is_set():
            sql, params = self._build_sql(
                target_table, cursor, pk_column, limit_prefix, limit_suffix
            )
            try:
                # sql_executor может возвращать None per type signature.
                # Narrow перед await для mypy; preserve семантику (None → []).
                coro = executor(sql, params)
                rows = await coro if coro is not None else []
            except Exception as exc:
                _logger.error(
                    "PollCDCBackend executor failed: %s (table=%s)",
                    exc,
                    target_table,
                )
                await asyncio.sleep(self._interval_s)
                continue

            if rows and pk_column is None:
                detected = detect_primary_key(rows[0], target_table)
                if detected:
                    pk_column = detected
                    _logger.info(
                        "PollCDCBackend: primary key detected table=%s pk=%s",
                        target_table,
                        detected,
                    )
                    if len(rows) >= self._batch_size:
                        # Батч заполнен — могли остаться строки с тем же ts.
                        # Перечитываем с детерминированным порядком (ts, PK).
                        sql, params = self._build_sql(
                            target_table, cursor, pk_column, limit_prefix, limit_suffix
                        )
                        coro = executor(sql, params)
                        rows = (await coro if coro is not None else []) or []

            new_cursor = cursor
            for row in rows:
                if self._stopped.is_set():
                    return
                ts = _parse_timestamp(row.get(self._timestamp_column))
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
                yield CDCEvent(
                    operation="UPSERT",
                    source=f"poll:{self._profile}",
                    table=target_table,
                    timestamp=ts or datetime.now(UTC),
                    new=row,
                    old=None,
                    cursor=CDCCursor(
                        value=encode_cursor(new_cursor.ts, new_cursor.pk),
                        backend="poll",
                    ),
                )
            if rows:
                cursor = new_cursor

            if self._interval_s > 0:
                await asyncio.sleep(self._interval_s)

    def _build_sql(
        self,
        target_table: str,
        cursor: PollCursor,
        pk_column: str | None,
        limit_prefix: str,
        limit_suffix: str,
    ) -> tuple[str, list[Any]]:
        """Собрать SELECT polling-запрос и bind-параметры.

        Args:
            target_table: Имя таблицы (провалидировано allowlist-ом).
            cursor: Текущий составной курсор.
            pk_column: PK-колонка (если известна).
            limit_prefix: Префикс ограничения выборки (``TOP (:limit)``).
            limit_suffix: Суффикс ограничения выборки (``LIMIT ...``).

        Returns:
            Пара ``(sql, params)``.

        """
        ts_column = self._timestamp_column
        select = (
            f"SELECT {limit_prefix} * FROM {target_table}"
            if limit_prefix
            else f"SELECT * FROM {target_table}"
        )
        where_params: list[Any]
        if pk_column and cursor.pk is not None:
            sql = (
                f"{select} "
                f"WHERE {ts_column} >= %s "
                f"AND ({ts_column} > %s OR {pk_column} > %s) "
                f"ORDER BY {ts_column} ASC, {pk_column} ASC"
            )
            where_params = [
                cursor.ts.replace(tzinfo=None),
                cursor.ts.replace(tzinfo=None),
                cursor.pk,
            ]
        else:
            order = f"ORDER BY {ts_column} ASC"
            if pk_column:
                order += f", {pk_column} ASC"
            sql = f"{select} WHERE {ts_column} >= %s {order}"
            where_params = [cursor.ts.replace(tzinfo=None)]
        if limit_suffix:
            sql = f"{sql} {limit_suffix}"
        # Параметры идут в порядке плейсхолдеров: TOP(...) — первым,
        # LIMIT/FETCH FIRST — последним.
        params: list[Any] = []
        if limit_prefix:
            params.append(self._batch_size)
        params.extend(where_params)
        if limit_suffix:
            params.append(self._batch_size)
        return sql, params

    def _decode_cursor(self, value: str) -> PollCursor:
        """Разобрать курсор (в т.ч. legacy-ISO-строку)."""
        try:
            return decode_cursor(value)
        except ValueError:
            return PollCursor(ts=datetime.now(UTC))

    async def ack(self, cursor: CDCCursor) -> None:
        """Записать cursor в журнал (для resume)."""
        self._cursor_log.append(cursor)

    async def replay(  # type: ignore[override]  # R2.MYPY: CDCSource AsyncIterator vs Coroutine[AsyncIterator]
        self, *, start_cursor: CDCCursor, end_cursor: CDCCursor | None = None
    ) -> AsyncIterator[CDCEvent]:
        """Replay для polling backend = re-poll по тому же timestamp.

        Feed mode: повторно consume'ит feed. Polling mode: no-op scaffold.
        """
        _logger.debug(
            "PollCDCBackend.replay: %s..%s (mode=%s)",
            start_cursor.value,
            end_cursor.value if end_cursor else "now",
            "feed" if self._feed is not None else "polling",
        )
        if self._feed is not None:
            # Re-iterate feed (для replay).
            async for raw in self._feed:
                yield CDCEvent(
                    operation="UPSERT",
                    source=f"poll:{self._profile}:replay",
                    table=str(raw.get("table", "_unknown")),
                    timestamp=datetime.now(UTC),
                    new=raw.get("new"),
                    cursor=CDCCursor(
                        value=str(raw.get("cursor", start_cursor.value)), backend="poll"
                    ),
                )
        return
        yield  # pragma: no cover

    async def close(self) -> None:
        """Остановить polling-loop или feed consumption."""
        self._stopped.set()

    async def health_check(
        self, *, mode: Literal["fast", "deep"] = "fast"
    ) -> dict[str, Any]:
        """Health probe для HealthAggregator (Sprint 170 M2 Phase 1).

        Returns:
            Статус backend'а. ``not_implemented`` — если polling-режим
            не сконфигурирован (``sql_executor`` не передан, ADR-0384).

        """
        try:
            import time

            start = time.monotonic()
            if self._sql_executor is None and self._feed is None:
                try:
                    # Registry-путь: engine внешней БД по профилю.
                    self._ensure_engine()
                except Exception as exc:
                    return {
                        "status": "not_implemented",
                        "latency_ms": 0.0,
                        "error": (
                            "polling mode requires sql_executor or a resolvable "
                            f"external DB profile ({exc})"
                        ),
                    }
            # Real probe: check is_running / is_open properties
            running = getattr(self, "_running", None)
            if running is False:
                return {"status": "down", "latency_ms": 0.0, "error": "not running"}
            # Try connect/ping if available
            connect = getattr(self, "connect", None)
            if connect is None:
                return {"status": "ok", "latency_ms": 0.0, "error": None}
            await connect()
            return {
                "status": "ok",
                "latency_ms": round((time.monotonic() - start) * 1000, 2),
                "error": None,
            }
        except Exception as exc:
            return {"status": "down", "error": str(exc)}
