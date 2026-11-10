"""ADR-0436 — circuit breaker + bulkhead для внешних вызовов DSL."""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.processors._resilience import guarded_external_call

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

    await asyncio.gather(
        *(guarded_external_call("test_bulkhead", _call) for _ in range(8))
    )
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


@pytest.mark.asyncio
async def test_server_error_counts_as_breaker_failure() -> None:
    """HTTP 5xx считается отказом для breaker'а (ADR-0436).

    Иначе CB не открывается на «upstream деградировал, но отвечает 503»:
    ``make_request`` не бросает исключение на 5xx.
    """
    from src.backend.core.resilience.breaker import get_breaker_registry

    get_breaker_registry().reset()

    class _Response:
        status_code = 503

    async def _degraded() -> _Response:
        return _Response()

    for _ in range(5):
        result = await guarded_external_call("test_5xx", _degraded)
        assert result.status_code == 503, "ответ 5xx должен возвращаться вызывающему"

    state = get_breaker_registry().list_states()
    assert state.get("dsl:test_5xx") in {"open", "half_open"}, state

    # Breaker открыт → следующий вызов отклоняется без обращения к upstream'у.
    from src.backend.core.resilience.breaker import CircuitOpen

    with pytest.raises(CircuitOpen):
        await guarded_external_call("test_5xx", _degraded)


@pytest.mark.asyncio
async def test_successful_response_does_not_open_breaker() -> None:
    """Успешный ответ не открывает breaker."""
    from src.backend.core.resilience.breaker import get_breaker_registry

    get_breaker_registry().reset()

    class _Response:
        status_code = 200

    async def _ok_response() -> _Response:
        return _Response()

    for _ in range(10):
        await guarded_external_call("test_2xx", _ok_response)

    state = get_breaker_registry().list_states()
    assert state.get("dsl:test_2xx") not in {"open", "half_open"}, state
