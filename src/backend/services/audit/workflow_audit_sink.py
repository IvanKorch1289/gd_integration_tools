"""WorkflowAuditSink — audit-trail для workflow событий (S12 K1 W1).

Назначение:
    Записывает события жизненного цикла workflow (start / signal /
    cancel / complete / fail) в ClickHouse таблицу ``workflow_audit``
    через :class:`~src.backend.infrastructure.clients.storage.clickhouse_bulk_writer.ClickHouseBulkWriter`,
    обеспечивая ≥10x throughput по сравнению с per-row insert.

    Поток событий:

    .. code-block:: text

        Temporal hook --> WorkflowAuditSink.emit(...)
                              |
                              v
                         ClickHouseBulkWriter
                              | batch INSERT (timer 1s или buffer 1000)
                              v
                       ClickHouse: workflow_audit

Использование::

    from src.backend.services.audit.workflow_audit_sink import (
        WorkflowAuditSink,
    )

    sink = WorkflowAuditSink(writer=clickhouse_bulk_writer)
    await sink.emit(
        event_type="workflow.start",
        workflow_id="wf-123",
        tenant_id="tenant-1",
        payload={"input": {...}},
        trace_id="abc-def",
    )
    # graceful shutdown
    await sink.aclose()

Безопасность:
    payload сериализуется через ``json.dumps(ensure_ascii=False)``.
    На уровне ClickHouse колонка ``payload`` — ``String`` (JSON).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

__all__ = (
    "WorkflowAuditSink",
    "get_workflow_audit_sink",
    "set_workflow_audit_sink",
    "reset_workflow_audit_sink",
)

_logger = logging.getLogger("services.audit.workflow")

_TABLE = "workflow_audit"

# Module-level singleton, инициализируется на startup-фазе через
# :func:`set_workflow_audit_sink` (см. plugins/composition/setup_infra.py).
# Возвращает ``None`` если ClickHouse выключен — caller должен no-op'ить.
_singleton: WorkflowAuditSink | None = None


def get_workflow_audit_sink() -> WorkflowAuditSink | None:
    """Возвращает зарегистрированный singleton sink или ``None``.

    Caller обязан корректно обрабатывать ``None`` — обычно через
    early-return или no-op (никогда не вызывать ``emit`` на ``None``).
    """
    return _singleton


def set_workflow_audit_sink(sink: WorkflowAuditSink | None) -> None:
    """Регистрирует singleton sink (startup-фаза)."""
    global _singleton
    _singleton = sink


def reset_workflow_audit_sink() -> None:
    """Сбрасывает singleton — для unit-тестов и shutdown."""
    global _singleton
    _singleton = None


class WorkflowAuditSink:
    """Обёртка над :class:`ClickHouseBulkWriter` с типизированной схемой.

    Не создаёт собственный writer — делегирует уже инициализированному
    инстансу (DI). Это позволяет переиспользовать единый
    flush-таймер на множестве sink'ов и/или подменить writer в тестах.

    Args:
        writer: уже запущенный :class:`ClickHouseBulkWriter` (метод
            ``add(dict) -> None`` + ``aclose()``); таблица — обычно
            ``"workflow_audit"``.
    """

    def __init__(self, writer: Any) -> None:
        """Инициализирует sink с готовым bulk-writer."""
        self._writer = writer

    async def emit(
        self,
        *,
        event_type: str,
        workflow_id: str,
        tenant_id: str | None,
        payload: dict[str, Any] | None = None,
        trace_id: str | None = None,
        event_id: str | None = None,
        created_at: datetime | None = None,
        actor: str | None = None,
        duration_ms: int | None = None,
        parent_workflow_id: str | None = None,
    ) -> None:
        """Отправляет одно событие в бекенд-writer.

        Расширенный event-set (S12 K1 W1):

        * ``workflow.start`` / ``workflow.signal`` / ``workflow.cancel`` /
          ``workflow.complete`` / ``workflow.fail`` — lifecycle;
        * ``workflow.compensation_start`` / ``workflow.compensation_complete`` /
          ``workflow.compensation_fail`` — saga rollback;
        * ``hitl.approved`` / ``hitl.rejected`` / ``hitl.requested_info`` —
          Human-in-the-Loop decisions.

        Args:
            event_type: тип события.
            workflow_id: уникальный ID workflow execution.
            tenant_id: ID тенанта (или ``None`` для системных событий).
            payload: произвольный словарь деталей; сериализуется в JSON.
            trace_id: ID распределённого трейса (OTEL trace_id или X-Request-Id).
            event_id: явный UUID события (если ``None`` — генерируется UUID4).
            created_at: явная метка времени (если ``None`` — текущее UTC).
            actor: «кто инициировал» — User-Agent, API-key fingerprint,
                ``manage.py`` / ``dsl.cancel_workflow`` и т.п. (S12 K1 W1).
            duration_ms: длительность для terminal events (S12 K2 W1 SLA).
            parent_workflow_id: child-workflow / saga compensation tree
                (S12 K3 W6).
        """
        row = {
            "event_id": event_id or str(uuid.uuid4()),
            "event_type": event_type,
            "workflow_id": workflow_id,
            "tenant_id": tenant_id,
            "payload": json.dumps(payload or {}, ensure_ascii=False),
            "trace_id": trace_id,
            "created_at": (created_at or datetime.now(timezone.utc)).astimezone(
                timezone.utc
            ),
            "actor": actor,
            "duration_ms": duration_ms,
            "parent_workflow_id": parent_workflow_id,
        }
        await self._writer.add(row)
        _logger.debug(
            "workflow_audit.emit",
            extra={
                "event_type": event_type,
                "workflow_id": workflow_id,
                "tenant_id": tenant_id,
            },
        )

    async def emit_batch(
        self,
        events: list[dict[str, Any]],
    ) -> None:
        """Отправляет пакет событий (для bulk-загрузок).

        Каждый элемент должен содержать минимум ``event_type`` и
        ``workflow_id``. Остальные поля имеют разумные дефолты.

        Args:
            events: список словарей-событий.
        """
        if not events:
            return
        rows = []
        now = datetime.now(timezone.utc)
        for raw in events:
            rows.append(
                {
                    "event_id": raw.get("event_id") or str(uuid.uuid4()),
                    "event_type": raw["event_type"],
                    "workflow_id": raw["workflow_id"],
                    "tenant_id": raw.get("tenant_id"),
                    "payload": json.dumps(
                        raw.get("payload") or {}, ensure_ascii=False
                    ),
                    "trace_id": raw.get("trace_id"),
                    "created_at": (raw.get("created_at") or now).astimezone(
                        timezone.utc
                    ),
                }
            )
        await self._writer.add_many(rows)

    async def flush(self) -> int:
        """Принудительный flush буфера. Возвращает число записей."""
        return await self._writer.flush_now()

    async def aclose(self) -> None:
        """Graceful shutdown: финальный flush + остановка writer'а."""
        await self._writer.aclose()

    @property
    def table_name(self) -> str:
        """Имя ClickHouse-таблицы, в которую пишутся события."""
        return _TABLE
