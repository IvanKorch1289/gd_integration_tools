"""S68 W2 - service.py part of clickhouse_audit_service decomp.

Classes: ClickHouseAuditService.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from src.backend.core.interfaces.audit import AuditBackend, AuditRecord
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

    При сбое ClickHouse (``client.insert()`` raises) и заданном ``dlq_path``
    событие сериализуется в ``AuditRecord`` и пишется через
    :class:`~src.backend.infrastructure.audit.jsonl_audit.JsonlAuditBackend`
    (append-only JSONL). Без ``dlq_path`` поведение остаётся legacy
    (WARNING + silent loss) для backward-compat.

    Атрибуты:
        _client: Ленивый async-клиент ClickHouse (создаётся по требованию).
        _lock: Мьютекс для потокобезопасного singleton-доступа к _client.
        _dlq_backend: lazy ``JsonlAuditBackend`` для DLQ-fallback (None если
            ``dlq_path`` не задан).
    """

    _TABLE = "audit_events"

    def __init__(
        self, client: Any | None = None, dlq_path: Any | None = None
    ) -> None:
        """Инициализирует сервис с опциональным pre-built клиентом.

        Args:
            client: Готовый async-клиент ClickHouse (для тестов/инъекции).
                Если None — будет создан лениво при первом вызове.
            dlq_path: Путь к JSONL-файлу для DLQ-fallback при сбое
                ClickHouse. Если None — legacy silent-loss (без DLQ).
        """
        self._client: Any | None = client
        self._lock = threading.Lock()
        self._dlq_path = dlq_path
        self._dlq_backend: AuditBackend | None = None
        self._dlq_lock = threading.Lock()

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

    def _get_dlq_backend(self) -> AuditBackend | None:
        """Lazily создаёт ``JsonlAuditBackend`` при первом обращении к DLQ.

        Returns ``None`` если ``dlq_path`` не задан (legacy silent-loss path).

        Ponytail: backend подгружается через ``importlib`` чтобы избежать
        прямого ``from src.backend.infrastructure.audit.jsonl_audit``
        import-statement — это layer-violation по правилам check_layers.py
        (services → infrastructure напрямую запрещён).
        """
        if self._dlq_path is None:
            return None
        if self._dlq_backend is None:
            with self._dlq_lock:
                if self._dlq_backend is None:
                    import importlib

                    mod = importlib.import_module(
                        "src.backend.infrastructure.audit.jsonl_audit"
                    )
                    self._dlq_backend = mod.JsonlAuditBackend(self._dlq_path)
        return self._dlq_backend

    async def _send_to_dlq(
        self,
        *,
        event: AuditEvent | None,
        events: list[AuditEvent] | None,
        error: BaseException,
        reason: str = "clickhouse_unavailable",
        action: str = "clickhouse_emit_failed",
    ) -> None:
        """Пишет failed-event(ы) в JSONL DLQ через ``JsonlAuditBackend``.

        Fire-and-forget: исключение DLQ-записи НЕ пробрасывается caller'у
        (audit-middleware не должен падать из-за observability-сбоя).

        Args:
            event: Одиночное событие (для ``emit``) или None для batch.
            events: Список событий (для ``emit_batch``) или None для single.
            error: исключение от ClickHouse.
            reason: high-level причина (идёт в ``metadata.dlq_reason``).
            action: high-level действие (идёт в ``action``).
        """
        backend = self._get_dlq_backend()
        if backend is None:
            return
        targets = events if events is not None else ([event] if event is not None else [])
        try:
            for ev in targets:
                record: AuditRecord = AuditRecord(
                    {
                        "event": ev.event_type if ev else "batch",
                        "action": action,
                        "entity_id": ev.event_id if ev else None,
                        "after": ev.to_row() if ev else None,
                        "metadata": {
                            "dlq_reason": reason,
                            "clickhouse_error": repr(error),
                        },
                    }
                )
                await backend.append(record)
        except Exception as dlq_exc:
            _logger.error(
                "DLQ fallback failed: count=%d error=%s",
                len(targets),
                dlq_exc,
            )

    async def emit(self, event: AuditEvent) -> None:
        """Отправляет одно audit-событие в ClickHouse.

        При выключенном feature-flag (``audit_clickhouse_enabled=False``)
        вызов игнорируется без ошибки.

        При сбое ``client.insert()`` и наличии ``dlq_path`` событие
        персистится в JSONL через :class:`JsonlAuditBackend` для
        последующего forensic/replay.

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

        from src.backend.core.resilience.retry import retry_async

        try:
            client = await self._get_client()
            row = event.to_row()

            async def _do_insert() -> None:
                await client.insert(
                    self._TABLE,
                    data=[list(row.values())],
                    column_names=list(row.keys()),
                )

            await retry_async(
                _do_insert,
                max_attempts=3,
                base_delay=0.5,
                max_delay=5.0,
                op=f"clickhouse_audit_emit {event.event_id}",
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
            await self._send_to_dlq(event=event, events=None, error=exc)

    async def emit_batch(self, events: list[AuditEvent]) -> None:
        """Отправляет пакет audit-событий в ClickHouse (batch insert).

        При выключенном feature-flag вызов игнорируется без ошибки.
        При пустом списке событий возвращает без обращения к ClickHouse.

        При сбое ``client.insert()`` и наличии ``dlq_path`` ВСЕ события
        пакета персистятся в JSONL (для replay после восстановления).

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

        from src.backend.core.resilience.retry import retry_async

        try:
            client = await self._get_client()
            rows = [event.to_row() for event in events]
            column_names = list(rows[0].keys())
            data = [list(row.values()) for row in rows]

            async def _do_insert_batch() -> None:
                await client.insert(
                    self._TABLE, data=data, column_names=column_names
                )

            await retry_async(
                _do_insert_batch,
                max_attempts=3,
                base_delay=0.5,
                max_delay=5.0,
                op=f"clickhouse_audit_emit_batch count={len(events)}",
            )
            _logger.debug("audit emit_batch ok: count=%d", len(events))
        except Exception as exc:
            _logger.warning(
                "ClickHouseAuditService.emit_batch failed: count=%d error=%s",
                len(events),
                exc,
            )
            await self._send_to_dlq(event=None, events=events, error=exc)
