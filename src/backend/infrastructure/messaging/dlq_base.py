"""Unified DLQ envelope schema (Sprint 8 K2 W3 scaffold).

Цель: единый ``DLQEnvelope`` для всех 4 транспортов (HTTP/SOAP/gRPC/Webhook)
и общий ``DLQWriter`` protocol. Реальная интеграция с транспортами и
DLQ-таблицей — Sprint 9 carryover (K2 W3).

V15 R-V15-1: универсальный envelope сохраняет trace_id + payload + error
для корреляции с outbox/audit + ручного re-publish из admin-панели.

DoD scaffold (Sprint 8):
* :class:`DLQEnvelope` — Pydantic-модель с обязательными полями.
* :class:`DLQWriter` — Protocol для backend-агностичной записи.
* :class:`DLQReason` — Enum для классификации причин.

DoD full (S9 carryover):
* 4 транспорта импортируют ``DLQEnvelope`` и пишут через ``DLQWriter``.
* Integration test проверяет round-trip publish → DLQ → admin replay.
* Grafana-dashboard outbox_dlq_depth.json расширен per-transport breakdown.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, Field

__all__ = ("DLQEnvelope", "DLQReason", "DLQWriter")


class DLQReason(StrEnum):
    """Классификация причин попадания в DLQ.

    Используется для алёртов и Grafana-dashboard breakdown.
    """

    TIMEOUT = "timeout"
    """Истёк timeout backend-вызова (4XX от proxy / 5XX от upstream)."""

    RETRIES_EXHAUSTED = "retries_exhausted"
    """Превышен max_retries; resilience-policy исчерпана."""

    VALIDATION_FAILED = "validation_failed"
    """Response/Request не прошёл Pydantic-схему."""

    CAPABILITY_DENIED = "capability_denied"
    """Capability-gate отклонил вызов (V11.1)."""

    WAF_BLOCKED = "waf_blocked"
    """WAF-policy заблокировал external-вызов (R-V15-5)."""

    UNEXPECTED = "unexpected"
    """Прочая фатальная ошибка; см. ``error_class`` для деталей."""


class DLQEnvelope(BaseModel):
    """Unified envelope для DLQ-записи.

    Поля совместимы с outbox-моделью (см.
    :class:`src.backend.infrastructure.database.models.outbox.OutboxEvent`),
    но включают transport-агностичные дополнения.

    Attributes:
        dlq_id: UUID записи (генерируется при создании, primary key).
        transport: Имя транспорта ("http"/"soap"/"grpc"/"webhook").
        trace_id: OpenTelemetry trace-id (для корреляции с audit/logs).
        tenant_id: ID tenant'а (для per-tenant квот и cleanup).
        route_id: DSL route, инициировавший вызов (если применимо).
        original_payload: Исходный body запроса (для replay).
        error_class: Имя класса исключения (httpx.ConnectTimeout, ...).
        error_message: Stringified message исключения.
        reason: Высокоуровневая категория (см. :class:`DLQReason`).
        retry_count: Сколько retry-попыток уже сделано.
        first_failed_at: Timestamp первой failure (UTC).
        last_failed_at: Timestamp последней failure (UTC).
        metadata: Произвольные пары ключ-значение для debug-контекста
            (request_id, upstream_url, response_code, и т.п.).
    """

    dlq_id: str = Field(default_factory=lambda: str(uuid4()))
    transport: str
    trace_id: str | None = None
    tenant_id: str | None = None
    route_id: str | None = None
    original_payload: Any = None
    error_class: str
    error_message: str
    reason: DLQReason = DLQReason.UNEXPECTED
    retry_count: int = 0
    first_failed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_failed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    dlq_class: str = "operational"
    """S13 K3 W4: класс для policy-based retention (``financial`` / ``analytics`` / ``operational``)."""
    metadata: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class DLQWriter(Protocol):
    """Backend-агностичный writer для DLQ.

    Реализации:
    * ``OutboxDLQWriter`` (S8 baseline) — пишет в Postgres outbox с
      статусом ``failed``.
    * ``InMemoryDLQWriter`` (тесты) — собирает в list для assertions.
    * ``KafkaDLQWriter`` (S9 carryover) — публикует в dedicated Kafka topic.

    Все транспорты получают writer через DI (см. composition root).
    """

    async def write(self, envelope: DLQEnvelope) -> None:
        """Записывает envelope в backend (idempotent по ``dlq_id``)."""
        ...
