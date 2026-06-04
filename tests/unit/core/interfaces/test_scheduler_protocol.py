"""Unit-тесты Protocol :class:`SchedulerBackend` и его реализаций.

Wave ``[wave:s18/w0-goal-driven-sweep-8-scheduler-backend-protocol]``.
"""

# ruff: noqa: S101

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from src.backend.core.interfaces.scheduler import ScheduledJob, SchedulerBackend
from src.backend.infrastructure.scheduler.temporal_scheduler_backend import (
    TemporalSchedulerBackend,
)


class _FakeSchedulerManager:
    """Минимальный mock SchedulerManager для тестов APSchedulerBackend."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.cron_calls: list[dict[str, Any]] = []
        self.removed: list[str] = []
        self.scheduler = _FakeAPS()
        self._jobs: list[dict[str, Any]] = []

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    def schedule_cron(
        self,
        *,
        name: str,
        cron_expr: str,
        callable_ref: Any,
        timezone: str = "Europe/Moscow",
        replace_existing: bool = True,
    ) -> str:
        self.cron_calls.append(
            {
                "name": name,
                "cron_expr": cron_expr,
                "timezone": timezone,
                "replace_existing": replace_existing,
            }
        )
        return name

    def list_jobs(self) -> list[dict[str, Any]]:
        return list(self._jobs)


class _FakeAPS:
    """Минимальный mock AsyncIOScheduler для add_job/remove_job."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.removed: list[str] = []

    def add_job(self, **kwargs: Any) -> Any:
        self.added.append(kwargs)
        return type("_Job", (), {"id": kwargs.get("id", "j1")})()

    def remove_job(self, job_id: str) -> None:
        self.removed.append(job_id)


def test_scheduled_job_to_dict() -> None:
    """ScheduledJob.to_dict() возвращает все 5 полей."""
    job = ScheduledJob(
        id="j1",
        name="weekly",
        next_run_time="2026-05-26T00:00:00",
        trigger="cron[*/5 * * * *]",
        paused=False,
    )
    assert job.to_dict() == {
        "id": "j1",
        "name": "weekly",
        "next_run_time": "2026-05-26T00:00:00",
        "trigger": "cron[*/5 * * * *]",
        "paused": False,
    }


def test_apscheduler_backend_implements_protocol() -> None:
    """APSchedulerBackend структурно соответствует SchedulerBackend Protocol."""
    from src.backend.infrastructure.scheduler.apscheduler_backend import (
        APSchedulerBackend,
    )

    backend = APSchedulerBackend(manager=_FakeSchedulerManager())
    assert isinstance(backend, SchedulerBackend)


@pytest.mark.asyncio
async def test_apscheduler_backend_delegates_start_stop() -> None:
    """start/stop делегируют SchedulerManager."""
    from src.backend.infrastructure.scheduler.apscheduler_backend import (
        APSchedulerBackend,
    )

    manager = _FakeSchedulerManager()
    backend = APSchedulerBackend(manager=manager)

    await backend.start()
    await backend.stop()
    assert manager.started is True
    assert manager.stopped is True


def test_apscheduler_backend_schedule_cron_delegates() -> None:
    """schedule_cron делегируется manager.schedule_cron()."""
    from src.backend.infrastructure.scheduler.apscheduler_backend import (
        APSchedulerBackend,
    )

    manager = _FakeSchedulerManager()
    backend = APSchedulerBackend(manager=manager)
    job_id = backend.schedule_cron("weekly", "0 9 * * 1", lambda: None)
    assert job_id == "weekly"
    assert manager.cron_calls[0]["name"] == "weekly"
    assert manager.cron_calls[0]["cron_expr"] == "0 9 * * 1"


def test_apscheduler_backend_cancel_returns_false_on_error() -> None:
    """cancel() возвращает False при отсутствии job (RemoveJob raises)."""
    from src.backend.infrastructure.scheduler.apscheduler_backend import (
        APSchedulerBackend,
    )

    manager = _FakeSchedulerManager()

    def _raise(_: str) -> None:
        raise LookupError("not found")

    manager.scheduler.remove_job = _raise
    backend = APSchedulerBackend(manager=manager)
    assert backend.cancel("absent") is False


def test_apscheduler_backend_cancel_returns_true_on_success() -> None:
    """cancel() возвращает True если manager.remove_job сработал."""
    from src.backend.infrastructure.scheduler.apscheduler_backend import (
        APSchedulerBackend,
    )

    manager = _FakeSchedulerManager()
    backend = APSchedulerBackend(manager=manager)
    assert backend.cancel("j1") is True
    assert manager.scheduler.removed == ["j1"]


def test_temporal_backend_implements_protocol() -> None:
    """TemporalSchedulerBackend stub структурно соответствует Protocol."""
    backend = TemporalSchedulerBackend()
    assert isinstance(backend, SchedulerBackend)


@pytest.mark.asyncio
async def test_temporal_backend_start_raises() -> None:
    """Stub start() бросает NotImplementedError с прозрачным сообщением."""
    backend = TemporalSchedulerBackend()
    with pytest.raises(NotImplementedError, match="stub"):
        await backend.start()


def test_temporal_backend_schedule_cron_raises() -> None:
    """Stub schedule_cron() бросает NotImplementedError."""
    backend = TemporalSchedulerBackend()
    with pytest.raises(NotImplementedError):
        backend.schedule_cron("any", "* * * * *", lambda: None)


def test_temporal_backend_schedule_oneshot_raises() -> None:
    """Stub schedule_oneshot() бросает NotImplementedError."""
    backend = TemporalSchedulerBackend()
    with pytest.raises(NotImplementedError):
        backend.schedule_oneshot("x", datetime.now(tz=timezone.utc), lambda: None)


def test_feature_flag_default_apscheduler() -> None:
    """feature_flags.scheduler_backend по умолчанию 'apscheduler'."""
    from src.backend.core.config.features import feature_flags

    assert feature_flags.scheduler_backend == "apscheduler"
