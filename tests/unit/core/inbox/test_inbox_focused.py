"""Focused tests for ``core.inbox`` (Wave 1 P0 #2).

Цель: покрыть InboxService + InMemory store на 100%.
"""

from __future__ import annotations

import asyncio

import pytest

from src.backend.core.inbox import (
    InboxService,
    InMemoryInboxStore,
    get_inbox_service,
)
from src.backend.core.inbox.service import (
    InboxConflict,
    InboxOutcome,
    InboxResult,
    reset_inbox_service,
)
from src.backend.core.inbox.store.base import (
    InboxEntry,
    InboxState,
    InboxStore,
)
from src.backend.core.inbox.store.in_memory import (
    InMemoryInboxStore as InMemoryAlias,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """Reset singleton перед каждым тестом."""
    reset_inbox_service()


class TestInboxEntry:
    """``InboxEntry`` — dataclass basics."""

    def test_init_defaults(self) -> None:
        """Defaults: attempts=0, last_error=None, etc."""
        e = InboxEntry(
            consumer_id="c1",
            message_id="m1",
            state=InboxState.RECEIVED,
        )
        assert e.consumer_id == "c1"
        assert e.message_id == "m1"
        assert e.state == InboxState.RECEIVED
        assert e.attempts == 0
        assert e.last_error is None
        assert e.created_at == 0.0
        assert e.committed_at is None
        assert e.metadata == {}

    def test_init_with_all_fields(self) -> None:
        """Custom values сохраняются."""
        e = InboxEntry(
            consumer_id="c1",
            message_id="m1",
            state=InboxState.COMMITTED,
            attempts=3,
            last_error="prev error",
            created_at=100.0,
            committed_at=200.0,
            metadata={"trace_id": "abc"},
        )
        assert e.attempts == 3
        assert e.last_error == "prev error"
        assert e.committed_at == 200.0
        assert e.metadata == {"trace_id": "abc"}


class TestInboxStateEnum:
    """``InboxState`` — enum values."""

    def test_values(self) -> None:
        """Все enum values."""
        assert InboxState.MISSING.value == "missing"
        assert InboxState.RECEIVED.value == "received"
        assert InboxState.COMMITTED.value == "committed"
        assert InboxState.FAILED.value == "failed"

    def test_count(self) -> None:
        """Всего 4 states."""
        assert len(InboxState) == 4


class TestInboxOutcomeEnum:
    """``InboxOutcome`` — enum values."""

    def test_values(self) -> None:
        """Все enum values."""
        assert InboxOutcome.COMMITTED.value == "committed"
        assert InboxOutcome.DEDUPLICATED.value == "deduplicated"
        assert InboxOutcome.FAILED.value == "failed"
        assert InboxOutcome.LOCKED.value == "locked"

    def test_count(self) -> None:
        """Всего 4 outcomes."""
        assert len(InboxOutcome) == 4


class TestInMemoryStoreInit:
    """``InMemoryInboxStore.__init__``."""

    def test_init_empty(self) -> None:
        """Store starts empty."""
        s = InMemoryInboxStore()
        assert s.size() == 0

    def test_init_with_lock(self) -> None:
        """Store имеет asyncio.Lock."""
        s = InMemoryInboxStore()
        assert isinstance(s._lock, asyncio.Lock)


class TestInMemoryTryClaim:
    """``try_claim()`` — атомарная регистрация entry."""

    async def test_first_claim_returns_missing(self) -> None:
        """First claim → MISSING (обрабатывай)."""
        s = InMemoryInboxStore()
        state, entry = await s.try_claim("c1", "m1")
        assert state == InboxState.MISSING
        assert entry is None
        assert s.size() == 1

    async def test_second_claim_returns_received(self) -> None:
        """Second claim → RECEIVED (concurrent)."""
        s = InMemoryInboxStore()
        await s.try_claim("c1", "m1")
        state, entry = await s.try_claim("c1", "m1")
        assert state == InboxState.RECEIVED
        assert entry is not None

    async def test_claim_after_commit_returns_committed(self) -> None:
        """Claim после commit → COMMITTED (dedupe)."""
        s = InMemoryInboxStore()
        await s.try_claim("c1", "m1")
        await s.commit("c1", "m1")
        state, entry = await s.try_claim("c1", "m1")
        assert state == InboxState.COMMITTED

    async def test_claim_after_fail_returns_failed(self) -> None:
        """Claim после fail → FAILED (retry)."""
        s = InMemoryInboxStore()
        await s.try_claim("c1", "m1")
        await s.fail("c1", "m1", error="oops")
        state, entry = await s.try_claim("c1", "m1")
        assert state == InboxState.FAILED

    async def test_different_consumers_independent(self) -> None:
        """Разные consumer_id → независимые entries."""
        s = InMemoryInboxStore()
        state1, _ = await s.try_claim("c1", "m1")
        state2, _ = await s.try_claim("c2", "m1")
        assert state1 == InboxState.MISSING
        assert state2 == InboxState.MISSING
        assert s.size() == 2


class TestInMemoryCommit:
    """``commit()`` — RECEIVED → COMMITTED."""

    async def test_commit_pending(self) -> None:
        """commit() после try_claim → state=COMMITTED."""
        s = InMemoryInboxStore()
        await s.try_claim("c1", "m1")
        await s.commit("c1", "m1")
        entry = await s.get("c1", "m1")
        assert entry is not None
        assert entry.state == InboxState.COMMITTED
        assert entry.committed_at is not None

    async def test_commit_missing_no_op(self) -> None:
        """commit() без try_claim → no-op."""
        s = InMemoryInboxStore()
        await s.commit("c1", "m1")
        entry = await s.get("c1", "m1")
        assert entry is None


class TestInMemoryFail:
    """``fail()`` — RECEIVED → FAILED."""

    async def test_fail_increments_attempts(self) -> None:
        """``fail()`` инкрементирует attempts."""
        s = InMemoryInboxStore()
        await s.try_claim("c1", "m1")
        await s.fail("c1", "m1", error="err1")
        await s.fail("c1", "m1", error="err2")
        entry = await s.get("c1", "m1")
        assert entry is not None
        # try_claim = 1 attempt + 2 fails = 3 attempts.
        assert entry.attempts == 3
        assert entry.last_error == "err2"
        assert entry.state == InboxState.FAILED


class TestInMemoryGet:
    """``get()`` — retrieve entry."""

    async def test_get_missing(self) -> None:
        """get() для missing → None."""
        s = InMemoryInboxStore()
        assert await s.get("c1", "m1") is None

    async def test_get_existing(self) -> None:
        """get() для existing → entry."""
        s = InMemoryInboxStore()
        await s.try_claim("c1", "m1")
        entry = await s.get("c1", "m1")
        assert entry is not None
        assert entry.consumer_id == "c1"
        assert entry.message_id == "m1"


class TestInMemoryClose:
    """``close()`` — cleanup."""

    async def test_close_clears_entries(self) -> None:
        """close() очищает все entries."""
        s = InMemoryInboxStore()
        await s.try_claim("c1", "m1")
        await s.try_claim("c2", "m2")
        await s.close()
        assert s.size() == 0


class TestInMemoryTestHelpers:
    """``size()`` и ``clear()`` — test-only helpers."""

    def test_clear(self) -> None:
        """clear() удаляет все entries."""
        s = InMemoryInboxStore()
        s._entries["k"] = InboxEntry(
            consumer_id="c", message_id="m", state=InboxState.RECEIVED
        )
        s.clear()
        assert s.size() == 0


class TestInboxServiceInit:
    """``InboxService.__init__``."""

    def test_init(self) -> None:
        """InboxService(store) создаётся."""
        svc = InboxService(store=InMemoryInboxStore())
        assert svc.store is not None

    def test_store_property(self) -> None:
        """store property returns backend."""
        store = InMemoryInboxStore()
        svc = InboxService(store=store)
        assert svc.store is store


class TestProcessFirstCall:
    """``process()`` — first call (MISSING state)."""

    async def test_first_call_committed(self) -> None:
        """First call → COMMITTED."""
        inbox = InboxService(store=InMemoryInboxStore())
        call_count = 0

        async def handler(payload, ctx):
            nonlocal call_count
            call_count += 1
            return f"result-{call_count}"

        result = await inbox.process(
            consumer_id="c1", message_id="m1", handler=handler, payload={"x": 1}
        )
        assert result.outcome == InboxOutcome.COMMITTED
        assert result.result == "result-1"
        assert result.attempts == 1
        assert result.entry is not None
        assert result.entry.state == InboxState.COMMITTED

    async def test_handler_receives_payload_and_context(self) -> None:
        """Handler получает payload + context."""
        inbox = InboxService(store=InMemoryInboxStore())
        received_payload = None
        received_context = None

        async def handler(payload, ctx):
            nonlocal received_payload, received_context
            received_payload = payload
            received_context = ctx
            return "ok"

        await inbox.process(
            consumer_id="c1",
            message_id="m1",
            handler=handler,
            payload={"order_id": "o1"},
            metadata={"trace_id": "t1"},
        )
        assert received_payload == {"order_id": "o1"}
        assert received_context["consumer_id"] == "c1"
        assert received_context["message_id"] == "m1"
        assert received_context["metadata"] == {"trace_id": "t1"}

    async def test_handler_exception_marks_failed(self) -> None:
        """Handler raised → FAILED outcome + entry.attempts incremented."""
        inbox = InboxService(store=InMemoryInboxStore())

        async def handler(payload, ctx):
            raise ValueError("boom")

        result = await inbox.process(
            consumer_id="c1", message_id="m1", handler=handler
        )
        assert result.outcome == InboxOutcome.FAILED
        assert result.entry is not None
        assert result.entry.state == InboxState.FAILED
        assert "boom" in (result.entry.last_error or "")
        assert result.attempts >= 2  # try_claim=1 + fail=1

    async def test_handler_exception_caught_returns_failed(self) -> None:
        """Handler exception caught — InboxResult с FAILED (не re-raised).

        InboxService абсорбирует handler exceptions и возвращает InboxResult
        с outcome=FAILED. Это позволяет retry/caller сам решать политику.
        """
        inbox = InboxService(store=InMemoryInboxStore())

        async def handler(payload, ctx):
            raise ValueError("boom")

        # Не raise — caller сам обрабатывает через result.outcome.
        result = await inbox.process(
            consumer_id="c1", message_id="m1", handler=handler
        )
        assert result.outcome == InboxOutcome.FAILED
        assert "boom" in (result.entry.last_error or "")


class TestProcessReplay:
    """``process()`` — replay (COMMITTED state)."""

    async def test_replay_returns_deduplicated(self) -> None:
        """Replay → DEDUPLICATED, handler не вызывается."""
        inbox = InboxService(store=InMemoryInboxStore())
        call_count = 0

        async def handler(payload, ctx):
            nonlocal call_count
            call_count += 1
            return f"r-{call_count}"

        r1 = await inbox.process(
            consumer_id="c1", message_id="m1", handler=handler
        )
        r2 = await inbox.process(
            consumer_id="c1", message_id="m1", handler=handler
        )
        assert r1.outcome == InboxOutcome.COMMITTED
        assert r2.outcome == InboxOutcome.DEDUPLICATED
        assert call_count == 1
        # result=handler result (cached), но handler не вызывается.
        assert r2.result is None
        assert r2.entry is not None
        assert r2.entry.state == InboxState.COMMITTED


class TestProcessRetry:
    """``process()`` — retry после FAILED."""

    async def test_retry_after_failure(self) -> None:
        """FAILED → retry → COMMITTED (новая попытка)."""
        inbox = InboxService(store=InMemoryInboxStore())
        attempt = 0

        async def handler(payload, ctx):
            nonlocal attempt
            attempt += 1
            if attempt < 2:
                raise ValueError("first attempt fails")
            return "ok"

        r1 = await inbox.process(
            consumer_id="c1", message_id="m1", handler=handler
        )
        assert r1.outcome == InboxOutcome.FAILED

        r2 = await inbox.process(
            consumer_id="c1", message_id="m1", handler=handler
        )
        assert r2.outcome == InboxOutcome.COMMITTED
        assert r2.result == "ok"
        assert attempt == 2


class TestSingleton:
    """``get_inbox_service()`` — module-level singleton."""

    def test_singleton_returns_instance(self) -> None:
        """Singleton returns InboxService."""
        svc = get_inbox_service()
        assert isinstance(svc, InboxService)

    def test_singleton_returns_same_instance(self) -> None:
        """Multiple calls return same instance."""
        s1 = get_inbox_service()
        s2 = get_inbox_service()
        assert s1 is s2

    def test_reset_clears_singleton(self) -> None:
        """reset_inbox_service() очищает singleton."""
        s1 = get_inbox_service()
        reset_inbox_service()
        s2 = get_inbox_service()
        assert s1 is not s2

    def test_default_store_is_in_memory(self) -> None:
        """Default store — InMemoryInboxStore."""
        svc = get_inbox_service()
        assert isinstance(svc.store, InMemoryInboxStore)


class TestExports:
    """``__all__`` exports."""

    def test_inbox_all(self) -> None:
        """``core.inbox.__all__`` — 7 symbols."""
        from src.backend.core import inbox

        assert len(inbox.__all__) == 7

    def test_store_all(self) -> None:
        """``store.__all__`` — 3 symbols."""
        from src.backend.core.inbox import store

        assert len(store.__all__) == 3

    def test_service_all(self) -> None:
        """``service.__all__`` — 6 symbols."""
        from src.backend.core.inbox import service

        assert len(service.__all__) == 6


class TestErrors:
    """``InboxError`` + ``InboxConflict``."""

    def test_inbox_conflict_inherits_error(self) -> None:
        """InboxConflict — Exception subclass."""
        assert issubclass(InboxConflict, Exception)

    def test_inbox_conflict_message(self) -> None:
        """Message сохраняется."""
        e = InboxConflict("conflict for m1")
        assert "m1" in str(e)


class TestProcessLockedPath:
    """``process()`` — LOCKED path (concurrent processing)."""

    async def test_locked_path_with_pre_committed_entry(self) -> None:
        """Concurrent path — entry уже RECEIVED (mock store)."""
        from unittest.mock import AsyncMock, MagicMock

        # Mock store возвращает RECEIVED для try_claim (concurrent).
        pre_entry = InboxEntry(
            consumer_id="c1",
            message_id="m1",
            state=InboxState.RECEIVED,
            attempts=1,
        )
        mock_store = MagicMock(spec=InboxStore)
        mock_store.try_claim = AsyncMock(
            return_value=(InboxState.RECEIVED, pre_entry)
        )
        inbox = InboxService(store=mock_store)

        async def handler(payload, ctx):
            return "never called"

        result = await inbox.process(
            consumer_id="c1", message_id="m1", handler=handler
        )
        assert result.outcome == InboxOutcome.LOCKED
        assert result.attempts == 1
        assert result.entry is pre_entry
        # Handler не должен вызываться.
        # (вызов будет брошен через mock, но мы не дойдём).


class TestStoreInterface:
    """``InboxStore`` — ABC interface."""

    def test_cannot_instantiate_abc(self) -> None:
        """Нельзя instantiate ``InboxStore`` напрямую."""
        with pytest.raises(TypeError):
            InboxStore()  # type: ignore[abstract]

    def test_abstract_methods(self) -> None:
        """ABC имеет 5 abstract methods."""
        assert hasattr(InboxStore, "__abstractmethods__")
        methods = InboxStore.__abstractmethods__
        assert "try_claim" in methods
        assert "commit" in methods
        assert "fail" in methods
        assert "get" in methods
        assert "close" in methods
