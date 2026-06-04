"""DSL processor ``audit_clickhouse`` (K8 Wave 4, V15 audit trail).

Записывает security/business событие в ClickHouse audit trail
через :class:`~src.backend.services.audit.ClickHouseAuditService`.

Процессор работает в режиме "fire and forget" — ошибки записи
логируются как warning, но не останавливают pipeline.

При ``feature_flags.audit_clickhouse_enabled=False`` вызов
``get_audit_service().emit()`` является no-op без ошибки.

Использование в YAML::

    steps:
      - audit_clickhouse:
          event_type: user.login
          severity: info
          payload:
            ip: ${headers.x-forwarded-for}

Использование в Python-builder::

    RouteBuilder("auth_login") \\
        .from_("http:POST /api/v1/auth/login") \\
        ...
        # (builder-метод audit_clickhouse будет добавлен в Wave G)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = ("AuditClickhouseParams", "AuditClickhouseProcessor")


class AuditClickhouseParams(BaseModel):
    """Параметры DSL-шага ``audit_clickhouse``.

    Атрибуты:
        event_type: Тип события (например ``user.login``, ``order.created``).
        payload: Дополнительный словарь данных (опционально).
        severity: Уровень важности: ``info`` | ``warning`` | ``error``.
        tenant_id_from: Выражение exchange-property для tenant_id (опционально).
        user_id_from: Выражение exchange-property для user_id (опционально).
        route_name_from: Выражение exchange-property для route_name (опционально).
    """

    event_type: str = Field(
        ...,
        description="Тип события (например user.login, order.created).",
        min_length=1,
    )
    payload: dict[str, Any] | None = Field(
        default=None,
        description="Дополнительные данные события (сериализуются в JSON).",
    )
    severity: Literal["info", "warning", "error"] = Field(
        default="info", description="Уровень важности события."
    )
    tenant_id_from: str | None = Field(
        default=None, description="Имя exchange-property для tenant_id."
    )
    user_id_from: str | None = Field(
        default=None, description="Имя exchange-property для user_id."
    )
    route_name_from: str | None = Field(
        default=None, description="Имя exchange-property для route_name."
    )


@processor(
    "audit_clickhouse",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "event_type": {"type": "string", "minLength": 1},
            "payload": {"type": ["object", "null"]},
            "severity": {
                "type": "string",
                "enum": ["info", "warning", "error"],
                "default": "info",
            },
            "tenant_id_from": {"type": ["string", "null"]},
            "user_id_from": {"type": ["string", "null"]},
            "route_name_from": {"type": ["string", "null"]},
        },
        "required": ["event_type"],
        "additionalProperties": False,
    },
    meta={"tier": 2, "category": "audit"},
)
class AuditClickhouseProcessor(BaseProcessor):
    """Записывает audit-событие в ClickHouse (K8 audit trail).

    Вызывает :func:`~src.backend.services.audit.get_audit_service` singleton
    и отправляет :class:`~src.backend.services.audit.AuditEvent` через
    ``emit()``. При ``audit_clickhouse_enabled=False`` — no-op без ошибки.

    Args:
        event_type: Тип события для записи в ``event_type`` колонку.
        payload: Дополнительные данные события (dict или None).
        severity: Уровень важности события.
        tenant_id_from: Имя exchange-property для tenant_id.
        user_id_from: Имя exchange-property для user_id.
        route_name_from: Имя exchange-property для route_name.
    """

    def __init__(
        self,
        event_type: str,
        *,
        payload: dict[str, Any] | None = None,
        severity: Literal["info", "warning", "error"] = "info",
        tenant_id_from: str | None = None,
        user_id_from: str | None = None,
        route_name_from: str | None = None,
        name: str | None = None,
    ) -> None:
        """Инициализирует процессор с параметрами audit-события.

        Args:
            event_type: Тип события (например ``user.login``).
            payload: Статический payload или None.
            severity: Уровень важности.
            tenant_id_from: Имя property в exchange для tenant_id.
            user_id_from: Имя property в exchange для user_id.
            route_name_from: Имя property в exchange для route_name.
            name: Переопределение имени процессора для логов.
        """
        super().__init__(name=name or f"audit_clickhouse:{event_type}")
        self._event_type = event_type
        self._payload = payload or {}
        self._severity = severity
        self._tenant_id_from = tenant_id_from
        self._user_id_from = user_id_from
        self._route_name_from = route_name_from

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Формирует и отправляет AuditEvent в ClickHouse.

        Извлекает tenant_id, user_id, route_name из exchange-properties
        (если указаны соответствующие ``*_from`` параметры), затем вызывает
        ``get_audit_service().emit()``.

        Args:
            exchange: Текущий контекст обмена данными в pipeline.
            context: Контекст выполнения с конфигурацией и зависимостями.
        """
        from src.backend.services.audit.clickhouse_audit_service import (
            AuditEvent,
            get_audit_service,
        )

        # Извлекаем динамические поля из exchange
        tenant_id: str | None = None
        user_id: str | None = None
        route_name: str | None = None

        if self._tenant_id_from:
            val = exchange.get_property(self._tenant_id_from)
            tenant_id = str(val) if val is not None else None

        if self._user_id_from:
            val = exchange.get_property(self._user_id_from)
            user_id = str(val) if val is not None else None

        if self._route_name_from:
            val = exchange.get_property(self._route_name_from)
            route_name = str(val) if val is not None else None

        event = AuditEvent(
            event_id=str(uuid.uuid4()),
            timestamp=datetime.now(UTC),
            event_type=self._event_type,
            tenant_id=tenant_id,
            user_id=user_id,
            route_name=route_name,
            payload=self._payload,
            severity=self._severity,
        )

        await get_audit_service().emit(event)

    def to_spec(self) -> dict[str, Any]:
        """YAML-spec round-trip для audit_clickhouse шага.

        Returns:
            Словарь, совместимый с DSL YAML-форматом шага ``audit_clickhouse``.
        """
        spec: dict[str, Any] = {
            "event_type": self._event_type,
            "severity": self._severity,
        }
        if self._payload:
            spec["payload"] = self._payload
        if self._tenant_id_from:
            spec["tenant_id_from"] = self._tenant_id_from
        if self._user_id_from:
            spec["user_id_from"] = self._user_id_from
        if self._route_name_from:
            spec["route_name_from"] = self._route_name_from
        return {"audit_clickhouse": spec}
