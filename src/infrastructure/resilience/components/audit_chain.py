"""Wiring W26.3: ClickHouse → PG audit table → JSONL.

Контракт примарного callable:

.. code-block:: python

    async def audit_append(record: AuditRecord) -> None: ...

Все backend'ы реализуют один и тот же контракт:
``AuditBackend.append(AuditRecord)``. Coordinator вызывает primary
(ClickHouse-через-AuditEventLog), при failure спускается по chain:
``pg_audit`` → ``jsonl``.

PG-audit-table использует ту же ``app_audit`` таблицу для сообщений
аудита (определена в alembic-миграции W21). Если PG тоже недоступен —
fallback в JSONL гарантирует, что событие не теряется (диск всегда
есть).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from src.core.interfaces.audit import AuditBackend, AuditRecord

__all__ = (
    "AuditCallable",
    "build_audit_fallbacks",
    "build_audit_primary",
)

logger = logging.getLogger(__name__)

AuditCallable = Callable[[AuditRecord], Awaitable[None]]


async def _clickhouse_append(record: AuditRecord) -> None:
    """Primary: ClickHouse через ``AuditEventLog``."""
    from src.infrastructure.audit.event_log import AuditEvent, get_audit_log

    event = AuditEvent(
        who=str(record.get("who", "")),
        what=str(record.get("what", record.get("event", ""))),
        entity_type=str(record.get("entity_type", "")),
        entity_id=str(record.get("entity_id", "")),
        action=str(record.get("action", "")),
        before=record.get("before"),
        after=record.get("after"),
        metadata=record.get("metadata") or {},
    )
    log = get_audit_log()
    await log.emit(event)


async def _pg_audit_append(record: AuditRecord) -> None:
    """Fallback 1: SQLAlchemy INSERT в таблицу ``app_audit`` PG.

    Использует существующую сессию через ``get_db_session``. PG —
    эфемерное хранилище (snapshot уходит в ClickHouse), но для
    durability при отказе CH этого достаточно.
    """
    from sqlalchemy import text

    from src.infrastructure.database.database import get_db_session

    async with get_db_session() as session:
        await session.execute(
            text(
                "INSERT INTO app_audit (record_json, created_at) "
                "VALUES (:record, NOW())"
            ),
            {"record": dict(record)},
        )
        await session.commit()


def build_jsonl_append(path: str | Path) -> AuditCallable:
    """Fallback 2: append-only JSONL (нерушимый — диск всегда доступен)."""
    from src.infrastructure.audit.jsonl_audit import JsonlAuditBackend

    backend: AuditBackend = JsonlAuditBackend(path)

    async def _append(record: AuditRecord) -> None:
        await backend.append(record)

    return _append


def build_audit_primary() -> AuditCallable:
    """Возвращает primary callable для chain ``clickhouse``."""
    return _clickhouse_append


def build_audit_fallbacks(
    *, jsonl_path: str | Path = "logs/audit.jsonl"
) -> dict[str, AuditCallable]:
    """Возвращает {chain_id: callable} для fallback-цепочки.

    Идентификаторы ``pg_audit`` и ``jsonl`` соответствуют ``chain``
    в ``config_profiles/base.yml`` (резерв порядок имеет значение).
    """
    return {
        "pg_audit": _pg_audit_append,
        "jsonl": build_jsonl_append(jsonl_path),
    }


def coerce_record(record: Any) -> AuditRecord:
    """Утилита: гарантирует, что dict преобразован в ``AuditRecord``."""
    if isinstance(record, AuditRecord):
        return record
    if isinstance(record, dict):
        return AuditRecord(record)
    raise TypeError(
        f"audit append: ожидался dict или AuditRecord, получен {type(record).__name__}"
    )
