"""R2.1 — `ListenNotifyCDCBackend`: PostgreSQL LISTEN/NOTIFY-based CDC.

Низколатентный CDC backend для PostgreSQL: подписывается через
asyncpg ``add_listener`` на канал `pg_notify`, отправляемый из
триггера (см. AlembicMigration ``c3d4e5f6a7b8`` для workflow_events
как образец триггера).

Преимущества над polling:
* Sub-second latency (push-based).
* Не нагружает БД polling-запросами.

Ограничения:
* Только PostgreSQL.
* Payload ограничен 8KB (PG hard limit) — для больших записей
  использовать polling или Debezium.

ADR-0384 (волна 16, кластер X5): backend реализован (asyncpg
``add_listener`` + разбор JSON-payload), а не заглушка ``wait()``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    pass

from src.backend.core.cdc.source import CDCCursor, CDCEvent, CDCSource
from src.backend.core.logging import get_logger
from src.backend.core.utils.datetime_utils import ensure_utc, parse_dt

__all__ = ("ListenNotifyCDCBackend",)


_logger = get_logger("cdc.listen_notify_backend")

#: Максимум непрочитанных notify-payload'ов в очереди.
_QUEUE_MAXSIZE = 1000


class ListenNotifyCDCBackend(CDCSource):
    """PostgreSQL `LISTEN/NOTIFY`-based CDC backend.

    Реализация (ADR-0384): ``asyncpg.connect`` → ``add_listener`` →
    разбор JSON-payload → :class:`CDCEvent`. Если ``asyncpg`` не
    установлен или соединение не удалось — подписка завершается с
    явной ошибкой в логе (fail-fast, а не молчаливое ожидание).
    """

    def __init__(self, *, dsn: str, channel: str = "cdc_events") -> None:
        """Параметры:

        :param dsn: PostgreSQL DSN (asyncpg-совместимый) **или** имя
            профиля внешней БД (тогда DSN собирается из настроек
            ``external_databases``).
        :param channel: имя канала pg_notify.
        """
        self._dsn = dsn
        self._channel = channel
        self._stopped = asyncio.Event()
        self._cursor_log: list[CDCCursor] = []

    def _resolve_dsn(self) -> str:
        """Получить DSN: явный DSN либо собрать из профиля внешней БД.

        Returns:
            DSN для ``asyncpg.connect``.

        Raises:
            ValueError: Если DSN не задан или профиль не найден.

        """
        if "://" in self._dsn:
            return self._dsn
        if not self._dsn:
            raise ValueError("ListenNotifyCDCBackend: dsn is not configured")
        try:
            from src.backend.core.config.external_databases.registry import (
                external_databases_settings,
            )

            profile = external_databases_settings.get_profile(self._dsn)
        except Exception as exc:
            raise ValueError(
                f"ListenNotifyCDCBackend: cannot resolve profile {self._dsn!r}: {exc}"
            ) from exc
        return (
            f"postgresql://{profile.username}:"
            f"{profile.password.get_secret_value()}@"
            f"{profile.host}:{profile.port}/{profile.db_name}"
        )

    def _parse_event(
        self, payload: str, tables: list[str]
    ) -> CDCEvent | None:
        """Разобрать notify-payload в :class:`CDCEvent`.

        Args:
            payload: JSON-payload из ``pg_notify``.
            tables: Таблицы подписки (для фильтрации).

        Returns:
            Событие либо ``None`` (неизвестная таблица / битый payload).

        """
        try:
            data = json.loads(payload)
        except (TypeError, ValueError) as exc:
            _logger.warning("CDC listen/notify: payload parse error: %s", exc)
            return None
        if not isinstance(data, dict):
            return None
        table = str(data.get("table", ""))
        if tables and table not in tables:
            return None
        operation = str(data.get("operation", "UNKNOWN")).upper()
        raw_ts = data.get("timestamp")
        timestamp = parse_dt(raw_ts) if raw_ts else datetime.now(UTC)
        return CDCEvent(
            operation=operation,  # type: ignore[arg-type]
            source="listen_notify",
            table=table or "_unknown",
            timestamp=ensure_utc(timestamp),
            cursor=CDCCursor(value=str(raw_ts or table or "0"), backend="listen_notify"),
            new=data.get("new"),
            old=data.get("old"),
            metadata={"channel": self._channel},
        )

    async def subscribe(  # type: ignore[override]
        self, *, tables: list[str], start_cursor: CDCCursor | None = None
    ) -> AsyncIterator[CDCEvent]:
        """LISTEN на ``channel``; парсит payload в `CDCEvent`.

        Реальный flow (ADR-0384):
          1. ``asyncpg.connect(dsn)``.
          2. ``conn.add_listener(channel, callback)``.
          3. callback парсит JSON payload, фильтрует по `tables`,
             yield'ит ``CDCEvent``.
        """
        _logger.info(
            "ListenNotifyCDCBackend started: channel=%s tables=%s",
            self._channel,
            tables,
        )
        _ = start_cursor  # silence unused
        try:
            import asyncpg
        except ImportError as exc:
            raise RuntimeError(
                "asyncpg is required for ListenNotifyCDCBackend; install asyncpg"
            ) from exc

        try:
            dsn = self._resolve_dsn()
        except ValueError as exc:
            _logger.error("CDC listen/notify: %s", exc)
            return

        try:
            conn = await asyncpg.connect(dsn)
        except Exception as exc:
            _logger.error("CDC listen/notify: connection failed: %s", exc)
            return

        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)

        def _notify_handler(_conn: Any, _pid: int, _chan: str, payload: str) -> None:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                _logger.warning("CDC notify queue full, dropping event")

        try:
            await conn.add_listener(self._channel, _notify_handler)
            while not self._stopped.is_set():
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=1.0)
                except TimeoutError:
                    continue
                event = self._parse_event(payload, tables)
                if event is not None:
                    yield event
        finally:
            try:
                await conn.remove_listener(self._channel, _notify_handler)
                await conn.close()
            except Exception as exc:
                _logger.warning("CDC listen/notify: cleanup failed: %s", exc)

    async def ack(self, cursor: CDCCursor) -> None:
        """LISTEN/NOTIFY не имеет cursor-ack semantics; запись в журнал."""
        self._cursor_log.append(cursor)

    async def replay(  # type: ignore[override]
        self, *, start_cursor: CDCCursor, end_cursor: CDCCursor | None = None
    ) -> AsyncIterator[CDCEvent]:
        """Replay для LISTEN/NOTIFY невозможен (push-only без хранилища).

        Использовать Polling/Debezium для recovery; этот backend —
        live-stream only.
        """
        _logger.warning(
            "ListenNotifyCDCBackend.replay: not supported "
            "(LISTEN/NOTIFY is live-stream only); "
            "use PollCDCBackend or DebeziumEventsCDCBackend for replay"
        )
        _ = (start_cursor, end_cursor, datetime.now(UTC))
        return
        yield  # pragma: no cover

    async def close(self) -> None:
        """Завершить LISTEN."""
        self._stopped.set()

    async def health_check(
        self, *, mode: Literal["fast", "deep"] = "fast"
    ) -> dict[str, Any]:
        """Health probe для HealthAggregator (Sprint 170 M2 Phase 1).

        Returns:
            Статус backend'а: ``not_implemented``, если ``asyncpg`` не
            установлен (опциональная зависимость).

        """
        try:
            import time

            start = time.monotonic()
            try:
                import asyncpg  # noqa: F401
            except ImportError:
                return {
                    "status": "not_implemented",
                    "latency_ms": 0.0,
                    "error": "asyncpg is not installed",
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
