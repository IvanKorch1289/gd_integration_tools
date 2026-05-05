"""Scheduled Reports Service — cron → action → export → deliver.

Планирование отчётов: выполнить action, экспортировать результат
в CSV/Excel/PDF и отправить через NotificationHub.

Actions: reports.schedule, reports.list, reports.run_now, reports.history
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from src.backend.core.di.app_state import app_state_singleton

__all__ = ("ScheduledReportsService", "ReportSchedule", "get_reports_service")

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ReportSchedule:
    """Описание запланированного отчёта."""

    id: str = field(default_factory=lambda: uuid4().hex[:12])
    name: str = ""
    action: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    cron: str = "0 9 * * MON"
    export_format: str = "csv"
    delivery_channel: str = "email"
    delivery_to: str = ""
    enabled: bool = True
    last_run: float = 0
    last_status: str = ""


@dataclass(slots=True)
class ReportRun:
    report_id: str
    timestamp: float = field(default_factory=time.time)
    status: str = "pending"
    rows: int = 0
    error: str | None = None
    duration_ms: float = 0


class ScheduledReportsService:
    """Управление запланированными отчётами."""

    def __init__(self) -> None:
        self._schedules: dict[str, ReportSchedule] = {}
        self._history: list[ReportRun] = []

    async def schedule(
        self,
        name: str,
        action: str,
        cron: str = "0 9 * * MON",
        export_format: str = "csv",
        delivery_channel: str = "email",
        delivery_to: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Создаёт или обновляет расписание отчёта."""
        report = ReportSchedule(
            name=name,
            action=action,
            cron=cron,
            export_format=export_format,
            delivery_channel=delivery_channel,
            delivery_to=delivery_to,
            payload=payload or {},
        )
        self._schedules[report.id] = report
        logger.info("Report scheduled: %s (%s)", name, cron)
        return {
            "status": "scheduled",
            "id": report.id,
            "name": name,
            "cron": cron,
            "action": action,
        }

    async def list_reports(self) -> dict[str, Any]:
        """Список всех отчётов."""
        return {
            "reports": [
                {
                    "id": r.id,
                    "name": r.name,
                    "action": r.action,
                    "cron": r.cron,
                    "format": r.export_format,
                    "channel": r.delivery_channel,
                    "to": r.delivery_to,
                    "enabled": r.enabled,
                    "last_run": r.last_run,
                    "last_status": r.last_status,
                }
                for r in self._schedules.values()
            ]
        }

    async def run_now(self, report_id: str) -> dict[str, Any]:
        """Выполняет отчёт немедленно."""
        report = self._schedules.get(report_id)
        if not report:
            return {"status": "not_found", "id": report_id}

        run = ReportRun(report_id=report_id)
        start = time.monotonic()

        try:
            from src.backend.dsl.commands.registry import action_handler_registry
            from src.backend.schemas.invocation import ActionCommandSchema

            command = ActionCommandSchema(
                action=report.action,
                payload=report.payload,
                meta={"source": f"report:{report.name}"},
            )
            result = await action_handler_registry.dispatch(command)

            data = (
                result
                if isinstance(result, list)
                else [result]
                if isinstance(result, dict)
                else []
            )
            run.rows = len(data)

            export_result = None
            if data and report.export_format != "none":
                from src.backend.services.io.export_service import get_export_service

                export_svc = get_export_service()
                export_method = getattr(
                    export_svc, f"to_{report.export_format}", export_svc.to_csv
                )
                export_result = await export_method(data=data, title=report.name)

            if report.delivery_to and export_result:
                from src.backend.services.ops.notification_hub import (
                    get_notification_hub,
                )

                hub = get_notification_hub()
                await hub.send(
                    channel=report.delivery_channel,
                    to=report.delivery_to,
                    subject=f"Отчёт: {report.name}",
                    message=f"Отчёт содержит {run.rows} записей.",
                )

            run.status = "success"
            run.duration_ms = (time.monotonic() - start) * 1000
            report.last_run = time.time()
            report.last_status = "success"

        except Exception as exc:
            run.status = "error"
            run.error = str(exc)
            run.duration_ms = (time.monotonic() - start) * 1000
            report.last_status = f"error: {exc}"
            logger.error("Report %s failed: %s", report.name, exc)

        self._history.append(run)
        return {
            "status": run.status,
            "id": report_id,
            "name": report.name,
            "rows": run.rows,
            "duration_ms": run.duration_ms,
            "error": run.error,
        }

    async def history(
        self, report_id: str | None = None, limit: int = 50
    ) -> dict[str, Any]:
        """История выполнения отчётов."""
        runs = self._history
        if report_id:
            runs = [r for r in runs if r.report_id == report_id]
        runs = runs[-limit:]
        return {
            "runs": [
                {
                    "report_id": r.report_id,
                    "status": r.status,
                    "rows": r.rows,
                    "duration_ms": r.duration_ms,
                    "error": r.error,
                    "timestamp": r.timestamp,
                }
                for r in runs
            ]
        }


@app_state_singleton("reports_service", factory=ScheduledReportsService)
def get_reports_service() -> ScheduledReportsService:
    raise NotImplementedError  # заменяется декоратором
