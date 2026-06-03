"""Unit tests for src.backend.infrastructure.scheduler.dlq."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.infrastructure.scheduler.dlq import (
    SchedulerDLQEntry,
    SchedulerDLQStore,
    attach_scheduler_dlq,
    get_scheduler_dlq_store,
    set_scheduler_dlq_store,
)


class TestSchedulerDLQEntry:
    def test_init(self) -> None:
        now = datetime.now(timezone.utc)
        entry = SchedulerDLQEntry(
            job_id="job-1",
            exception="ValueError: boom",
            traceback_text="trace",
            scheduled_at=now,
            failed_at=now,
        )
        assert entry.job_id == "job-1"
        assert entry.exception == "ValueError: boom"
        assert entry.traceback_text == "trace"
        assert entry.scheduled_at is now
        assert entry.failed_at is now
        assert entry.retry_count == 0
        assert uuid.UUID(entry.id)  # valid uuid

    def test_mark_retried(self) -> None:
        entry = SchedulerDLQEntry(
            job_id="j",
            exception="e",
            traceback_text="t",
            scheduled_at=None,
            failed_at=datetime.now(timezone.utc),
        )
        entry.mark_retried()
        assert entry.retry_count == 1

    def test_to_dict(self) -> None:
        now = datetime.now(timezone.utc)
        entry = SchedulerDLQEntry(
            job_id="j",
            exception="e",
            traceback_text="t",
            scheduled_at=now,
            failed_at=now,
        )
        d = entry.to_dict()
        assert d["job_id"] == "j"
        assert d["exception"] == "e"
        assert d["traceback"] == "t"
        assert d["scheduled_at"] == now.isoformat()
        assert d["failed_at"] == now.isoformat()
        assert d["retry_count"] == 0
        assert "id" in d

    def test_to_dict_no_scheduled(self) -> None:
        now = datetime.now(timezone.utc)
        entry = SchedulerDLQEntry(
            job_id="j",
            exception="e",
            traceback_text="t",
            scheduled_at=None,
            failed_at=now,
        )
        d = entry.to_dict()
        assert d["scheduled_at"] is None


class TestSchedulerDLQStore:
    def test_capacity_validation(self) -> None:
        with pytest.raises(ValueError, match="capacity"):
            SchedulerDLQStore(capacity=0)

    def test_add_and_list(self) -> None:
        store = SchedulerDLQStore(capacity=3)
        e1 = SchedulerDLQEntry(job_id="a", exception="e", traceback_text="t", scheduled_at=None, failed_at=datetime.now(timezone.utc))
        e2 = SchedulerDLQEntry(job_id="b", exception="e", traceback_text="t", scheduled_at=None, failed_at=datetime.now(timezone.utc))
        store.add(e1)
        store.add(e2)
        assert store.size() == 2
        items = store.list()
        assert items[0].job_id == "b"
        assert items[1].job_id == "a"

    def test_capacity_eviction(self) -> None:
        store = SchedulerDLQStore(capacity=2)
        e1 = SchedulerDLQEntry(job_id="a", exception="e", traceback_text="t", scheduled_at=None, failed_at=datetime.now(timezone.utc))
        e2 = SchedulerDLQEntry(job_id="b", exception="e", traceback_text="t", scheduled_at=None, failed_at=datetime.now(timezone.utc))
        e3 = SchedulerDLQEntry(job_id="c", exception="e", traceback_text="t", scheduled_at=None, failed_at=datetime.now(timezone.utc))
        store.add(e1)
        store.add(e2)
        store.add(e3)
        assert store.size() == 2
        items = store.list()
        assert items[0].job_id == "c"
        assert items[1].job_id == "b"

    def test_list_limit(self) -> None:
        store = SchedulerDLQStore(capacity=5)
        for i in range(3):
            store.add(SchedulerDLQEntry(job_id=str(i), exception="e", traceback_text="t", scheduled_at=None, failed_at=datetime.now(timezone.utc)))
        assert len(store.list(limit=2)) == 2

    def test_get_and_delete(self) -> None:
        store = SchedulerDLQStore()
        e = SchedulerDLQEntry(job_id="a", exception="e", traceback_text="t", scheduled_at=None, failed_at=datetime.now(timezone.utc))
        store.add(e)
        assert store.get(e.id) is e
        assert store.delete(e.id) is True
        assert store.get(e.id) is None
        assert store.delete(e.id) is False

    def test_thread_safety(self) -> None:
        store = SchedulerDLQStore(capacity=100)
        errors = []

        def worker() -> None:
            try:
                for _ in range(50):
                    e = SchedulerDLQEntry(job_id="x", exception="e", traceback_text="t", scheduled_at=None, failed_at=datetime.now(timezone.utc))
                    store.add(e)
                    store.list(limit=10)
                    store.size()
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        assert store.size() == 100  # capped


class TestStoreSingleton:
    def test_get_set(self) -> None:
        set_scheduler_dlq_store(None)
        assert get_scheduler_dlq_store() is None
        store = SchedulerDLQStore()
        set_scheduler_dlq_store(store)
        assert get_scheduler_dlq_store() is store


@pytest.fixture(autouse=True)
def _reset_store() -> Iterator[None]:
    set_scheduler_dlq_store(None)
    yield
    set_scheduler_dlq_store(None)


class TestAttachSchedulerDLQ:
    def test_disabled_by_feature_flag(self) -> None:
        with patch("src.backend.infrastructure.scheduler.dlq.feature_flags") as ff:
            ff.scheduler_dlq_enabled = False
            scheduler = MagicMock()
            result = attach_scheduler_dlq(scheduler)
        assert result is None
        scheduler.add_listener.assert_not_called()

    def test_attach_with_store(self) -> None:
        scheduler = MagicMock()
        with patch("src.backend.infrastructure.scheduler.dlq.feature_flags") as ff:
            ff.scheduler_dlq_enabled = True
            with patch(
                "src.backend.infrastructure.scheduler.dlq.EVENT_JOB_ERROR",
                create=True,
            ):
                store = SchedulerDLQStore()
                result = attach_scheduler_dlq(scheduler, store=store)
        assert result is store
        scheduler.add_listener.assert_called_once()
        handler = scheduler.add_listener.call_args[0][0]
        assert callable(handler)

    def test_listener_event_with_exception(self) -> None:
        scheduler = MagicMock()
        with patch("src.backend.infrastructure.scheduler.dlq.feature_flags") as ff:
            ff.scheduler_dlq_enabled = True
            with patch(
                "src.backend.infrastructure.scheduler.dlq.EVENT_JOB_ERROR",
                create=True,
            ):
                store = SchedulerDLQStore()
                attach_scheduler_dlq(scheduler, store=store)
        handler = scheduler.add_listener.call_args[0][0]
        event = MagicMock()
        event.job_id = "job-1"
        event.exception = ValueError("boom")
        event.traceback = None
        event.scheduled_run_time = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        handler(event)
        assert store.size() == 1
        entry = store.list()[0]
        assert entry.job_id == "job-1"
        assert "ValueError" in entry.exception

    def test_listener_event_without_exception(self) -> None:
        scheduler = MagicMock()
        with patch("src.backend.infrastructure.scheduler.dlq.feature_flags") as ff:
            ff.scheduler_dlq_enabled = True
            with patch(
                "src.backend.infrastructure.scheduler.dlq.EVENT_JOB_ERROR",
                create=True,
            ):
                store = SchedulerDLQStore()
                attach_scheduler_dlq(scheduler, store=store)
        handler = scheduler.add_listener.call_args[0][0]
        event = MagicMock()
        event.job_id = "job-2"
        event.exception = None
        event.traceback = "some traceback"
        event.scheduled_run_time = None
        handler(event)
        assert store.size() == 1
        entry = store.list()[0]
        assert entry.job_id == "job-2"
        assert entry.exception == "Unknown"

    @pytest.mark.asyncio
    async def test_listener_with_writer_and_loop(self) -> None:
        scheduler = MagicMock()
        writer = MagicMock()
        writer.write = AsyncMock()
        with patch("src.backend.infrastructure.scheduler.dlq.feature_flags") as ff:
            ff.scheduler_dlq_enabled = True
            with patch(
                "src.backend.infrastructure.scheduler.dlq.EVENT_JOB_ERROR",
                create=True,
            ):
                with patch(
                    "src.backend.core.utils.task_registry.get_task_registry"
                ) as mock_get_tr:
                    tr = MagicMock()
                    mock_get_tr.return_value = tr
                    store = SchedulerDLQStore()
                    attach_scheduler_dlq(scheduler, store=store, writer=writer)
                    handler = scheduler.add_listener.call_args[0][0]
                    event = MagicMock()
                    event.job_id = "job-3"
                    event.exception = RuntimeError("fail")
                    event.traceback = None
                    event.scheduled_run_time = datetime.now(timezone.utc)
                    handler(event)
        assert store.size() == 1
        tr.create_task.assert_called_once()

    def test_listener_no_running_loop(self, caplog: pytest.LogCaptureFixture) -> None:
        scheduler = MagicMock()
        writer = MagicMock()
        with patch("src.backend.infrastructure.scheduler.dlq.feature_flags") as ff:
            ff.scheduler_dlq_enabled = True
            with patch(
                "src.backend.infrastructure.scheduler.dlq.EVENT_JOB_ERROR",
                create=True,
            ):
                store = SchedulerDLQStore()
                with caplog.at_level("WARNING"):
                    attach_scheduler_dlq(scheduler, store=store, writer=writer)
        handler = scheduler.add_listener.call_args[0][0]
        event = MagicMock()
        event.job_id = "job-4"
        event.exception = RuntimeError("fail")
        event.traceback = None
        event.scheduled_run_time = None
        # No running loop here
        handler(event)
        assert "no running loop" in caplog.text

    def test_listener_exception_in_handler(self, caplog: pytest.LogCaptureFixture) -> None:
        scheduler = MagicMock()
        with patch("src.backend.infrastructure.scheduler.dlq.feature_flags") as ff:
            ff.scheduler_dlq_enabled = True
            with patch(
                "src.backend.infrastructure.scheduler.dlq.EVENT_JOB_ERROR",
                create=True,
            ):
                store = SchedulerDLQStore()
                attach_scheduler_dlq(scheduler, store=store)
        handler = scheduler.add_listener.call_args[0][0]
        event = MagicMock()
        # Force getattr to blow up
        type(event).job_id = property(lambda self: (_ for _ in ()).throw(RuntimeError("kaboom")))
        with caplog.at_level("ERROR"):
            handler(event)
        assert "DLQ listener failed" in caplog.text
