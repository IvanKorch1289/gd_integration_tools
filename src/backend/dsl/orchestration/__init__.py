"""Orchestration: Sensor / Backfill / Dry-run / HITL (C3).

Scaffold для операционных примитивов оркестрации DSL-маршрутов:

* `Sensor` — периодическая проверка условия, запуск route при
  выполнении.
* `Backfill` — перепрогон route за исторический диапазон дат.
* `DryRun` — исполнение route без side-effects (read-only + log).
* `HumanApproval` — пауза pipeline до явного approve через API/Streamlit.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Awaitable, Callable

__all__ = ("Sensor", "Backfill", "DryRun", "HumanApproval")


@dataclass(slots=True)
class Sensor:
    """Периодический sensor для triggering route.

    Args:
        name: Имя (для логов).
        predicate: Корутина, возвращающая True для запуска.
        interval_seconds: Интервал между проверками.
        route_id: Route, который запускается при True.
    """

    name: str
    predicate: Callable[[], Awaitable[bool]]
    interval_seconds: float
    route_id: str
    _task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        from src.backend.dsl.service import get_dsl_service

        async def _loop() -> None:
            while True:
                try:
                    if await self.predicate():
                        await get_dsl_service().dispatch(
                            route_id=self.route_id, body={}, headers={}
                        )
                except Exception:
                    import logging

                    logging.getLogger("dsl.sensor").exception(
                        "Sensor '%s' failed", self.name
                    )
                await asyncio.sleep(self.interval_seconds)

        self._task = asyncio.create_task(_loop(), name=f"sensor:{self.name}")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None


@dataclass(slots=True)
class Backfill:
    """Backfill window — прогон route за диапазон дат."""

    route_id: str
    start_date: date
    end_date: date
    step_days: int = 1

    async def run(self, payload_for_day: Callable[[date], dict[str, Any]]) -> list[Any]:
        from src.backend.dsl.service import get_dsl_service

        dsl = get_dsl_service()
        results: list[Any] = []
        current = self.start_date
        while current <= self.end_date:
            payload = payload_for_day(current)
            results.append(
                await dsl.dispatch(
                    route_id=self.route_id, body=payload, headers={"x-backfill": "1"}
                )
            )
            current = current.fromordinal(current.toordinal() + self.step_days)
        return results


@dataclass(slots=True)
class DryRun:
    """Dry-run — исполнение route с флагом `_dry_run: True`; все
    сторонние side-effect-процессоры должны учитывать этот флаг."""

    route_id: str

    async def run(self, payload: dict[str, Any]) -> Any:
        from src.backend.dsl.service import get_dsl_service

        return await get_dsl_service().dispatch(
            route_id=self.route_id, body=payload, headers={"x-dry-run": "1"}
        )


@dataclass(slots=True)
class HumanApproval:
    """Human-in-the-loop: пауза pipeline до approve."""

    approval_id: str
    approvers: list[str]
    approved: asyncio.Event = field(default_factory=asyncio.Event)
    decision: str = "pending"  # pending / approved / rejected
    decided_at: datetime | None = None

    async def wait(self, timeout: float | None = None) -> str:
        if timeout is not None:
            try:
                await asyncio.wait_for(self.approved.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                self.decision = "rejected_timeout"
                return self.decision
        else:
            await self.approved.wait()
        return self.decision

    def approve(self) -> None:
        self.decision = "approved"
        self.decided_at = datetime.utcnow()
        self.approved.set()

    def reject(self) -> None:
        self.decision = "rejected"
        self.decided_at = datetime.utcnow()
        self.approved.set()
