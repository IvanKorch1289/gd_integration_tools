"""Sprint 21 W4 — Scheduler DLQ tests (G-09 closure).

Покрытие:
    * SchedulerDLQStore — add/list/get/delete/capacity.
    * attach_scheduler_dlq — feature-flag OFF = no-op.
    * SchedulerDLQEntry.mark_retried() — счётчик инкрементируется.
    * to_dict() — корректный сериализуемый формат.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.backend.infrastructure.scheduler.dlq import (
    SchedulerDLQEntry,
    SchedulerDLQStore,
    attach_scheduler_dlq,
    get_scheduler_dlq_store,
    set_scheduler_dlq_store,
)


@pytest.fixture(autouse=True)
def _reset_store() -> None:
    """Сбрасывает module-level singleton перед каждым тестом."""
    set_scheduler_dlq_store(None)
    yield
    set_scheduler_dlq_store(None)


def _make_entry(job_id: str = "test_job") -> SchedulerDLQEntry:
    return SchedulerDLQEntry(
        job_id=job_id,
        exception="ConnectionError('refused')",
        traceback_text="Traceback...",
        scheduled_at=datetime(2026, 5, 22, tzinfo=timezone.utc),
        failed_at=datetime.now(timezone.utc),
    )


def test_store_add_list_get_delete() -> None:
    store = SchedulerDLQStore()
    entry = _make_entry()
    store.add(entry)

    listed = store.list()
    assert len(listed) == 1
    assert listed[0].id == entry.id

    fetched = store.get(entry.id)
    assert fetched is entry

    assert store.delete(entry.id) is True
    assert store.get(entry.id) is None
    assert store.size() == 0


def test_store_capacity_evicts_oldest() -> None:
    store = SchedulerDLQStore(capacity=3)
    entries = [_make_entry(job_id=f"job_{i}") for i in range(5)]
    for e in entries:
        store.add(e)
    assert store.size() == 3
    listed_ids = [e.id for e in store.list()]
    # Самые новые (последние 3) — entries[2,3,4], сверху новейшие
    assert listed_ids == [entries[4].id, entries[3].id, entries[2].id]


def test_store_invalid_capacity() -> None:
    with pytest.raises(ValueError):
        SchedulerDLQStore(capacity=0)


def test_mark_retried_increments() -> None:
    entry = _make_entry()
    assert entry.retry_count == 0
    entry.mark_retried()
    entry.mark_retried()
    assert entry.retry_count == 2


def test_to_dict_serializable() -> None:
    entry = _make_entry(job_id="x")
    d = entry.to_dict()
    assert d["job_id"] == "x"
    assert "exception" in d
    assert "traceback" in d
    assert "scheduled_at" in d
    assert "failed_at" in d
    assert d["retry_count"] == 0


def test_attach_dlq_feature_flag_off_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При выключенном feature-flag attach_scheduler_dlq возвращает None."""
    from src.backend.core.config import features as features_module

    monkeypatch.setattr(
        features_module.feature_flags, "scheduler_dlq_enabled", False, raising=False
    )

    class _FakeScheduler:
        def add_listener(self, *a, **kw) -> None:
            raise AssertionError("attach должен быть no-op при OFF")

    assert attach_scheduler_dlq(_FakeScheduler()) is None
    assert get_scheduler_dlq_store() is None


def test_attach_dlq_feature_flag_on_creates_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При включённом feature-flag store создаётся + listener регистрируется."""
    from src.backend.core.config import features as features_module

    monkeypatch.setattr(
        features_module.feature_flags, "scheduler_dlq_enabled", True, raising=False
    )

    listeners: list = []

    class _FakeScheduler:
        def add_listener(self, fn, mask) -> None:
            listeners.append((fn, mask))

    result = attach_scheduler_dlq(_FakeScheduler())
    assert result is not None
    assert isinstance(result, SchedulerDLQStore)
    assert get_scheduler_dlq_store() is result
    assert len(listeners) == 1


def test_listener_writes_entry_to_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Listener fakes EVENT_JOB_ERROR → entry попадает в store."""
    from src.backend.core.config import features as features_module

    monkeypatch.setattr(
        features_module.feature_flags, "scheduler_dlq_enabled", True, raising=False
    )

    captured: list = []

    class _FakeScheduler:
        def add_listener(self, fn, mask) -> None:
            captured.append(fn)

    store = attach_scheduler_dlq(_FakeScheduler())
    assert store is not None
    handler = captured[0]

    class _FakeEvent:
        job_id = "fail_job"
        exception = ValueError("boom")
        traceback = None
        scheduled_run_time = datetime(2026, 5, 22, tzinfo=timezone.utc)

    handler(_FakeEvent())
    assert store.size() == 1
    entry = store.list()[0]
    assert entry.job_id == "fail_job"
    assert "ValueError" in entry.exception
