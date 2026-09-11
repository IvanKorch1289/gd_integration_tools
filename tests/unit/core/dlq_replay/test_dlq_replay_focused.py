"""Focused tests for ``core.dlq_replay`` (Wave 1 P0 #4 + #5 baseline)."""

from __future__ import annotations

import asyncio

import pytest

from src.backend.core.dlq_replay import (
    DLQReplayService,
    FailureClass,
    FailureTaxonomy,
    InMemoryDLQStore,
    classify_exception,
    get_dlq_replay,
)
from src.backend.core.dlq_replay.cockpit import (
    ReplayCockpit,
    reset_dlq_replay,
)
from src.backend.core.dlq_replay.store.base import DLQRecord


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_dlq_replay()


class TestFailureClassEnum:
    def test_values(self) -> None:
        assert FailureClass.RETRYABLE.value == "retryable"
        assert FailureClass.POISON.value == "poison"
        assert FailureClass.BUSINESS.value == "business"
        assert FailureClass.SECURITY.value == "security"
        assert FailureClass.SYSTEM.value == "system"

    def test_count(self) -> None:
        assert len(FailureClass) == 5


class TestFailureTaxonomy:
    """``FailureTaxonomy.classify()`` — exception classification."""

    def test_retryable_timeout(self) -> None:
        tx = FailureTaxonomy()
        assert tx.classify(TimeoutError()) == FailureClass.RETRYABLE
        assert tx.classify(ConnectionError()) == FailureClass.RETRYABLE
        assert tx.classify(OSError()) == FailureClass.RETRYABLE

    def test_poison_validation(self) -> None:
        tx = FailureTaxonomy()
        assert tx.classify(ValueError()) == FailureClass.POISON
        assert tx.classify(KeyError()) == FailureClass.POISON
        assert tx.classify(TypeError()) == FailureClass.POISON

    def test_security_auth(self) -> None:
        tx = FailureTaxonomy()
        assert tx.classify(PermissionError()) == FailureClass.SECURITY

    def test_business_400_status(self) -> None:
        """Exception со ``status_code=400`` → BUSINESS."""
        tx = FailureTaxonomy()

        class CustomError(Exception):
            status_code = 400

        assert tx.classify(CustomError()) == FailureClass.BUSINESS

    def test_security_401_403_status(self) -> None:
        tx = FailureTaxonomy()

        class E401(Exception):
            status_code = 401

        class E403(Exception):
            status_code = 403

        assert tx.classify(E401()) == FailureClass.SECURITY
        assert tx.classify(E403()) == FailureClass.SECURITY

    def test_retryable_5xx_status(self) -> None:
        tx = FailureTaxonomy()

        class E500(Exception):
            status_code = 500

        class E429(Exception):
            status_code = 429

        assert tx.classify(E500()) == FailureClass.RETRYABLE
        assert tx.classify(E429()) == FailureClass.RETRYABLE

    def test_unknown_default_system(self) -> None:
        """Unknown exception → SYSTEM."""
        tx = FailureTaxonomy()

        class WeirdError(Exception):
            pass

        assert tx.classify(WeirdError()) == FailureClass.SYSTEM

    def test_custom_rule(self) -> None:
        """``add_rule(type_name, failure_class)``."""
        tx = FailureTaxonomy()
        tx.add_rule("MyError", FailureClass.POISON)

        class MyError(Exception):
            pass

        assert tx.classify(MyError()) == FailureClass.POISON

    def test_classify_exception_helper(self) -> None:
        """``classify_exception`` convenience function."""
        assert classify_exception(TimeoutError()) == FailureClass.RETRYABLE


class TestInMemoryDLQStoreInit:
    def test_init_empty(self) -> None:
        s = InMemoryDLQStore()
        assert s.size() == 0


