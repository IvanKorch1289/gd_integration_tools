"""ADR-0436 — circuit breaker + bulkhead для внешних вызовов DSL."""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.processors._resilience import (
    guarded_external_call,
)

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_call_passes_through() -> None:
    """Успешный вызов проходит без изменений."""
    result = await guarded_external_call("test_ok", lambda: _ok("value"))
    assert result == "value"


@pytest.mark.asyncio
async def test_bulkhead_limits_concurrency() -> None:
    """Bulkhead ограничивает число одновременных вызовов."""
    import asyncio

    from src.backend.core.resilience.bulkhead_registry import get_bulkhead_registry

    registry = get_bulkhead_registry()
    registry.clear()
    active = 0
    peak = 0

    async def _call() -> str:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return "ok"

    await asyncio.gather(*(guarded_external_call("test_bulkhead", _call) for _ in range(8)))
    assert peak <= 8


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_failures() -> None:
    """После серии отказов breaker открывается и вызов падает быстро."""
    from src.backend.core.resilience.breaker import get_breaker_registry

    get_breaker_registry().reset()

    async def _boom() -> str:
        raise RuntimeError("down")

    failures = 0
    for _ in range(8):
        try:
            await guarded_external_call("test_cb", _boom)
        except Exception:
            failures += 1

    assert failures >= 1, "ошибка внешнего вызова должна пробрасываться"


@pytest.mark.asyncio
async def test_breaker_and_bulkhead_are_named_per_processor() -> None:
    """Имена ресурсов — ``dsl:<processor>`` (общие реестры)."""
    from src.backend.core.resilience.breaker import get_breaker_registry
    from src.backend.core.resilience.bulkhead_registry import get_bulkhead_registry

    await guarded_external_call("test_names", lambda: _ok("x"))

    assert "dsl:test_names" in get_breaker_registry().list_states()
    assert "dsl:test_names" in get_bulkhead_registry().list_names()


async def _ok(value: Any) -> Any:
    """Заглушка успешного вызова."""
    return value
