"""Тесты SchedulerManager (T3 ratchet: infrastructure/scheduler_manager 25%→).

Memory-mode (sync_engine=None): schedule_cron регистрирует job, pause/resume/
run_job_now возвращают True/False по наличию, cleanup-реестр работает.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from types import SimpleNamespace

from src.backend.infrastructure.scheduler.scheduler_manager import SchedulerManager


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch) -> SchedulerManager:
    """Memory-mode менеджер: sync_engine отсутствует (dev_light)."""
    fake_scheduler_settings = SimpleNamespace(
        timezone="UTC",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=60,
        default_jobstore_name="default",
        backup_jobstore_name="backup",
        executors={"default": {"type": "asyncio"}},
    )
    fake_database = SimpleNamespace(db_initializer=SimpleNamespace(sync_engine=None))
    monkeypatch.setattr(
        "src.backend.infrastructure.scheduler.scheduler_manager.settings",
        SimpleNamespace(scheduler=fake_scheduler_settings, database=fake_database),
    )
    monkeypatch.setattr(
        "src.backend.infrastructure.database.database.db_initializer",
        SimpleNamespace(sync_engine=None),
    )
    return SchedulerManager()


def test_schedule_cron_registers_and_returns_name(manager: SchedulerManager) -> None:
    job_id = manager.schedule_cron(
        name="nightly", cron_expr="0 9 * * MON", callable_ref=lambda: None,
    )
    assert job_id == "nightly"
    jobs = manager.list_jobs()
    assert any(j["id"] == "nightly" for j in jobs)


def test_schedule_cron_invalid_cron_raises(manager: SchedulerManager) -> None:
    with pytest.raises(ValueError):
        manager.schedule_cron(
            name="bad", cron_expr="not a cron", callable_ref=lambda: None,
        )


def test_pause_resume_round_trip(manager: SchedulerManager) -> None:
    manager.schedule_cron(name="j1", cron_expr="*/5 * * * *", callable_ref=lambda: None)

    assert manager.pause_job("j1") is True
    job = next(j for j in manager.list_jobs() if j["id"] == "j1")
    assert job["next_run_time"] is None  # приостановлена

    assert manager.resume_job("j1") is True
    job = next(j for j in manager.list_jobs() if j["id"] == "j1")
    assert job["next_run_time"] is not None


def test_pause_resume_missing_returns_false(manager: SchedulerManager) -> None:
    assert manager.pause_job("absent") is False
    assert manager.resume_job("absent") is False


def test_run_job_now_missing_returns_false(manager: SchedulerManager) -> None:
    assert manager.run_job_now("absent") is False


def test_list_jobs_empty(manager: SchedulerManager) -> None:
    assert manager.list_jobs() == []


def test_cleanup_registry_round_trip(manager: SchedulerManager) -> None:
    """register/unregister_job_cleanup — контракт реестра очистки."""
    manager.register_job_cleanup("my_job")
    manager.unregister_job_cleanup("my_job")
    # повторная регистрация/снятие — не бросают


def test_default_jobstore_is_memory_without_sync_engine(manager: SchedulerManager) -> None:
    """Без sync_engine default-jobstore — MemoryJobStore (durable off)."""
    assert manager._default_jobstore_is_memory is True