class TestInMemoryDLQStoreCRUD:
    async def test_add_and_get(self) -> None:
        s = InMemoryDLQStore()
        rec = DLQRecord(
            record_id="r1",
            consumer_id="c1",
            topic="t1",
            message={"x": 1},
            error="boom",
            failure_class=FailureClass.POISON,
        )
        await s.add(rec)
        fetched = await s.get("r1")
        assert fetched is rec

    async def test_get_missing(self) -> None:
        s = InMemoryDLQStore()
        assert await s.get("missing") is None

    async def test_list_all(self) -> None:
        s = InMemoryDLQStore()
        for i in range(3):
            await s.add(
                DLQRecord(
                    record_id=f"r{i}",
                    consumer_id="c1",
                    topic="t1",
                    message={},
                    error="",
                    failure_class=FailureClass.POISON,
                )
            )
        records = await s.list()
        assert len(records) == 3

    async def test_list_filter_consumer(self) -> None:
        s = InMemoryDLQStore()
        await s.add(
            DLQRecord(
                record_id="r1",
                consumer_id="c1",
                topic="t1",
                message={},
                error="",
                failure_class=FailureClass.POISON,
            )
        )
        await s.add(
            DLQRecord(
                record_id="r2",
                consumer_id="c2",
                topic="t1",
                message={},
                error="",
                failure_class=FailureClass.POISON,
            )
        )
        records = await s.list(consumer_id="c1")
        assert len(records) == 1
        assert records[0].record_id == "r1"

    async def test_list_filter_failure_class(self) -> None:
        s = InMemoryDLQStore()
        await s.add(
            DLQRecord(
                record_id="r1",
                consumer_id="c1",
                topic="t1",
                message={},
                error="",
                failure_class=FailureClass.POISON,
            )
        )
        await s.add(
            DLQRecord(
                record_id="r2",
                consumer_id="c1",
                topic="t1",
                message={},
                error="",
                failure_class=FailureClass.RETRYABLE,
            )
        )
        records = await s.list(failure_class=FailureClass.POISON)
        assert len(records) == 1

    async def test_list_filter_replayed(self) -> None:
        s = InMemoryDLQStore()
        await s.add(
            DLQRecord(
                record_id="r1",
                consumer_id="c1",
                topic="t1",
                message={},
                error="",
                failure_class=FailureClass.POISON,
            )
        )
        await s.add(
            DLQRecord(
                record_id="r2",
                consumer_id="c1",
                topic="t1",
                message={},
                error="",
                failure_class=FailureClass.POISON,
            )
        )
        await s.mark_replayed("r1", "alice")

        pending = await s.list(replayed=False)
        replayed = await s.list(replayed=True)
        assert len(pending) == 1
        assert len(replayed) == 1

    async def test_mark_replayed(self) -> None:
        s = InMemoryDLQStore()
        await s.add(
            DLQRecord(
                record_id="r1",
                consumer_id="c1",
                topic="t1",
                message={},
                error="",
                failure_class=FailureClass.POISON,
            )
        )
        await s.mark_replayed("r1", "alice")
        rec = await s.get("r1")
        assert rec.replayed_at is not None
        assert rec.replayed_by == "alice"


class TestDLQReplayServiceInit:
    def test_init_default(self) -> None:
        svc = DLQReplayService(store=InMemoryDLQStore())
        assert svc.store is not None
        assert svc.taxonomy is not None

    def test_init_with_taxonomy(self) -> None:
        tx = FailureTaxonomy()
        svc = DLQReplayService(store=InMemoryDLQStore(), taxonomy=tx)
        assert svc.taxonomy is tx


class TestSendToDLQ:
    async def test_send_to_dlq_creates_record(self) -> None:
        svc = DLQReplayService(store=InMemoryDLQStore())
        rec = await svc.send_to_dlq(
            message={"x": 1},
            error=ValueError("boom"),
            consumer_id="c1",
            topic="t1",
        )
        assert rec.record_id  # UUID
        assert rec.consumer_id == "c1"
        assert rec.topic == "t1"
        assert rec.message == {"x": 1}
        assert rec.error == "boom"
        assert rec.failure_class == FailureClass.POISON
        assert rec.attempts == 1
        assert rec.replayed_at is None

    async def test_send_to_dlq_attempts(self) -> None:
        svc = DLQReplayService(store=InMemoryDLQStore())
        rec = await svc.send_to_dlq(
            message={},
            error=ValueError(),
            consumer_id="c1",
            topic="t1",
            attempts=5,
        )
        assert rec.attempts == 5

    async def test_send_to_dlq_with_metadata(self) -> None:
        svc = DLQReplayService(store=InMemoryDLQStore())
        rec = await svc.send_to_dlq(
            message={},
            error=ValueError(),
            consumer_id="c1",
            topic="t1",
            metadata={"trace_id": "abc"},
        )
        assert rec.metadata == {"trace_id": "abc"}

    async def test_send_to_dlq_classifies_failure(self) -> None:
        """Failure class определяется по error type."""
        svc = DLQReplayService(store=InMemoryDLQStore())
        rec = await svc.send_to_dlq(
            message={},
            error=TimeoutError(),
            consumer_id="c1",
            topic="t1",
        )
        assert rec.failure_class == FailureClass.RETRYABLE


