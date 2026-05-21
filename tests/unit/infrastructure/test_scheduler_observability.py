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


def test_attach_scheduler_metrics_attaches_three_listeners() -> None:
    """attach_scheduler_metrics регистрирует 3 listener'а на job events."""
    pytest.importorskip("apscheduler")
    from apscheduler.events import (
        EVENT_JOB_ERROR,
        EVENT_JOB_EXECUTED,
        EVENT_JOB_MISSED,
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
    assert EVENT_JOB_EXECUTED in masks
    assert EVENT_JOB_ERROR in masks
    assert EVENT_JOB_MISSED in masks


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
