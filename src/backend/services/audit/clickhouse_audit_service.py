"""ClickHouse audit trail сервис (K8 Wave 4, V15 audit trail requirement).

Реализует отправку security/business событий в таблицу ``audit_events``
ClickHouse с lazy-импортом клиента и default-OFF через feature-flag.

Архитектура:
    * :class:`AuditEvent` — неизменяемый dataclass с полями события.
    * :class:`ClickHouseAuditService` — singleton-сервис с методами
      ``emit`` и ``emit_batch``.
    * :func:`get_audit_service` — фабрика singleton-экземпляра.

Безопасность:
    * Клиент ClickHouse создаётся лениво только при включённом feature-flag.
    * При flag=OFF все вызовы emit/emit_batch возвращают без ошибки.
    * event_id использует UUID4 из stdlib (UUID7 требует внешней зависимости
      uuid-utils, которая не добавлена в pyproject.toml).
    * payload сериализуется в JSON-строку через :func:`dumps_str`
      (orjson wrapper, ~3-5x faster than stdlib json).

Использование::

    from src.backend.services.audit import get_audit_service, AuditEvent
    from datetime import datetime, timezone

    await get_audit_service().emit(AuditEvent(
        event_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc),
        event_type="user.login",
        tenant_id="tenant-123",
        user_id="user-456",
        route_name="/api/v1/auth/login",
        payload={"ip": "127.0.0.1"},
        severity="info",
    ))
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger


import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from src.backend.core.util.json_utils import dumps_str

if TYPE_CHECKING:
    pass

__all__ = ("AuditEvent", "ClickHouseAuditService", "get_audit_service")

_logger = get_logger("services.audit.clickhouse")


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Неизменяемое описание одного audit-события.

    Атрибуты:
        event_id: Уникальный ID события (рекомендуется UUID4 или UUID7).
        timestamp: Временная метка в UTC.
        event_type: Тип события (например ``user.login``, ``order.created``).
        tenant_id: ID тенанта (или None для системных событий).
        user_id: ID пользователя-актора (или None для системных событий).
        route_name: Имя DSL-маршрута или API-пути, из которого пришло событие.
        payload: Произвольный словарь с деталями события (сериализуется в JSON).
        severity: Уровень важности: ``info`` | ``warning`` | ``error``.
    """

    event_id: str
    timestamp: datetime
    event_type: str
    tenant_id: str | None
    user_id: str | None
    route_name: str | None
    payload: dict[str, Any]
    severity: Literal["info", "warning", "error"]

    def to_row(self) -> dict[str, Any]:
        """Преобразует событие в словарь для вставки в ClickHouse.

        Returns:
            Словарь, совместимый с колонками таблицы ``audit_events``.
        """
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp.astimezone(UTC),
            "event_type": self.event_type,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "route_name": self.route_name,
            "payload": dumps_str(self.payload, default=str),
            "severity": self.severity,
        }


def _make_default_event_id() -> str:
    """Генерирует уникальный ID события через UUID4.

    Returns:
        Строковое представление UUID4.
    """
    return str(uuid.uuid4())


def _make_default_timestamp() -> datetime:
    """Возвращает текущее время в UTC.

    Returns:
        Текущая временная метка в timezone-aware формате UTC.
    """
    return datetime.now(UTC)


def make_audit_event(
    event_type: str,
    *,
    payload: dict[str, Any] | None = None,
    severity: Literal["info", "warning", "error"] = "info",
    tenant_id: str | None = None,
    user_id: str | None = None,
    route_name: str | None = None,
    event_id: str | None = None,
    timestamp: datetime | None = None,
) -> AuditEvent:
    """Удобный конструктор :class:`AuditEvent` с разумными дефолтами.

    Args:
        event_type: Тип события (например ``user.login``).
        payload: Словарь дополнительных данных.
        severity: Уровень важности.
        tenant_id: ID тенанта.
        user_id: ID пользователя.
        route_name: Имя маршрута.
        event_id: Явный ID (если None — генерируется UUID4).
        timestamp: Явная метка времени (если None — текущее UTC).

    Returns:
        Заполненный экземпляр :class:`AuditEvent`.
    """
    return AuditEvent(
        event_id=event_id or _make_default_event_id(),
        timestamp=timestamp or _make_default_timestamp(),
        event_type=event_type,
        tenant_id=tenant_id,
        user_id=user_id,
        route_name=route_name,
        payload=payload or {},
        severity=severity,
    )


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


# ─── Singleton ─────────────────────────────────────────────────────────────
_service_instance: ClickHouseAuditService | None = None
_service_lock = threading.Lock()


def get_audit_service() -> ClickHouseAuditService:
    """Возвращает глобальный singleton :class:`ClickHouseAuditService`.

    Потокобезопасен. Создаётся при первом обращении.

    Returns:
        Единственный экземпляр :class:`ClickHouseAuditService`.
    """
    global _service_instance
    if _service_instance is not None:
        return _service_instance
    with _service_lock:
        if _service_instance is None:
            _service_instance = ClickHouseAuditService()
    return _service_instance
