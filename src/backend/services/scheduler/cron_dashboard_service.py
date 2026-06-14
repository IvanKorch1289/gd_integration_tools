"""Cron dashboard service — Sprint 12 K5 W3.

Объединяет данные APScheduler (active jobs / next_run_time) с
workflow_audit ClickHouse (success rate за период) для page 14.

API:
    * :class:`ScheduledWorkflowSummary` — одна строка таблицы.
    * :class:`CronDashboardService.list_scheduled()` — все active jobs.
    * :class:`CronDashboardService.get_success_rate(job_id, period_days)`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from typing import Any

from src.backend.core.logging import get_logger

__all__ = ("CronDashboardService", "ScheduledWorkflowSummary")

_logger = get_logger("services.scheduler.dashboard")


@dataclass(frozen=True, slots=True)
class ScheduledWorkflowSummary:
    """Сводная информация по одной scheduled job."""

    id: str
    name: str
    cron_expr: str
    timezone: str
    next_run_at: str | None
    last_run_at: str | None
    success_rate_7d: float
    status: str  # "enabled" | "paused"


class CronDashboardService:
    """Объединяет SchedulerManager + workflow_audit для page 14."""

    def __init__(self, clickhouse_client_factory: Any | None = None) -> None:
        self._ch_factory = clickhouse_client_factory

    async def _get_ch_client(self) -> Any | None:
        try:
            if self._ch_factory is not None:
                return await self._ch_factory()
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
            return await get_async_client(host=host, port=port, database=database)
        except Exception as _:
            return None

    async def list_scheduled(self) -> list[ScheduledWorkflowSummary]:
        """Список всех scheduled jobs + success_rate(7d) каждой."""
        from src.backend.core.scheduler import (
            get_scheduler_manager,
        )

        manager = get_scheduler_manager()
        jobs = manager.list_jobs()
        results: list[ScheduledWorkflowSummary] = []

        for job in jobs:
            success_rate = await self.get_success_rate(job["id"])
            trigger_str = job.get("trigger", "")
            cron_expr = ""
            timezone = "UTC"
            if "cron[" in trigger_str:
                cron_expr = trigger_str.split("cron[", 1)[1].rstrip("]")
            if "timezone=" in trigger_str:
                tz_part = trigger_str.split("timezone=", 1)[1]
                timezone = tz_part.split()[0].strip()

            status = "paused" if job.get("paused") else "enabled"

            results.append(
                ScheduledWorkflowSummary(
                    id=job["id"],
                    name=job["name"],
                    cron_expr=cron_expr,
                    timezone=timezone,
                    next_run_at=job.get("next_run_time"),
                    last_run_at=None,
                    success_rate_7d=success_rate,
                    status=status,
                )
            )
        return results

    async def get_success_rate(self, job_id: str, *, period_days: int = 7) -> float:
        """Возвращает success rate (%) за период из workflow_audit."""
        from datetime import datetime, timedelta

        client = await self._get_ch_client()
        if client is None:
            return 0.0

        cutoff = datetime.now(UTC) - timedelta(days=period_days)
        try:
            result = await client.query(
                "SELECT countIf(event_type='workflow.complete') * 100.0 / "
                "  greatest(count(), 1) FROM workflow_audit "
                "WHERE JSONExtractString(payload, 'job_id') = %(job_id)s "
                "  AND created_at >= %(cutoff)s "
                "  AND event_type IN ('workflow.complete', 'workflow.fail')",
                parameters={"job_id": job_id, "cutoff": cutoff},
            )
            row = (
                result.result_rows[0] if getattr(result, "result_rows", None) else None
            )
        except Exception as exc:
            _logger.warning("CH success_rate failed: %s", exc)
            return 0.0

        if row is None:
            return 0.0
        return float(row[0] or 0.0)
