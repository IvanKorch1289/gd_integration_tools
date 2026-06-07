"""Unit tests for StranglerFigProcessor (v21 §2.3)."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.processors.strangler_fig import (
    RouteTarget,
    StranglerFigProcessor,
    StranglerFigRollback,
    StranglerFigStats,
    get_strangler_rollback,
    get_strangler_stats,
    reset_strangler_rollback,
    reset_strangler_stats,
)


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(
        in_message=Message(body=body, headers={}),
        out_message=Message(body=body, headers={}),
    )


# ── StranglerFigStats ──────────────────────────────────────────────────


def test_stats_record_route() -> None:
    stats = StranglerFigStats()
    stats.record_route(RouteTarget.OLD)
    stats.record_route(RouteTarget.OLD)
    stats.record_route(RouteTarget.NEW)
    assert stats.routed_to_old == 2
    assert stats.routed_to_new == 1
    assert stats.total() == 3


def test_stats_record_error() -> None:
    stats = StranglerFigStats()
    stats.record_error(RouteTarget.NEW)
    stats.record_error(RouteTarget.OLD)
    assert stats.new_errors == 1
    assert stats.old_errors == 1


def test_stats_new_pct() -> None:
    stats = StranglerFigStats()
    assert stats.new_pct() == 0.0  # empty
    for _ in range(3):
        stats.record_route(RouteTarget.OLD)
    for _ in range(7):
        stats.record_route(RouteTarget.NEW)
    assert stats.new_pct() == 70.0


# ── StranglerFigRollback ───────────────────────────────────────────────


def test_rollback_default_inactive() -> None:
    rb = StranglerFigRollback()
    assert rb.is_active is False
    assert rb.reason == ""


def test_rollback_trigger() -> None:
    rb = StranglerFigRollback()
    rb.trigger("production incident")
    assert rb.is_active is True
    assert rb.reason == "production incident"


def test_rollback_reset() -> None:
    rb = StranglerFigRollback()
    rb.trigger("incident")
    rb.reset()
    assert rb.is_active is False
    assert rb.reason == ""


# ── StranglerFigProcessor: validation ──────────────────────────────────


def test_processor_validates_split_pct() -> None:
    async def h(b: Any) -> Any:
        return b

    with pytest.raises(ValueError, match="traffic_split_pct должен быть 0-100"):
        StranglerFigProcessor(old_handler=h, new_handler=h, traffic_split_pct=150.0)
    with pytest.raises(ValueError, match="traffic_split_pct должен быть 0-100"):
        StranglerFigProcessor(old_handler=h, new_handler=h, traffic_split_pct=-1.0)


def test_processor_validates_handlers() -> None:
    with pytest.raises(ValueError, match="old_handler и new_handler обязательны"):
        StranglerFigProcessor(  # type: ignore[arg-type]
            old_handler=None,  # type: ignore[arg-type]
            new_handler=lambda b: b,
        )


# ── StranglerFigProcessor: routing ─────────────────────────────────────


@pytest.mark.asyncio
async def test_split_0_all_old() -> None:
    """split_pct=0 → all traffic to old."""
    reset_strangler_stats()
    old_calls: list[Any] = []
    new_calls: list[Any] = []

    async def old_h(b: Any) -> str:
        old_calls.append(b)
        return "old"

    async def new_h(b: Any) -> str:
        new_calls.append(b)
        return "new"

    proc = StranglerFigProcessor(
        old_handler=old_h, new_handler=new_h, traffic_split_pct=0.0
    )
    for i in range(10):
        ex = _ex(body={"i": i})
        await proc.process(ex, None)  # type: ignore[arg-type]
        assert ex.properties["strangler_target"] == "old"
        assert ex.out_message.body == "old"

    assert len(old_calls) == 10
    assert len(new_calls) == 0
    assert get_strangler_stats().routed_to_old == 10
    assert get_strangler_stats().routed_to_new == 0


@pytest.mark.asyncio
async def test_split_100_all_new() -> None:
    """split_pct=100 → all traffic to new."""
    reset_strangler_stats()
    new_calls: list[Any] = []

    async def old_h(b: Any) -> str:
        return "old"

    async def new_h(b: Any) -> str:
        new_calls.append(b)
        return "new"

    proc = StranglerFigProcessor(
        old_handler=old_h, new_handler=new_h, traffic_split_pct=100.0
    )
    for i in range(5):
        ex = _ex(body={"i": i})
        await proc.process(ex, None)  # type: ignore[arg-type]
        assert ex.properties["strangler_target"] == "new"
        assert ex.out_message.body == "new"

    assert len(new_calls) == 5
    assert get_strangler_stats().routed_to_new == 5
    assert get_strangler_stats().routed_to_old == 0


@pytest.mark.asyncio
async def test_split_50_distribution() -> None:
    """split_pct=50 → ~50/50 distribution over many samples."""
    reset_strangler_stats()

    async def old_h(b: Any) -> str:
        return "old"

    async def new_h(b: Any) -> str:
        return "new"

    proc = StranglerFigProcessor(
        old_handler=old_h,
        new_handler=new_h,
        traffic_split_pct=50.0,
        deterministic_seed=42,
    )
    for i in range(1000):
        ex = _ex(body={"i": i})
        await proc.process(ex, None)  # type: ignore[arg-type]

    stats = get_strangler_stats()
    assert 400 <= stats.routed_to_new <= 600  # ~50% ± 10pp


@pytest.mark.asyncio
async def test_fallback_on_new_error() -> None:
    """Error в new → fallback to old (on_new_error=True default)."""
    reset_strangler_stats()

    async def old_h(b: Any) -> str:
        return "old_result"

    async def new_h(b: Any) -> str:
        raise RuntimeError("new system down")

    proc = StranglerFigProcessor(
        old_handler=old_h,
        new_handler=new_h,
        traffic_split_pct=100.0,  # force new
        on_new_error=True,
    )
    ex = _ex(body={"x": 1})
    await proc.process(ex, None)  # type: ignore[arg-type]
    # Fallback to old
    assert ex.out_message.body == "old_result"
    assert ex.properties["strangler_target"] == "old"
    stats = get_strangler_stats()
    # record_route() only on success → only old success counts
    assert stats.routed_to_new == 0  # new call failed → not counted
    assert stats.routed_to_old == 1  # fallback succeeded
    assert stats.new_errors == 1


@pytest.mark.asyncio
async def test_no_fallback_on_new_error_when_disabled() -> None:
    """on_new_error=False → error пробрасывается, нет fallback."""
    reset_strangler_stats()

    async def old_h(b: Any) -> str:
        return "old"

    async def new_h(b: Any) -> str:
        raise ValueError("boom")

    proc = StranglerFigProcessor(
        old_handler=old_h,
        new_handler=new_h,
        traffic_split_pct=100.0,
        on_new_error=False,
    )
    ex = _ex(body={"x": 1})
    await proc.process(ex, None)  # type: ignore[arg-type]
    # Error caught by @handle_processor_error
    assert ex.error is not None
    assert "boom" in ex.error
    assert get_strangler_stats().new_errors == 1


@pytest.mark.asyncio
async def test_rollback_forces_old() -> None:
    """Active rollback → all traffic to old regardless of split_pct."""
    reset_strangler_stats()
    reset_strangler_rollback()
    get_strangler_rollback().trigger("incident")

    old_calls: list[Any] = []
    new_calls: list[Any] = []

    async def old_h(b: Any) -> str:
        old_calls.append(b)
        return "old"

    async def new_h(b: Any) -> str:
        new_calls.append(b)
        return "new"

    proc = StranglerFigProcessor(
        old_handler=old_h, new_handler=new_h, traffic_split_pct=100.0
    )
    for i in range(5):
        ex = _ex(body={"i": i})
        await proc.process(ex, None)  # type: ignore[arg-type]
        assert ex.properties["strangler_target"] == "old"

    assert len(old_calls) == 5
    assert len(new_calls) == 0
    # Rollback counter incremented via trigger_rollback helper
    reset_strangler_rollback()


@pytest.mark.asyncio
async def test_manual_rollback_via_processor() -> None:
    """processor.trigger_rollback() → increment counter."""
    reset_strangler_stats()
    reset_strangler_rollback()

    async def old_h(b: Any) -> str:
        return "old"

    async def new_h(b: Any) -> str:
        return "new"

    proc = StranglerFigProcessor(
        old_handler=old_h, new_handler=new_h, traffic_split_pct=100.0
    )
    proc.trigger_rollback("manual test")
    assert get_strangler_stats().rollbacks_triggered == 1
    assert get_strangler_rollback().is_active is True
    reset_strangler_rollback()


# ── Side effect classification ─────────────────────────────────────────


def test_processor_side_effects() -> None:
    from src.backend.core.types.side_effect import SideEffectKind

    async def h(b: Any) -> Any:
        return b

    proc = StranglerFigProcessor(old_handler=h, new_handler=h)
    assert proc.side_effect == SideEffectKind.SIDE_EFFECTING
    assert proc.compensatable is True
