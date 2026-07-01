"""Scheduler domain provider — S170 NEW (Milestone 1).

Single entry point для scheduler manager (APScheduler + DLQ + job queue).

Usage::

    from src.backend.core.di.providers.scheduler import get_scheduler_provider

    scheduler = get_scheduler_provider()
    scheduler.schedule_job(job_id, fn, cron="0 * * * *")
"""

from __future__ import annotations

from typing import Any

from src.backend.core.di.module_registry import resolve_module

_overrides: dict[str, Any] = {}


def get_scheduler_provider() -> Any:
    """Вернуть singleton SchedulerManager."""
    if "scheduler" in _overrides:
        return _overrides["scheduler"]
    return resolve_module("infrastructure.scheduler.scheduler_manager").get_default_scheduler()


def set_scheduler_provider(scheduler: Any) -> None:
    """Test-инжекция scheduler backend."""
    _overrides["scheduler"] = scheduler


__all__ = ("get_scheduler_provider", "set_scheduler_provider")