class TestListDLQ:
    async def test_list_all(self) -> None:
        svc = DLQReplayService(store=InMemoryDLQStore())
        await svc.send_to_dlq(message={}, error=ValueError(), consumer_id="c1", topic="t1")
        records = await svc.list_dlq()
        assert len(records) == 1

    async def test_list_with_filters(self) -> None:
        svc = DLQReplayService(store=InMemoryDLQStore())
        await svc.send_to_dlq(message={}, error=ValueError(), consumer_id="c1", topic="t1")
        await svc.send_to_dlq(message={}, error=TimeoutError(), consumer_id="c2", topic="t2")

        c1 = await svc.list_dlq(consumer_id="c1")
        assert len(c1) == 1

        retryable = await svc.list_dlq(failure_class=FailureClass.RETRYABLE)
        assert len(retryable) == 1


class TestReplay:
    async def test_replay_success(self) -> None:
        svc = DLQReplayService(store=InMemoryDLQStore())
        rec = await svc.send_to_dlq(
            message={"x": 1}, error=ValueError(), consumer_id="c1", topic="t1"
        )
        replayed = []

        async def replay_fn(r):
            replayed.append(r)
            return True

        success = await svc.replay(
            record_id=rec.record_id, operator="alice", replay_fn=replay_fn
        )
        assert success is True
        assert len(replayed) == 1
        # Mark as replayed.
        updated = await svc.store.get(rec.record_id)
        assert updated.replayed_at is not None
        assert updated.replayed_by == "alice"

    async def test_replay_already_replayed(self) -> None:
        svc = DLQReplayService(store=InMemoryDLQStore())
        rec = await svc.send_to_dlq(
            message={}, error=ValueError(), consumer_id="c1", topic="t1"
        )

        async def replay_fn(r):
            return True

        await svc.replay(record_id=rec.record_id, operator="alice", replay_fn=replay_fn)
        # Second replay — should fail.
        success = await svc.replay(
            record_id=rec.record_id, operator="bob", replay_fn=replay_fn
        )
        assert success is False

    async def test_replay_not_found(self) -> None:
        svc = DLQReplayService(store=InMemoryDLQStore())

        async def replay_fn(r):
            return True

        success = await svc.replay(
            record_id="missing", operator="alice", replay_fn=replay_fn
        )
        assert success is False

    async def test_replay_callback_failure(self) -> None:
        """replay_fn raised → success=False."""
        svc = DLQReplayService(store=InMemoryDLQStore())
        rec = await svc.send_to_dlq(
            message={}, error=ValueError(), consumer_id="c1", topic="t1"
        )

        async def failing_fn(r):
            raise RuntimeError("downstream failure")

        success = await svc.replay(
            record_id=rec.record_id, operator="alice", replay_fn=failing_fn
        )
        assert success is False
        # Record NOT marked as replayed.
        updated = await svc.store.get(rec.record_id)
        assert updated.replayed_at is None

    async def test_replay_callback_returns_false(self) -> None:
        """replay_fn returns False → not marked."""
        svc = DLQReplayService(store=InMemoryDLQStore())
        rec = await svc.send_to_dlq(
            message={}, error=ValueError(), consumer_id="c1", topic="t1"
        )

        async def false_fn(r):
            return False

        success = await svc.replay(
            record_id=rec.record_id, operator="alice", replay_fn=false_fn
        )
        assert success is False


class TestClassifyFailure:
    def test_classify_failure_public(self) -> None:
        svc = DLQReplayService(store=InMemoryDLQStore())
        assert svc.classify_failure(ValueError()) == FailureClass.POISON
        assert svc.classify_failure(TimeoutError()) == FailureClass.RETRYABLE


class TestSingleton:
    def test_singleton(self) -> None:
        s1 = get_dlq_replay()
        s2 = get_dlq_replay()
        assert s1 is s2

    def test_reset(self) -> None:
        s1 = get_dlq_replay()
        reset_dlq_replay()
        s2 = get_dlq_replay()
        assert s1 is not s2

    def test_default_store_is_in_memory(self) -> None:
        svc = get_dlq_replay()
        assert isinstance(svc.store, InMemoryDLQStore)

    def test_replay_cockpit_alias(self) -> None:
        """ReplayCockpit = DLQReplayService."""
        assert ReplayCockpit is DLQReplayService


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import dlq_replay

        assert len(dlq_replay.__all__) == 9

    def test_store_all(self) -> None:
        from src.backend.core.dlq_replay import store

        assert len(store.__all__) == 2
