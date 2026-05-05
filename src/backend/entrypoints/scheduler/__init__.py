"""Scheduler entry-point для :class:`Invoker` (W22 этап B).

Содержит recurring-триггеры (cron / interval), которые на каждый tick
формируют :class:`InvocationRequest` и пробрасывают его в Invoker.
В отличие от :attr:`InvocationMode.DEFERRED` (однократный run_at),
здесь — повторяющийся триггер.
"""

from __future__ import annotations

from src.entrypoints.scheduler.invoker_schedule import (
    ScheduleSpec,
    register_scheduled_invocation,
    register_scheduled_invocations,
)

__all__ = (
    "ScheduleSpec",
    "register_scheduled_invocation",
    "register_scheduled_invocations",
)
