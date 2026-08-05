"""S68 W2 - service.py part of clickhouse_audit_service decomp.

Classes: ClickHouseAuditService.

S180 P1-#1 (S36 multi-agent audit follow-up T7):
ClickHouse DLQ unification через единый :class:`DLQWriter` Protocol.
Backward-compat: legacy ``dlq_path`` (JSONL) сохранён с WARNING.
Приоритет: ``dlq_writer`` через setter > ``dlq_path`` legacy.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from src.backend.core.interfaces.audit import AuditBackend, AuditRecord
from src.backend.core.logging import get_logger
from src.backend.services.audit.clickhouse_audit_service.state import AuditEvent

if TYPE_CHECKING:
    from src.backend.infrastructure.messaging.dlq_base import DLQWriter

_logger = get_logger("services.audit.clickhouse")


class ClickHouseAuditService:
    """Сервис записи audit-событий в ClickHouse.

    Создание клиента ClickHouse выполняется лениво при первом вызове
    ``emit``/``emit_batch``, только если ``feature_flags.audit_clickhouse_enabled``
    равен ``True``.

    При flag=OFF все вызовы возвращают без ошибки (no-op), что позволяет
    свободно использовать сервис в коде без условий.

    DLQ-fallback (при сбое ``client.insert()``) — два пути (по приоритету):

    1. ``dlq_writer`` через setter (:meth:`set_dlq_writer`) — единый
       :class:`~src.backend.infrastructure.messaging.dlq_base.DLQWriter`
       Protocol. Канонический путь (Postgres/Kafka/Redis/RabbitMQ через
       существующие :class:`InboxDLQWriter`/:class:`KafkaDLQWriter`/etc.).
    2. ``dlq_path`` legacy (JSONL) — backward-compat, deprecated.
       Ponytail: legacy path остаётся для непрерывности старых deployment;
       canonical-путь через DLQWriter требует migration-flag.
    3. None → silent loss + WARNING (как было до S36 P0 fix).

    Атрибуты:
        _client: Ленивый async-клиент ClickHouse (создаётся по требованию).
        _lock: Мьютекс для потокобезопасного singleton-доступа к _client.
        _dlq_writer: опциональный canonical DLQWriter (preferred).
        _dlq_path: legacy JSONL-path (backward-compat).
        _dlq_backend: lazy ``JsonlAuditBackend`` для legacy-DLQ (None если
            ``dlq_path`` не задан).
    """

    _TABLE = "audit_events"

    def __init__(
        self,
        client: Any | None = None,
        dlq_path: Any | None = None,
        dlq_writer: "DLQWriter | None" = None,
    ) -> None:
        """Инициализирует сервис с опциональным pre-built клиентом.

        Args:
            client: Готовый async-клиент ClickHouse (для тестов/инъекции).
                Если None — будет создан лениво при первом вызове.
            dlq_path: [DEPRECATED, S180] Путь к JSONL-файлу для DLQ-fallback.
                Использовать ``set_dlq_writer(DLQWriter)`` для canonical path.
                Сохранён для backward-compat — для prod-migration переключиться
                на InboxDLQWriter / KafkaDLQWriter через composition root.
            dlq_writer: [S180 P1-#1] Канонический DLQWriter через Protocol.
                Приоритет над ``dlq_path``. Если None — setter можно
                использовать post-init (см. :meth:`set_dlq_writer`).
        """
        self._client: Any | None = client
        self._lock = threading.Lock()
        self._dlq_writer: "DLQWriter | None" = dlq_writer
        self._dlq_path = dlq_path
        self._dlq_backend: AuditBackend | None = None
        self._dlq_lock = threading.Lock()

    def set_dlq_writer(self, writer: "DLQWriter | None") -> None:
        """Установить/сбросить canonical DLQWriter (composition root wiring).

        S180 P1-#1: позволяет composer установить writer после init.
        Тот же паттерн, что и ``CDCClient.set_dlq_writer`` (S176 cycle 33) —
        singleton-friendly.
        """
        self._dlq_writer = writer

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

        B-11 fix (cycle 33): factory ``get_jsonl_backend`` живёт в
        ``core.audit.facade`` — capability-checked обёртка над
        infrastructure-слоем. Раньше backend подгружался через
        ``importlib.import_module`` (bypass layer-rules); теперь —
        явный facade-import, попадает под статический контроль
        ``check_layers.py`` (services → core разрешён).
        """
        if self._dlq_path is None:
            return None
        if self._dlq_backend is None:
            with self._dlq_lock:
                if self._dlq_backend is None:
                    from src.backend.core.audit.facade import get_jsonl_backend

                    self._dlq_backend = get_jsonl_backend(self._dlq_path)
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
        """Пишет failed-event(ы) в DLQ.

        Приоритет (S180 P1-#1):
        1. ``self._dlq_writer`` (canonical) → через ``DLQWriter.write(envelope)``.
        2. ``self._dlq_path`` legacy → JSONL через ``JsonlAuditBackend``.
        3. None → silent loss (no-op).

        Fire-and-forget: исключение DLQ-записи НЕ пробрасывается caller'у
        (audit-middleware не должен падать из-за observability-сбоя).

        Args:
            event: Одиночное событие (для ``emit``) или None для batch.
            events: Список событий (для ``emit_batch``) или None для single.
            error: исключение от ClickHouse.
            reason: high-level причина (идёт в ``metadata.dlq_reason``).
            action: high-level действие (legacy JSONL только).
        """
        targets = events if events is not None else ([event] if event is not None else [])
        if not targets:
            return

        # Приоритет 1: canonical DLQWriter Protocol (Inbox / Kafka / NATS / etc.).
        if self._dlq_writer is not None:
            try:
                # Lazy import для layer-clean (services → infrastructure).
                from src.backend.infrastructure.messaging.dlq_base import (
                    DLQEnvelope,
                    DLQReason,
                )

                for ev in targets:
                    envelope = DLQEnvelope(
                        transport="clickhouse_audit",
                        trace_id=None,
                        tenant_id=getattr(ev, "tenant_id", None) if ev else None,
                        route_id=getattr(ev, "route_name", None) if ev else None,
                        original_payload=ev.to_row() if ev else None,
                        error_class=type(error).__name__,
                        error_message=str(error),
                        reason=DLQReason.UNEXPECTED,
                        metadata={"action": action, "reason": reason},
                        dlq_class="operational",
                    )
                    await self._dlq_writer.write(envelope)
            except Exception as dlq_exc:
                # S180 P1-#1 — same fire-and-forget semantics as legacy path.
                _logger.error(
                    "DLQWriter fallback failed (count=%d, transport=clickhouse_audit) error=%s",
                    len(targets),
                    dlq_exc,
                )
            return

        # Приоритет 2: legacy JSONL path (deprecated, для старых deployment).
        backend = self._get_dlq_backend()
        if backend is None:
            return
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
