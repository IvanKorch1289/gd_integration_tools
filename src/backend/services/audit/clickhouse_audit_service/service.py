"""S68 W2 - service.py part of clickhouse_audit_service decomp.

Classes: ClickHouseAuditService.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.services.audit.clickhouse_audit_service.state import AuditEvent

if TYPE_CHECKING:
    pass

_logger = get_logger("services.audit.clickhouse")


class ClickHouseAuditService:
    """Сервис записи audit-событий в ClickHouse.

    Создание клиента ClickHouse выполняется лениво при первом вызове
    ``emit``/``emit_batch``, только если ``feature_flags.audit_clickhouse_enabled``
    равен ``True``.

    При flag=OFF все вызовы возвращают без ошибки (no-op), что позволяет
    свободно использовать сервис в коде без условий.

    Атрибуты:
        _client: Ленивый async-клиент ClickHouse (создаётся по требованию).
        _lock: Мьютекс для потокобезопасного singleton-доступа к _client.
    """

    _TABLE = "audit_events"

    def __init__(self, client: Any | None = None) -> None:
        """Инициализирует сервис с опциональным pre-built клиентом.

        Args:
            client: Готовый async-клиент ClickHouse (для тестов/инъекции).
                Если None — будет создан лениво при первом вызове.
        """
        self._client: Any | None = client
        self._lock = threading.Lock()

    async def _get_client(self) -> Any:
        """Возвращает (или создаёт) async-клиент ClickHouse.

        Lazy-создание происходит только при включённом feature-flag.
        Используется ``clickhouse_connect.get_async_client``.

        Returns:
            Async-клиент ClickHouse.

        Raises:
            RuntimeError: Если feature-flag выключен и клиент не предоставлен.
        """
        if self._client is not None:
            return self._client
        with self._lock:
            if self._client is not None:
                return self._client
            # Lazy-импорт тяжёлой зависимости только при включённом flag
            from clickhouse_connect import get_async_client

            from src.backend.core.config import settings

            host = (
                getattr(settings.clickhouse, "host", "localhost")
                if hasattr(settings, "clickhouse")
                else "localhost"
            )
            port = (
                getattr(settings.clickhouse, "port", 8123)
                if hasattr(settings, "clickhouse")
                else 8123
            )
            database = (
                getattr(settings.clickhouse, "database", "default")
                if hasattr(settings, "clickhouse")
                else "default"
            )

            self._client = await get_async_client(
                host=host, port=port, database=database
            )
        return self._client

    async def emit(self, event: AuditEvent) -> None:
        """Отправляет одно audit-событие в ClickHouse.

        При выключенном feature-flag (``audit_clickhouse_enabled=False``)
        вызов игнорируется без ошибки.

        Args:
            event: Событие для записи.
        """
        from src.backend.core.config.features import feature_flags

        if not feature_flags.audit_clickhouse_enabled:
            _logger.debug(
                "audit_clickhouse_enabled=False, skip emit event_type=%s",
                event.event_type,
            )
            return

        try:
            client = await self._get_client()
            row = event.to_row()
            await client.insert(
                self._TABLE, data=[list(row.values())], column_names=list(row.keys())
            )
            _logger.debug(
                "audit emit ok: event_type=%s event_id=%s",
                event.event_type,
                event.event_id,
            )
        except Exception as exc:
            _logger.warning(
                "ClickHouseAuditService.emit failed: event_type=%s error=%s",
                event.event_type,
                exc,
            )

    async def emit_batch(self, events: list[AuditEvent]) -> None:
        """Отправляет пакет audit-событий в ClickHouse (batch insert).

        При выключенном feature-flag вызов игнорируется без ошибки.
        При пустом списке событий возвращает без обращения к ClickHouse.

        Args:
            events: Список событий для batch-вставки.
        """
        from src.backend.core.config.features import feature_flags

        if not feature_flags.audit_clickhouse_enabled:
            _logger.debug(
                "audit_clickhouse_enabled=False, skip emit_batch count=%d", len(events)
            )
            return

        if not events:
            return

        try:
            client = await self._get_client()
            rows = [event.to_row() for event in events]
            column_names = list(rows[0].keys())
            data = [list(row.values()) for row in rows]
            await client.insert(self._TABLE, data=data, column_names=column_names)
            _logger.debug("audit emit_batch ok: count=%d", len(events))
        except Exception as exc:
            _logger.warning(
                "ClickHouseAuditService.emit_batch failed: count=%d error=%s",
                len(events),
                exc,
            )
