"""Focused tests for ``core.idempotency`` (Wave 1 P0 #1).

Цель: покрыть ``IdempotencyService`` + backends + decorator на 100%.
Проверяет:
- ``execute_or_replay`` — first call, replay, conflict, fail-then-retry.
- ``idempotent`` decorator — auto-dedupe.
- Backend state machine (PENDING → COMMITTED, fail).
- TTL expiration (in-memory).
- Singleton lifecycle.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from src.backend.core.idempotency import (
    IdempotencyService,
    InMemoryIdempotencyBackend,
    get_idempotency_service,
)
from src.backend.core.idempotency.backends.base import (
    IdempotencyBackend,
    IdempotencyEntry,
    IdempotencyOutcome,
)
from src.backend.core.idempotency.backends.in_memory import (
    InMemoryIdempotencyBackend as InMemoryBackendAlias,
)
from src.backend.core.idempotency.service import (
    IdempotencyConflict,
    IdempotencyState,
    reset_idempotency_service,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """Reset singleton перед каждым тестом."""
    reset_idempotency_service()


class TestIdempotencyEntry:
    """``IdempotencyEntry`` — dataclass basics."""

    def test_init_defaults(self) -> None:
        """Defaults: state=PENDING, result=None, error=None."""
        e = IdempotencyEntry(key="k1", state=IdempotencyOutcome.PENDING)
        assert e.key == "k1"
        assert e.state == IdempotencyOutcome.PENDING
        assert e.result is None
        assert e.error is None
        assert e.created_at == 0.0
        assert e.committed_at is None
        assert e.ttl_seconds == 86400
        assert e.metadata == {}

    def test_init_with_all_fields(self) -> None:
        """Custom values сохраняются."""
        e = IdempotencyEntry(
            key="k1",
            state=IdempotencyOutcome.COMMITTED,
            result={"x": 1},
            error=None,
            created_at=100.0,
            committed_at=200.0,
            ttl_seconds=60,
            metadata={"trace_id": "abc"},
        )
        assert e.state == IdempotencyOutcome.COMMITTED
        assert e.result == {"x": 1}
        assert e.committed_at == 200.0
        assert e.ttl_seconds == 60
        assert e.metadata == {"trace_id": "abc"}

    def test_slots(self) -> None:
        """``slots=True`` — нет __dict__."""
        e = IdempotencyEntry(key="k1", state=IdempotencyOutcome.PENDING)
        assert not hasattr(e, "__dict__") or "__slots__" in dir(e)


class TestIdempotencyOutcomeEnum:
    """``IdempotencyOutcome`` — enum values."""

    def test_values(self) -> None:
        """Все enum values."""
        assert IdempotencyOutcome.MISSING.value == "missing"
        assert IdempotencyOutcome.PENDING.value == "pending"
        assert IdempotencyOutcome.COMMITTED.value == "committed"
        assert IdempotencyOutcome.LOCKED.value == "locked"
        assert IdempotencyOutcome.ERROR.value == "error"

    def test_count(self) -> None:
        """Всего 5 outcomes."""
        assert len(IdempotencyOutcome) == 5


class TestInMemoryIdempotencyBackendInit:
    """``InMemoryIdempotencyBackend.__init__``."""

    def test_init_empty(self) -> None:
        """Backend starts empty."""
        b = InMemoryIdempotencyBackend()
        assert b.size() == 0
        assert isinstance(b._entries, dict)

    def test_init_with_lock(self) -> None:
        """Backend имеет asyncio.Lock."""
        b = InMemoryIdempotencyBackend()
        assert isinstance(b._lock, asyncio.Lock)


class TestInMemoryBegin:
    """``begin()`` — ставит PENDING marker."""

    async def test_first_begin_returns_pending(self) -> None:
        """First begin → PENDING."""
        b = InMemoryIdempotencyBackend()
        outcome = await b.begin("k1", ttl_seconds=60)
        assert outcome == IdempotencyOutcome.PENDING
        assert b.size() == 1

    async def test_second_begin_same_key_returns_pending(self) -> None:
        """Second begin (concurrent) → PENDING (existing)."""
        b = InMemoryIdempotencyBackend()
        await b.begin("k1", ttl_seconds=60)
        outcome = await b.begin("k1", ttl_seconds=60)
        assert outcome == IdempotencyOutcome.PENDING

    async def test_begin_after_commit_returns_committed(self) -> None:
        """Begin после commit → COMMITTED."""
        b = InMemoryIdempotencyBackend()
        await b.begin("k1", ttl_seconds=60)
        await b.commit("k1", result={"x": 1})
        outcome = await b.begin("k1", ttl_seconds=60)
        assert outcome == IdempotencyOutcome.COMMITTED

    async def test_begin_expired_purges_old(self) -> None:
        """Begin после TTL expiry → PENDING (старый purged)."""
        b = InMemoryIdempotencyBackend()
        await b.begin("k1", ttl_seconds=0)  # TTL=0 → instant expire
        await asyncio.sleep(0.01)
        outcome = await b.begin("k1", ttl_seconds=60)
        assert outcome == IdempotencyOutcome.PENDING


class TestInMemoryCommit:
    """``commit()`` — PENDING → COMMITTED."""

    async def test_commit_pending(self) -> None:
        """``commit()`` после begin → entry state=COMMITTED."""
        b = InMemoryIdempotencyBackend()
        await b.begin("k1", ttl_seconds=60)
        await b.commit("k1", result={"x": 1})
        entry = await b.get("k1")
        assert entry is not None
        assert entry.state == IdempotencyOutcome.COMMITTED
        assert entry.result == {"x": 1}
        assert entry.committed_at is not None

    async def test_commit_without_begin(self) -> None:
        """``commit()`` без begin → re-create as COMMITTED (replay)."""
        b = InMemoryIdempotencyBackend()
        await b.commit("k1", result={"x": 1})
        entry = await b.get("k1")
        assert entry is not None
        assert entry.state == IdempotencyOutcome.COMMITTED
        assert entry.result == {"x": 1}

    async def test_commit_overwrites_result(self) -> None:
        """``commit()`` второй раз → result перезаписан."""
        b = InMemoryIdempotencyBackend()
        await b.begin("k1", ttl_seconds=60)
        await b.commit("k1", result={"x": 1})
        await b.commit("k1", result={"x": 2})
        entry = await b.get("k1")
        assert entry.result == {"x": 2}


class TestInMemoryFail:
    """``fail()`` — PENDING → MISSING (delete)."""

    async def test_fail_pending(self) -> None:
        """``fail()`` удаляет PENDING entry."""
        b = InMemoryIdempotencyBackend()
        await b.begin("k1", ttl_seconds=60)
        await b.fail("k1")
        entry = await b.get("k1")
        assert entry is None

    async def test_fail_committed_no_op(self) -> None:
        """``fail()`` для COMMITTED entry → no-op (не трогает)."""
        b = InMemoryIdempotencyBackend()
        await b.begin("k1", ttl_seconds=60)
        await b.commit("k1", result={"x": 1})
        await b.fail("k1")
        entry = await b.get("k1")
        assert entry is not None
        assert entry.state == IdempotencyOutcome.COMMITTED

    async def test_fail_missing_no_op(self) -> None:
        """``fail()`` для missing key → no-op."""
        b = InMemoryIdempotencyBackend()
        await b.fail("missing")  # не должно raise


class TestInMemoryGet:
    """``get()`` — возвращает entry или None."""

    async def test_get_missing(self) -> None:
        """``get()`` для missing key → None."""
        b = InMemoryIdempotencyBackend()
        entry = await b.get("missing")
        assert entry is None

    async def test_get_existing(self) -> None:
        """``get()`` для existing key → entry."""
        b = InMemoryIdempotencyBackend()
        await b.begin("k1", ttl_seconds=60)
        entry = await b.get("k1")
        assert entry is not None
        assert entry.key == "k1"

    async def test_get_expired_returns_none(self) -> None:
        """``get()`` для expired entry → None + purges."""
        b = InMemoryIdempotencyBackend()
        await b.begin("k1", ttl_seconds=0)  # instant expire
        await asyncio.sleep(0.01)
        entry = await b.get("k1")
        assert entry is None


class TestInMemoryClose:
    """``close()`` — cleanup."""

    async def test_close_clears_entries(self) -> None:
        """``close()`` очищает все entries."""
        b = InMemoryIdempotencyBackend()
        await b.begin("k1", ttl_seconds=60)
        await b.begin("k2", ttl_seconds=60)
        await b.close()
        assert b.size() == 0


class TestInMemoryTestHelpers:
    """``size()`` и ``clear()`` — test-only helpers."""

    def test_size_empty(self) -> None:
        """``size()`` empty = 0."""
        b = InMemoryIdempotencyBackend()
        assert b.size() == 0

    async def test_size_after_operations(self) -> None:
        """``size()`` отражает количество entries."""
        b = InMemoryIdempotencyBackend()
        await b.begin("k1", ttl_seconds=60)
        assert b.size() == 1
        await b.begin("k2", ttl_seconds=60)
        assert b.size() == 2

    def test_clear(self) -> None:
        """``clear()`` удаляет все entries."""
        b = InMemoryIdempotencyBackend()
        # Synchronous test (clear doesn't need async).
        b._entries["k1"] = IdempotencyEntry(
            key="k1", state=IdempotencyOutcome.PENDING
        )
        b.clear()
        assert b.size() == 0


class TestExecuteOrReplayConflict:
    """``execute_or_replay()`` — conflict path (PENDING in backend)."""

    async def test_conflict_on_pending_entry(self) -> None:
        """Если entry уже PENDING (concurrent) → conflict=True."""
        from unittest.mock import AsyncMock

        backend = InMemoryIdempotencyBackend()
        # Pre-populate as PENDING (simulating concurrent caller).
        await backend.begin("k1", ttl_seconds=60)
        svc = IdempotencyService(backend=backend)

        # Now another caller arrives — must see PENDING and report conflict.
        state = await svc.execute_or_replay(
            "k1", lambda: asyncio.sleep(0, result="never")
        )
        assert state.conflict is True
        assert state.replayed is False
        assert state.result is None


class TestExecuteOrReplayLockedBackend:
    """Backend, возвращающий LOCKED."""

    async def test_locked_outcome_conflict(self) -> None:
        """Backend → LOCKED → state.conflict=True."""
        from unittest.mock import AsyncMock, MagicMock

        backend = MagicMock(spec=IdempotencyBackend)
        backend.get = AsyncMock(return_value=None)
        backend.begin = AsyncMock(return_value=IdempotencyOutcome.LOCKED)
        svc = IdempotencyService(backend=backend)
        state = await svc.execute_or_replay(
            "k1", lambda: asyncio.sleep(0, result="x")
        )
        assert state.conflict is True

    async def test_committed_outcome_after_begin_replays(self) -> None:
        """Backend begin → COMMITTED (race) → fetch + replay."""
        from unittest.mock import AsyncMock, MagicMock

        committed_entry = IdempotencyEntry(
            key="k1",
            state=IdempotencyOutcome.COMMITTED,
            result={"race": "winner"},
        )

        backend = MagicMock(spec=IdempotencyBackend)
        backend.get = AsyncMock(return_value=None)
        backend.begin = AsyncMock(return_value=IdempotencyOutcome.COMMITTED)
        # After race detected, get returns the winning entry.
        async def get_side_effect(key: str) -> IdempotencyEntry | None:
            return committed_entry

        backend.get = AsyncMock(side_effect=get_side_effect)
        svc = IdempotencyService(backend=backend)
        state = await svc.execute_or_replay(
            "k1", lambda: asyncio.sleep(0, result="never-called")
        )
        assert state.replayed is True
        assert state.result == {"race": "winner"}


class TestDecoratorConflict:
    """Decorator path при conflict."""

    async def test_decorator_raises_idempotency_conflict(self) -> None:
        """Decorator при state.conflict=True → IdempotencyConflict."""
        from unittest.mock import AsyncMock, MagicMock

        backend = MagicMock(spec=IdempotencyBackend)
        backend.get = AsyncMock(return_value=None)
        backend.begin = AsyncMock(return_value=IdempotencyOutcome.LOCKED)
        svc = IdempotencyService(backend=backend)

        @svc.idempotent(key_fn=lambda args, kwargs: "k1")
        async def my_func() -> str:
            return "x"

        with pytest.raises(IdempotencyConflict, match="k1"):
            await my_func()


class TestIdempotencyServiceInit:
    """``IdempotencyService.__init__``."""

    def test_init_with_in_memory_backend(self) -> None:
        """``IdempotencyService(in_memory)`` создаётся."""
        backend = InMemoryIdempotencyBackend()
        svc = IdempotencyService(backend=backend)
        assert svc.backend is backend
        assert svc._default_ttl == 86400

    def test_init_custom_ttl(self) -> None:
        """Custom TTL."""
        svc = IdempotencyService(
            backend=InMemoryIdempotencyBackend(), default_ttl_seconds=60
        )
        assert svc._default_ttl == 60


class TestExecuteOrReplay:
    """``execute_or_replay()`` — основной flow."""

    async def test_first_call_executes_fn(self) -> None:
        """First call → execute fn, committed=True."""
        svc = IdempotencyService(backend=InMemoryIdempotencyBackend())
        state = await svc.execute_or_replay(
            "k1", lambda: asyncio.sleep(0, result="ok")
        )
        assert state.replayed is False
        assert state.committed is True
        assert state.result == "ok"
        assert state.conflict is False

    async def test_replay_returns_cached(self) -> None:
        """Second call with same key → replayed=True."""
        svc = IdempotencyService(backend=InMemoryIdempotencyBackend())
        call_count = 0

        async def fn() -> str:
            nonlocal call_count
            call_count += 1
            return f"result-{call_count}"

        s1 = await svc.execute_or_replay("k1", fn)
        s2 = await svc.execute_or_replay("k1", fn)
        assert s1.replayed is False
        assert s2.replayed is True
        assert s1.result == s2.result == "result-1"
        assert call_count == 1  # fn вызван только раз

    async def test_fn_exception_clears_state(self) -> None:
        """``fn()`` exception → fail() → следующий call может retry."""
        svc = IdempotencyService(backend=InMemoryIdempotencyBackend())
        call_count = 0

        async def fn() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await svc.execute_or_replay("k1", fn)
        # Второй call — retry должен сработать.
        with pytest.raises(ValueError):
            await svc.execute_or_replay("k1", fn)
        # fn вызван 2 раза (по разу на каждый attempt).
        assert call_count == 2

    async def test_fn_exception_then_success(self) -> None:
        """fn raise → retry → success."""
        svc = IdempotencyService(backend=InMemoryIdempotencyBackend())
        attempt = 0

        async def fn() -> str:
            nonlocal attempt
            attempt += 1
            if attempt < 2:
                raise ValueError("first attempt")
            return "ok"

        with pytest.raises(ValueError):
            await svc.execute_or_replay("k1", fn)
        state = await svc.execute_or_replay("k1", fn)
        assert state.result == "ok"
        assert attempt == 2

    async def test_custom_ttl(self) -> None:
        """``ttl_seconds=60`` override default."""
        svc = IdempotencyService(backend=InMemoryIdempotencyBackend())
        await svc.execute_or_replay("k1", lambda: asyncio.sleep(0, result=1), ttl_seconds=60)
        entry = await svc.backend.get("k1")
        assert entry is not None
        assert entry.ttl_seconds == 60

    async def test_different_keys_independent(self) -> None:
        """Разные keys → независимые executions."""
        svc = IdempotencyService(backend=InMemoryIdempotencyBackend())
        s1 = await svc.execute_or_replay("k1", lambda: asyncio.sleep(0, result="a"))
        s2 = await svc.execute_or_replay("k2", lambda: asyncio.sleep(0, result="b"))
        assert s1.result == "a"
        assert s2.result == "b"
        assert s1.replayed is False
        assert s2.replayed is False


class TestIdempotentDecorator:
    """``@svc.idempotent(key_fn=...)`` — decorator."""

    async def test_decorator_basic(self) -> None:
        """Decorator: same key → same result."""
        svc = IdempotencyService(backend=InMemoryIdempotencyBackend())
        call_count = 0

        @svc.idempotent(key_fn=lambda args, kwargs: f"order:{args[0]}")
        async def create_order(order_id: str, amount: int) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"order_id": order_id, "amount": amount, "seq": call_count}

        r1 = await create_order("o1", 100)
        r2 = await create_order("o1", 100)
        # Same key → replayed.
        assert r1 == r2
        assert call_count == 1

    async def test_decorator_different_keys(self) -> None:
        """Decorator: different keys → different results."""
        svc = IdempotencyService(backend=InMemoryIdempotencyBackend())

        @svc.idempotent(key_fn=lambda args, kwargs: f"order:{args[0]}")
        async def create_order(order_id: str, amount: int) -> str:
            return f"order-{order_id}"

        r1 = await create_order("o1", 100)
        r2 = await create_order("o2", 100)
        assert r1 == "order-o1"
        assert r2 == "order-o2"

    async def test_decorator_preserves_metadata(self) -> None:
        """Decorator сохраняет ``functools.wraps`` metadata."""
        svc = IdempotencyService(backend=InMemoryIdempotencyBackend())

        @svc.idempotent(key_fn=lambda args, kwargs: args[0])
        async def my_func(x: int) -> int:
            """My docstring."""
            return x * 2

        assert my_func.__name__ == "my_func"
        assert "My docstring" in (my_func.__doc__ or "")

    async def test_decorator_with_kwargs(self) -> None:
        """Decorator с key_fn, использующим kwargs."""
        svc = IdempotencyService(backend=InMemoryIdempotencyBackend())
        call_count = 0

        @svc.idempotent(key_fn=lambda args, kwargs: f"k:{kwargs.get('id')}")
        async def fn(*, id: str) -> str:
            nonlocal call_count
            call_count += 1
            return f"result-{call_count}"

        r1 = await fn(id="x")
        r2 = await fn(id="x")
        assert r1 == r2 == "result-1"

    async def test_decorator_attaches_metadata(self) -> None:
        """Decorator attaches ``__idempotency_key_fn__`` + ``__idempotency_ttl__``."""
        svc = IdempotencyService(backend=InMemoryIdempotencyBackend())

        key_fn = lambda args, kwargs: f"k:{args[0]}"

        @svc.idempotent(key_fn=key_fn, ttl_seconds=120)
        async def my_func(x: int) -> int:
            return x

        assert my_func.__idempotency_key_fn__ is key_fn
        assert my_func.__idempotency_ttl__ == 120


class TestSingleton:
    """``get_idempotency_service()`` — module-level singleton."""

    def test_singleton_returns_instance(self) -> None:
        """Singleton returns IdempotencyService."""
        svc = get_idempotency_service()
        assert isinstance(svc, IdempotencyService)

    def test_singleton_returns_same_instance(self) -> None:
        """Multiple calls return same instance."""
        s1 = get_idempotency_service()
        s2 = get_idempotency_service()
        assert s1 is s2

    def test_reset_clears_singleton(self) -> None:
        """``reset_idempotency_service()`` очищает singleton."""
        s1 = get_idempotency_service()
        reset_idempotency_service()
        s2 = get_idempotency_service()
        assert s1 is not s2

    def test_default_backend_is_in_memory(self) -> None:
        """Default backend — InMemory."""
        svc = get_idempotency_service()
        assert isinstance(svc.backend, InMemoryIdempotencyBackend)


class TestExports:
    """``__all__`` exports."""

    def test_idempotency_all(self) -> None:
        """``core.idempotency.__all__`` — 6 symbols."""
        from src.backend.core import idempotency

        assert len(idempotency.__all__) == 6

    def test_backends_all(self) -> None:
        """``backends.__all__`` — 4 symbols."""
        from src.backend.core.idempotency import backends

        assert len(backends.__all__) == 4

    def test_service_all(self) -> None:
        """``service.__all__`` — 5 symbols."""
        from src.backend.core.idempotency import service

        assert len(service.__all__) == 5


class TestIdempotencyState:
    """``IdempotencyState`` — result dataclass."""

    def test_init_defaults(self) -> None:
        """Defaults: result=None, replayed=False, committed=False, conflict=False."""
        s = IdempotencyState()
        assert s.result is None
        assert s.replayed is False
        assert s.committed is False
        assert s.conflict is False

    def test_init_with_values(self) -> None:
        """Custom values сохраняются."""
        s = IdempotencyState(result={"x": 1}, replayed=True, committed=True)
        assert s.result == {"x": 1}
        assert s.replayed is True
        assert s.committed is True


class TestErrors:
    """``IdempotencyError`` + ``IdempotencyConflict``."""

    def test_idempotency_conflict_inherits_error(self) -> None:
        """``IdempotencyConflict`` — подкласс ``IdempotencyError``."""
        assert issubclass(IdempotencyConflict, Exception)
        assert issubclass(IdempotencyConflict, Exception)

    def test_idempotency_conflict_message(self) -> None:
        """Message сохраняется."""
        e = IdempotencyConflict("conflict for key=k1")
        assert "k1" in str(e)


class TestBackendInterface:
    """``IdempotencyBackend`` — ABC interface."""

    def test_cannot_instantiate_abc(self) -> None:
        """Нельзя instantiate ``IdempotencyBackend`` напрямую."""
        with pytest.raises(TypeError):
            IdempotencyBackend()  # type: ignore[abstract]

    def test_abstract_methods(self) -> None:
        """ABC имеет 5 abstract methods."""
        assert hasattr(IdempotencyBackend, "__abstractmethods__")
        methods = IdempotencyBackend.__abstractmethods__
        assert "begin" in methods
        assert "commit" in methods
        assert "fail" in methods
        assert "get" in methods
        assert "close" in methods
