"""Focused tests for ``core.outbox_verify`` (Wave 1 P0 #3)."""

from __future__ import annotations

import asyncio

import pytest

from src.backend.core.outbox_verify import (
    InMemoryOutboxVerifyStore,
    OutboxPublishService,
    get_outbox_publish_service,
)
from src.backend.core.outbox_verify.service import (
    OutboxPublishOutcome,
    OutboxPublishResult,
    reset_outbox_publish_service,
)
from src.backend.core.outbox_verify.store.base import (
    OutboxPublishEntry,
    OutboxPublishState,
    OutboxPublishStore,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    reset_outbox_publish_service()


class TestOutboxPublishEntry:
    """``OutboxPublishEntry`` — dataclass basics."""

    def test_init_defaults(self) -> None:
        e = OutboxPublishEntry(
            event_id="e1", state=OutboxPublishState.PENDING
        )
        assert e.event_id == "e1"
        assert e.state == OutboxPublishState.PENDING
        assert e.broker is None
        assert e.broker_offset is None
        assert e.attempts == 0
        assert e.last_error is None
        assert e.created_at == 0.0
        assert e.delivered_at is None

    def test_init_with_all(self) -> None:
        e = OutboxPublishEntry(
            event_id="e1",
            state=OutboxPublishState.DELIVERED,
            broker="kafka",
            broker_offset="123",
            attempts=2,
            last_error="prev",
            created_at=100.0,
            delivered_at=200.0,
            metadata={"trace": "abc"},
        )
        assert e.broker == "kafka"
        assert e.broker_offset == "123"
        assert e.attempts == 2
        assert e.delivered_at == 200.0
        assert e.metadata == {"trace": "abc"}


class TestOutboxPublishStateEnum:
    def test_values(self) -> None:
        assert OutboxPublishState.PENDING.value == "pending"
        assert OutboxPublishState.PUBLISHING.value == "publishing"
        assert OutboxPublishState.DELIVERED.value == "delivered"
        assert OutboxPublishState.FAILED.value == "failed"

    def test_count(self) -> None:
        assert len(OutboxPublishState) == 4


class TestOutboxPublishOutcomeEnum:
    def test_values(self) -> None:
        assert OutboxPublishOutcome.ACQUIRED.value == "acquired"
        assert OutboxPublishOutcome.DUPLICATE.value == "duplicate"
        assert OutboxPublishOutcome.IN_PROGRESS.value == "in_progress"
        assert OutboxPublishOutcome.FAILED.value == "failed"

    def test_count(self) -> None:
        assert len(OutboxPublishOutcome) == 4


class TestInMemoryStoreInit:
    def test_init_empty(self) -> None:
        s = InMemoryOutboxVerifyStore()
        assert s.size() == 0


class TestInMemoryBegin:
    async def test_first_begin_pending(self) -> None:
        s = InMemoryOutboxVerifyStore()
        state, entry = await s.begin("e1")
        assert state == OutboxPublishState.PENDING
        assert entry is None

    async def test_second_begin_publishing(self) -> None:
        s = InMemoryOutboxVerifyStore()
        await s.begin("e1")
        state, entry = await s.begin("e1")
        assert state == OutboxPublishState.PUBLISHING
        assert entry is not None

    async def test_begin_after_delivered(self) -> None:
        s = InMemoryOutboxVerifyStore()
        await s.begin("e1")
        await s.confirm("e1", "kafka", "off1")
        state, entry = await s.begin("e1")
        assert state == OutboxPublishState.DELIVERED
        assert entry.broker_offset == "off1"

    async def test_begin_after_failed(self) -> None:
        s = InMemoryOutboxVerifyStore()
        await s.begin("e1")
        await s.fail("e1", "err1")
        state, entry = await s.begin("e1")
        assert state == OutboxPublishState.FAILED
        assert entry.last_error == "err1"


class TestInMemoryConfirm:
    async def test_confirm(self) -> None:
        s = InMemoryOutboxVerifyStore()
        await s.begin("e1")
        await s.confirm("e1", "kafka", "123")
        entry = await s.get("e1")
        assert entry.state == OutboxPublishState.DELIVERED
        assert entry.broker == "kafka"
        assert entry.broker_offset == "123"
        assert entry.delivered_at is not None


class TestInMemoryFail:
    async def test_fail_increments_attempts(self) -> None:
        s = InMemoryOutboxVerifyStore()
        await s.begin("e1")
        await s.fail("e1", "err1")
        await s.fail("e1", "err2")
        entry = await s.get("e1")
        # begin=1 + fail=2 = 3 attempts.
        assert entry.attempts == 3
        assert entry.last_error == "err2"


class TestInMemoryGet:
    async def test_get_missing(self) -> None:
        s = InMemoryOutboxVerifyStore()
        assert await s.get("e1") is None

    async def test_get_existing(self) -> None:
        s = InMemoryOutboxVerifyStore()
        await s.begin("e1")
        entry = await s.get("e1")
        assert entry is not None


class TestPublishWithVerification:
    """``publish_with_verification()`` — two-phase protocol."""

    async def test_first_publish_acquired(self) -> None:
        svc = OutboxPublishService(store=InMemoryOutboxVerifyStore())

        async def publisher(payload, ctx):
            return ("kafka", "offset-1")

        result = await svc.publish_with_verification(
            event_id="e1", payload={"x": 1}, publisher=publisher
        )
        assert result.outcome == OutboxPublishOutcome.ACQUIRED
        assert result.broker_offset == "offset-1"
        assert result.entry.state == OutboxPublishState.DELIVERED

    async def test_duplicate_publish(self) -> None:
        """Second call with same event_id → DUPLICATE."""
        svc = OutboxPublishService(store=InMemoryOutboxVerifyStore())
        call_count = 0

        async def publisher(payload, ctx):
            nonlocal call_count
            call_count += 1
            return ("kafka", f"offset-{call_count}")

        r1 = await svc.publish_with_verification(
            event_id="e1", payload={"x": 1}, publisher=publisher
        )
        r2 = await svc.publish_with_verification(
            event_id="e1", payload={"x": 1}, publisher=publisher
        )
        assert r1.outcome == OutboxPublishOutcome.ACQUIRED
        assert r2.outcome == OutboxPublishOutcome.DUPLICATE
        assert r2.broker_offset == "offset-1"  # original
        assert call_count == 1

    async def test_publisher_failure(self) -> None:
        """Publisher raised → FAILED outcome + state=FAILED."""
        svc = OutboxPublishService(store=InMemoryOutboxVerifyStore())

        async def publisher(payload, ctx):
            raise ValueError("broker timeout")

        result = await svc.publish_with_verification(
            event_id="e1", payload={"x": 1}, publisher=publisher
        )
        assert result.outcome == OutboxPublishOutcome.FAILED
        assert "broker timeout" in result.error
        assert result.entry.state == OutboxPublishState.FAILED

    async def test_publisher_receives_payload_and_context(self) -> None:
        """Publisher получает payload + context."""
        svc = OutboxPublishService(store=InMemoryOutboxVerifyStore())
        received_payload = None
        received_context = None

        async def publisher(payload, ctx):
            nonlocal received_payload, received_context
            received_payload = payload
            received_context = ctx
            return ("kafka", "off")

        await svc.publish_with_verification(
            event_id="e1",
            payload={"order_id": "o1"},
            publisher=publisher,
            metadata={"trace_id": "t1"},
        )
        assert received_payload == {"order_id": "o1"}
        assert received_context["event_id"] == "e1"
        assert received_context["metadata"] == {"trace_id": "t1"}

    async def test_retry_after_failure(self) -> None:
        """FAILED → retry → ACQUIRED (succeeds)."""
        svc = OutboxPublishService(store=InMemoryOutboxVerifyStore())
        attempt = 0

        async def publisher(payload, ctx):
            nonlocal attempt
            attempt += 1
            if attempt < 2:
                raise ValueError("first fails")
            return ("kafka", "off-2")

        r1 = await svc.publish_with_verification(
            event_id="e1", payload={"x": 1}, publisher=publisher
        )
        assert r1.outcome == OutboxPublishOutcome.FAILED

        r2 = await svc.publish_with_verification(
            event_id="e1", payload={"x": 1}, publisher=publisher
        )
        assert r2.outcome == OutboxPublishOutcome.ACQUIRED
        assert r2.broker_offset == "off-2"


class TestInProgress:
    """Concurrent publisher path (PUBLISHING state)."""

    async def test_concurrent_publisher_returns_in_progress(self) -> None:
        """Если entry уже PUBLISHING (concurrent) → IN_PROGRESS."""
        from unittest.mock import AsyncMock, MagicMock

        pre_entry = OutboxPublishEntry(
            event_id="e1",
            state=OutboxPublishState.PUBLISHING,
            attempts=1,
        )
        mock_store = MagicMock(spec=OutboxPublishStore)
        mock_store.begin = AsyncMock(
            return_value=(OutboxPublishState.PUBLISHING, pre_entry)
        )
        svc = OutboxPublishService(store=mock_store)

        async def publisher(payload, ctx):
            return ("kafka", "off")

        result = await svc.publish_with_verification(
            event_id="e1", payload={}, publisher=publisher
        )
        assert result.outcome == OutboxPublishOutcome.IN_PROGRESS


class TestSingleton:
    def test_singleton(self) -> None:
        s1 = get_outbox_publish_service()
        s2 = get_outbox_publish_service()
        assert s1 is s2

    def test_reset(self) -> None:
        s1 = get_outbox_publish_service()
        reset_outbox_publish_service()
        s2 = get_outbox_publish_service()
        assert s1 is not s2

    def test_default_store_is_in_memory(self) -> None:
        svc = get_outbox_publish_service()
        assert isinstance(svc.store, InMemoryOutboxVerifyStore)


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import outbox_verify

        assert len(outbox_verify.__all__) == 7

    def test_store_all(self) -> None:
        from src.backend.core.outbox_verify import store

        assert len(store.__all__) == 4

    def test_service_all(self) -> None:
        from src.backend.core.outbox_verify import service

        assert len(service.__all__) == 3


class TestStoreInterface:
    def test_abc_instantiate_fails(self) -> None:
        with pytest.raises(TypeError):
            OutboxPublishStore()  # type: ignore[abstract]

    def test_abstract_methods(self) -> None:
        methods = OutboxPublishStore.__abstractmethods__
        assert "begin" in methods
        assert "confirm" in methods
        assert "fail" in methods
        assert "get" in methods
        assert "close" in methods
