"""Unit-тесты 5-уровневой Graceful Degradation (S13 K2 W4)."""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.core.resilience.degradation import (
    DegradationManager,
    DegradationMode,
    DegradationTransition,
    mode_at_least,
)
from src.backend.infrastructure.persistence.degradation_state_store import (
    InMemoryDegradationStateStore,
)


def test_mode_strictness_ordering() -> None:
    assert mode_at_least(DegradationMode.MAINTENANCE, DegradationMode.ESSENTIAL_ONLY)
    assert mode_at_least(DegradationMode.ESSENTIAL_ONLY, DegradationMode.READ_ONLY)
    assert mode_at_least(DegradationMode.CACHE_ONLY, DegradationMode.READ_ONLY)
    assert mode_at_least(DegradationMode.READ_ONLY, DegradationMode.FULL)
    assert not mode_at_least(DegradationMode.FULL, DegradationMode.READ_ONLY)
    assert not mode_at_least(DegradationMode.READ_ONLY, DegradationMode.MAINTENANCE)


def test_legacy_aliases_have_same_strictness() -> None:
    assert mode_at_least(DegradationMode.DEGRADED, DegradationMode.READ_ONLY)
    assert mode_at_least(DegradationMode.READ_ONLY, DegradationMode.DEGRADED)
    assert mode_at_least(DegradationMode.EMERGENCY, DegradationMode.ESSENTIAL_ONLY)
    assert mode_at_least(DegradationMode.ESSENTIAL_ONLY, DegradationMode.EMERGENCY)


@pytest.mark.asyncio
async def test_set_mode_records_transition() -> None:
    mgr = DegradationManager()
    transition = await mgr.set_mode(
        DegradationMode.READ_ONLY, actor="ops-1", reason="db primary failure"
    )
    assert isinstance(transition, DegradationTransition)
    assert transition.to_mode == "read_only"
    assert transition.actor == "ops-1"
    assert transition.reason == "db primary failure"


@pytest.mark.asyncio
async def test_history_max_20_returned() -> None:
    mgr = DegradationManager()
    for i in range(30):
        await mgr.set_mode(
            DegradationMode.READ_ONLY if i % 2 == 0 else DegradationMode.FULL,
            actor=f"actor-{i}",
            reason=f"reason-{i}",
        )
    history = mgr.history(20)
    assert len(history) == 20
    assert history[-1].actor == "actor-29"


@pytest.mark.asyncio
async def test_current_mode_reflects_manual() -> None:
    mgr = DegradationManager()
    assert mgr.current_mode == DegradationMode.FULL
    await mgr.set_mode(DegradationMode.MAINTENANCE, actor="ops", reason="test")
    assert mgr.current_mode == DegradationMode.MAINTENANCE


@pytest.mark.asyncio
async def test_store_persistence() -> None:
    mgr = DegradationManager()
    store = InMemoryDegradationStateStore()
    mgr.attach_store(store)
    await mgr.set_mode(DegradationMode.CACHE_ONLY, actor="ops", reason="redis slow")
    loaded = await store.load_current()
    assert loaded == DegradationMode.CACHE_ONLY
    history = await store.load_history(10)
    assert len(history) == 1
    assert history[0].to_mode == "cache_only"


@pytest.mark.asyncio
async def test_store_load_history_limit() -> None:
    store = InMemoryDegradationStateStore()
    mgr = DegradationManager()
    mgr.attach_store(store)
    for i in range(5):
        await mgr.set_mode(
            DegradationMode.CACHE_ONLY, actor=f"a-{i}", reason=f"r-{i}"
        )
    history = await store.load_history(3)
    assert len(history) == 3


@pytest.mark.asyncio
async def test_store_error_does_not_raise() -> None:
    class _FailingStore:
        async def persist(self, *args, **kwargs):
            raise RuntimeError("boom")

        async def load_current(self):
            return None

        async def load_history(self, n=20):
            return []

    mgr = DegradationManager()
    mgr.attach_store(_FailingStore())
    # Должно не падать даже при ошибке store.
    await mgr.set_mode(DegradationMode.MAINTENANCE, actor="x", reason="y")
    assert mgr.current_mode == DegradationMode.MAINTENANCE
