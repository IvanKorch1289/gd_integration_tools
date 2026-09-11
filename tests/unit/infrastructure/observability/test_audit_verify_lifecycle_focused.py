"""Focused tests for audit_verify_lifecycle (PERF-6.6 Sprint 22 coverage ratchet).

2026-09-11: переписаны под текущий контракт — AuditVerifyScheduler(*, store,
interval_hours=24.0), verify() через store, start_audit_verify(store=...).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.infrastructure.observability.audit_verify_lifecycle import (
    AuditVerifyScheduler,
    start_audit_verify,
    stop_audit_verify,
)


def _make_store(valid: bool = True) -> MagicMock:
    """Fake ImmutableAuditStore с verify()."""
    store = MagicMock()
    store.verify = AsyncMock(return_value=MagicMock(valid=valid))
    return store


def test_scheduler_init_default() -> None:
    """AuditVerifyScheduler init со store — default 24h."""
    s = AuditVerifyScheduler(store=_make_store())
    assert s.interval_seconds == 24.0 * 3600.0
    assert s.is_running is False
    assert s.runs_total == 0


def test_scheduler_init_custom() -> None:
    """AuditVerifyScheduler init с custom interval_hours."""
    s = AuditVerifyScheduler(store=_make_store(), interval_hours=1.0)
    assert s.interval_seconds == 3600.0


def test_scheduler_init_invalid_interval() -> None:
    """interval_hours <= 0 → ValueError."""
    with pytest.raises(ValueError, match="interval_hours"):
        AuditVerifyScheduler(store=_make_store(), interval_hours=0)


def test_scheduler_str_no_raise() -> None:
    """str/repr не raise."""
    s = AuditVerifyScheduler(store=_make_store())
    assert isinstance(str(s), str)


def test_scheduler_with_concrete_store() -> None:
    """AuditVerifyScheduler с concrete store-моком."""
    store = _make_store()
    s = AuditVerifyScheduler(store=store)
    assert s._store is store


@pytest.mark.asyncio
async def test_scheduler_run_once_increments_total() -> None:
    """Одна итерация loop → verify вызван, runs_total растёт."""
    s = AuditVerifyScheduler(store=_make_store(), interval_hours=1 / 3600)
    await s.start()
    # Даём loop-таске стартовать и выполнить verify до stop
    for _ in range(100):
        if s.runs_total >= 1:
            break
        await asyncio.sleep(0.01)
    await s.stop()
    assert s.is_running is False
    assert s.runs_total >= 1


@pytest.mark.asyncio
async def test_scheduler_loop_survives_verify_error() -> None:
    """verify() с ошибкой → loop живёт (defense-in-depth), runs_total не растёт."""
    store = _make_store()
    store.verify = AsyncMock(side_effect=RuntimeError("db down"))
    s = AuditVerifyScheduler(store=store, interval_hours=1 / 3600)
    await s.start()
    await s.stop()
    assert s.runs_total == 0


def test_start_audit_verify_returns_none() -> None:
    """start_audit_verify(*) без store → TypeError (обязательный kwarg)."""
    with pytest.raises(TypeError):
        import asyncio

        asyncio.run(start_audit_verify())  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_stop_audit_verify_handles_no_scheduler() -> None:
    """stop_audit_verify() без активного scheduler — не raise."""
    await stop_audit_verify()


@pytest.mark.asyncio
async def test_start_audit_verify_idempotent() -> None:
    """Повторный start_audit_verify с running scheduler — no-op."""
    from src.backend.infrastructure.observability.audit_verify_lifecycle import (
        start_audit_verify,
    )

    store = _make_store()
    s = AuditVerifyScheduler(store=store, interval_hours=24.0)
    # Эмулируем занятый singleton без реального запуска loop
    import src.backend.infrastructure.observability.audit_verify_lifecycle as mod

    mod.default_scheduler = s
    s._running = True
    try:
        await start_audit_verify(store=store)
        assert mod.default_scheduler is s
    finally:
        mod.default_scheduler = None
        s._running = False
