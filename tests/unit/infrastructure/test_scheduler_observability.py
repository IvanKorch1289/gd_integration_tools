"""Тесты Prometheus observability для APScheduler (Sprint 16 Wave 5, M-9/CP-22)."""

# ruff: noqa: S101

from __future__ import annotations

import logging

import pytest

from src.backend.infrastructure.scheduler.observability import (
    attach_scheduler_metrics,
    report_jobstore_type,
)


def test_report_jobstore_type_memory_in_prod_logs_critical(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Memory jobstore в prod → CRITICAL лог."""
    with caplog.at_level(logging.CRITICAL):
        report_jobstore_type(is_memory=True, is_production=True)
    assert any(
        "scheduler.memory_jobstore_in_production" in r.message
        for r in caplog.records
    )


def test_report_jobstore_type_memory_in_dev_logs_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Memory jobstore в dev — только INFO, не CRITICAL."""
    with caplog.at_level(logging.INFO):
        report_jobstore_type(is_memory=True, is_production=False)
    critical = [r for r in caplog.records if r.levelno >= logging.CRITICAL]
    assert critical == []


def test_report_jobstore_type_sqlalchemy_in_prod_clean(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SQLAlchemy jobstore в prod не должен поднимать CRITICAL."""
    with caplog.at_level(logging.INFO):
        report_jobstore_type(is_memory=False, is_production=True)
    critical = [r for r in caplog.records if r.levelno >= logging.CRITICAL]
    assert critical == []


def test_attach_scheduler_metrics_attaches_four_listeners() -> None:
    """attach_scheduler_metrics регистрирует 4 listener'а (S17 K2 W4: +SUBMITTED)."""
    pytest.importorskip("apscheduler")
    from apscheduler.events import (
        EVENT_JOB_ERROR,
        EVENT_JOB_EXECUTED,
        EVENT_JOB_MISSED,
        EVENT_JOB_SUBMITTED,
    )
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler()
    baseline_listeners = list(scheduler._listeners)

    attach_scheduler_metrics(scheduler)

    new_listeners = [
        ln for ln in scheduler._listeners if ln not in baseline_listeners
    ]
    # APScheduler хранит listeners как (callback, mask) tuples.
    masks = {ln[1] for ln in new_listeners}
    assert EVENT_JOB_SUBMITTED in masks
    assert EVENT_JOB_EXECUTED in masks
    assert EVENT_JOB_ERROR in masks
    assert EVENT_JOB_MISSED in masks


def test_duration_metric_observed_on_executed() -> None:
    """Duration histogram записывает elapsed между submit и executed."""
    pytest.importorskip("apscheduler")
    pytest.importorskip("prometheus_client")
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from src.backend.infrastructure.scheduler import observability as obs

    scheduler = AsyncIOScheduler()
    attach_scheduler_metrics(scheduler)

    # Симулируем submit + executed события
    class _Event:
        def __init__(self, job_id: str) -> None:
            self.job_id = job_id

    submit_listener = None
    executed_listener = None
    from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_SUBMITTED

    for cb, mask in scheduler._listeners:
        if mask == EVENT_JOB_SUBMITTED:
            submit_listener = cb
        elif mask == EVENT_JOB_EXECUTED:
            executed_listener = cb
    assert submit_listener is not None and executed_listener is not None

    submit_listener(_Event("job-duration-test"))
    assert "job-duration-test" in obs._JOB_SUBMIT_TIMES
    executed_listener(_Event("job-duration-test"))
    # submit_time снят
    assert "job-duration-test" not in obs._JOB_SUBMIT_TIMES


def test_emit_handles_unknown_job_id_label() -> None:
    """job_id=None превращается в 'unknown' label."""
    from src.backend.infrastructure.scheduler.observability import _emit

    class _FakeCounter:
        def __init__(self) -> None:
            self.calls: list[dict[str, str]] = []

        def labels(self, **kwargs: str) -> "_FakeCounter":
            self.calls.append(kwargs)
            return self

        def inc(self) -> None:
            return None

    fake = _FakeCounter()
    _emit(fake, job_id="", status="success")
    assert fake.calls == [{"job_id": "unknown", "status": "success"}]
