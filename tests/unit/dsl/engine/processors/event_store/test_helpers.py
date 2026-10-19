"""Tests for ``src.backend.dsl.engine.processors.event_store.helpers``.

Module-level EventStore singleton with thread-safe lazy init + reset.
"""

from __future__ import annotations

import pytest

from src.backend.dsl.engine.processors.event_store import helpers as mod
from src.backend.dsl.engine.processors.event_store.helpers import (
    get_event_store,
    reset_event_store,
    set_event_store,
)
from src.backend.dsl.engine.processors.event_store.store import (
    InMemoryEventStore,
)


@pytest.fixture(autouse=True)
def _reset_store() -> None:
    """Reset store до/после каждого теста."""
    mod._store = None
    yield
    mod._store = None


class TestGetEventStore:
    """get_event_store() — lazy singleton + thread-safety."""

    def test_returns_in_memory_store(self) -> None:
        store = get_event_store()
        assert isinstance(store, InMemoryEventStore)

    def test_returns_singleton(self) -> None:
        a = get_event_store()
        b = get_event_store()
        assert a is b

    def test_initializes_on_first_call(self) -> None:
        assert mod._store is None
        store = get_event_store()
        assert mod._store is not None
        assert store is mod._store


class TestSetEventStore:
    """set_event_store() — replace singleton (для tests/production)."""

    def test_replaces_singleton(self) -> None:
        new_store = InMemoryEventStore()
        set_event_store(new_store)
        assert get_event_store() is new_store

    def test_replaces_with_any_event_store(self) -> None:
        class _FakeEventStore:
            def append(self, event):  # type: ignore[no-untyped-def]
                pass

            def get(self, event_id):  # type: ignore[no-untyped-def]
                pass

        fake = _FakeEventStore()
        set_event_store(fake)
        # Не InMemoryEventStore, но всё равно возвращается
        assert get_event_store() is fake

    def test_set_overrides_existing(self) -> None:
        first = InMemoryEventStore()
        second = InMemoryEventStore()
        set_event_store(first)
        assert get_event_store() is first
        set_event_store(second)
        assert get_event_store() is second


class TestResetEventStore:
    """reset_event_store() — clear old store + create new in-memory."""

    def test_returns_in_memory_store(self) -> None:
        result = reset_event_store()
        assert isinstance(result, InMemoryEventStore)

    def test_replaces_singleton(self) -> None:
        first = InMemoryEventStore()
        set_event_store(first)
        # Reset возвращает новый
        result = reset_event_store()
        assert result is not first
        # get_event_store возвращает reset result
        assert get_event_store() is result

    def test_clears_existing_in_memory_store(self) -> None:
        # Use existing store, add some events
        from src.backend.dsl.engine.processors.event_store.types import Event

        store = get_event_store()
        event = Event(aggregate_id="a1", event_type="test")
        store.append(event)
        assert len(store._events) > 0

        # Reset should clear old + create new
        new_store = reset_event_store()
        assert len(new_store._events) == 0
        assert len(new_store._by_aggregate) == 0
        assert len(new_store._by_stream) == 0

    def test_reset_when_no_existing_store(self) -> None:
        # _store is None
        assert mod._store is None
        result = reset_event_store()
        assert isinstance(result, InMemoryEventStore)

    def test_reset_does_not_clear_non_in_memory_store(self) -> None:
        # Если store не InMemoryEventStore, не пытаемся clear

        class _FakeStore:
            pass

        fake = _FakeStore()
        set_event_store(fake)
        # Reset — should not try to call _events.clear on fake
        result = reset_event_store()
        # Новый in-memory instance создан
        assert isinstance(result, InMemoryEventStore)
        assert result is not fake


class TestThreadSafety:
    """Проверка наличия lock."""

    def test_has_lock(self) -> None:
        import threading

        assert isinstance(mod._store_lock, type(threading.Lock()))

    def test_lock_acquired_during_set(self) -> None:
        # Smoke: set под lock не падает
        set_event_store(InMemoryEventStore())


class TestModuleImports:
    """Smoke imports."""

    def test_module_imports(self) -> None:
        from src.backend.dsl.engine.processors.event_store import helpers as m

        assert m is mod

    def test_functions_callable(self) -> None:
        assert callable(get_event_store)
        assert callable(set_event_store)
        assert callable(reset_event_store)


class TestGetEventStoreReturnsSameInstance:
    """Singleton consistency check."""

    def test_multiple_get_returns_same(self) -> None:
        results = [get_event_store() for _ in range(5)]
        first = results[0]
        assert all(r is first for r in results)


class TestDoubleCheckLocking:
    """Double-check locking pattern в get_event_store."""

    def test_safe_under_concurrent_init(self) -> None:
        import threading

        results: list[EventStore] = []
        barrier = threading.Barrier(5)

        def worker() -> None:
            barrier.wait()
            results.append(get_event_store())

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Все 5 вызовов вернули один и тот же instance
        first = results[0]
        assert all(r is first for r in results)