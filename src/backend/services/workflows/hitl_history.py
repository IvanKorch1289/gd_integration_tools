"""HITL history service — Sprint 12 K5 W2.

Читает workflow_audit ClickHouse записи с event_type IN
('hitl.approved', 'hitl.rejected', 'hitl.requested_info') и
возвращает структурированные records для page 72 History tab.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

__all__ = ("HitlHistoryRecord", "HitlHistoryService")

_logger = logging.getLogger("services.workflows.hitl_history")


_HITL_EVENT_TYPES = frozenset({"hitl.approved", "hitl.rejected", "hitl.requested_info"})


@dataclass(frozen=True, slots=True)
class HitlHistoryRecord:
    """Одна запись HITL history для UI."""

    signal_id: str
    workflow_id: str
    tenant_id: str | None
    action: str
    operator: str | None
    requested_at: datetime | None
    resolved_at: datetime
    duration_ms: int | None
    comment: str | None


class HitlHistoryService:
    """Service для извлечения HITL history из workflow_audit."""

    def __init__(self, clickhouse_client_factory: Any | None = None) -> None:
        self._factory = clickhouse_client_factory

    async def _get_client(self) -> Any:
        if self._factory is not None:
            return await self._factory()
        from clickhouse_connect import get_async_client  # type: ignore[import-untyped]

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
        return await get_async_client(host=host, port=port, database=database)

    async def get_history(
        self,
        *,
        tenant_id: str | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        action: str | None = None,
        operator: str | None = None,
        limit: int = 100,
    ) -> list[HitlHistoryRecord]:
        """Возвращает HITL history с применением фильтров."""
        import json
        from datetime import datetime as _dt
        from datetime import timedelta as _td
        from datetime import timezone as _tz

        limit = max(1, min(limit, 1000))
        to_dt = to_dt or _dt.now(_tz.utc)
        from_dt = from_dt or (to_dt - _td(days=30))

        try:
            client = await self._get_client()
        except Exception as exc:  # noqa: BLE001
            _logger.warning("CH unavailable: %s", exc)
            return []

        conditions = [
            "created_at >= %(from_dt)s",
            "created_at <= %(to_dt)s",
            "event_type IN ('hitl.approved', 'hitl.rejected', 'hitl.requested_info')",
        ]
        params: dict[str, Any] = {"from_dt": from_dt, "to_dt": to_dt, "limit": limit}
        if tenant_id:
            conditions.append("tenant_id = %(tenant_id)s")
            params["tenant_id"] = tenant_id
        if action:
            ev_type = {
                "approve": "hitl.approved",
                "reject": "hitl.rejected",
                "request_info": "hitl.requested_info",
            }.get(action, f"hitl.{action}")
            conditions.append("event_type = %(event_type)s")
            params["event_type"] = ev_type
        if operator:
            conditions.append("actor = %(operator)s")
            params["operator"] = operator

        sql = (  # noqa: S608
            "SELECT workflow_id, tenant_id, event_type, actor, payload, "  # noqa: S608
            "  created_at, duration_ms "
            f"FROM workflow_audit WHERE {' AND '.join(conditions)} "
            "ORDER BY created_at DESC LIMIT %(limit)s"
        )

        try:
            result = await client.query(sql, parameters=params)
        except Exception as exc:  # noqa: BLE001
            _logger.warning("CH query failed: %s", exc)
            return []

        records: list[HitlHistoryRecord] = []
        for row in getattr(result, "result_rows", []):
            try:
                payload = json.loads(row[4]) if row[4] else {}
            except TypeError, json.JSONDecodeError:
                payload = {}
            event_type = row[2]
            action_str = event_type.removeprefix("hitl.")
            records.append(
                HitlHistoryRecord(
                    signal_id=payload.get("signal_id", ""),
                    workflow_id=row[0],
                    tenant_id=row[1],
                    action=action_str,
                    operator=row[3],
                    requested_at=None,
                    resolved_at=row[5],
                    duration_ms=row[6],
                    comment=payload.get("comment"),
                )
            )
        return records
