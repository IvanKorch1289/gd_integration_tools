"""Unit-тесты для apply_late_policy (W14.3, cycle 33 L3 cycle 1).

``late_event_policy.py`` — 69-LOC модуль, реализующий 3 стратегии
обработки late events в DSL watermark pipeline:

* ``DROP`` — exchange помечается ``_late_dropped``, не пропускается.
* ``SIDE_OUTPUT`` — публикация в side-sink, exchange помечается
  ``_late_routed``.
* ``REPROCESS`` — флагует ``_late_reprocess`` для downstream compensation.

Используется в ``dsl/engine/processors/streaming/windows.py`` для
windowed aggregations. Без тестов — гарантии поведения держатся
только на type hints и docstring.
"""


from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.types.watermark import LatePolicy, WatermarkState
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.late_event_policy import apply_late_policy


def _make_exchange() -> Exchange[Any]:
    """Создаёт минимальный Exchange для тестов.

    Exchange — pydantic BaseModel, конструктор принимает fields напрямую.
    """
    return Exchange(
        in_message=Message(body={"id": 1, "value": "test"}),
    )


def _make_state() -> WatermarkState:
    """Создаёт WatermarkState для трекинга метрик."""
    return WatermarkState()


@pytest.mark.asyncio
async def test_drop_policy_marks_exchange_and_returns_false() -> None:
    """DROP policy: exchange помечается _late_dropped, return False (drop)."""
    exchange = _make_exchange()
    state = _make_state()

    result = await apply_late_policy(exchange, state=state, policy=LatePolicy.DROP)

    assert result is False, "DROP должен сигнализировать 'не продолжать'"
    assert exchange.properties.get("_late_dropped") is True
    assert state.late_events_total == 1


@pytest.mark.asyncio
async def test_side_output_policy_marks_and_returns_true() -> None:
    """SIDE_OUTPUT: exchange помечается _late_routed, return True (continue)."""
    exchange = _make_exchange()
    state = _make_state()

    result = await apply_late_policy(
        exchange, state=state, policy=LatePolicy.SIDE_OUTPUT,
    )

    assert result is True, "SIDE_OUTPUT должен сигнализировать 'продолжать'"
    assert exchange.properties.get("_late_routed") is True
    assert state.late_events_total == 1


@pytest.mark.asyncio
async def test_reprocess_policy_marks_and_returns_true() -> None:
    """REPROCESS: exchange помечается _late_reprocess, return True."""
    exchange = _make_exchange()
    state = _make_state()

    result = await apply_late_policy(
        exchange, state=state, policy=LatePolicy.REPROCESS,
    )

    assert result is True
    assert exchange.properties.get("_late_reprocess") is True
    assert state.late_events_total == 1


@pytest.mark.asyncio
async def test_side_output_calls_callback_with_exchange() -> None:
    """SIDE_OUTPUT: side_output callback получает exchange."""
    exchange = _make_exchange()
    state = _make_state()
    captured: list[Exchange[Any]] = []

    async def side_sink(ex: Exchange[Any]) -> None:
        captured.append(ex)

    result = await apply_late_policy(
        exchange,
        state=state,
        policy=LatePolicy.SIDE_OUTPUT,
        side_output=side_sink,
    )

    assert result is True
    assert len(captured) == 1
    assert captured[0] is exchange


@pytest.mark.asyncio
async def test_side_output_handles_callback_failure_gracefully() -> None:
    """SIDE_OUTPUT: падение callback НЕ пробрасывается (log+continue)."""
    exchange = _make_exchange()
    state = _make_state()

    async def broken_sink(_ex: Exchange[Any]) -> None:
        raise RuntimeError("side sink down")

    # Должен НЕ raise — ошибка логируется, но apply_late_policy
    # возвращает True (exchange продолжается).
    result = await apply_late_policy(
        exchange,
        state=state,
        policy=LatePolicy.SIDE_OUTPUT,
        side_output=broken_sink,
    )
    assert result is True
    assert exchange.properties.get("_late_routed") is True


@pytest.mark.asyncio
async def test_side_output_handles_sync_callback() -> None:
    """SIDE_OUTPUT: sync callback (без await) тоже поддерживается."""
    exchange = _make_exchange()
    state = _make_state()
    call_count = 0

    def sync_sink(_ex: Exchange[Any]) -> None:
        nonlocal call_count
        call_count += 1

    result = await apply_late_policy(
        exchange,
        state=state,
        policy=LatePolicy.SIDE_OUTPUT,
        side_output=sync_sink,
    )

    assert result is True
    assert call_count == 1


@pytest.mark.asyncio
async def test_late_events_total_increments_for_each_call() -> None:
    """state.late_events_total инкрементируется на каждом вызове."""
    state = _make_state()
    assert state.late_events_total == 0

    for _i in range(3):
        exchange = _make_exchange()
        await apply_late_policy(exchange, state=state, policy=LatePolicy.DROP)

    assert state.late_events_total == 3


@pytest.mark.asyncio
async def test_drop_does_not_call_side_output() -> None:
    """DROP policy НЕ вызывает side_output callback (no-op)."""
    exchange = _make_exchange()
    state = _make_state()
    call_count = 0

    def side_sink(_ex: Exchange[Any]) -> None:
        nonlocal call_count
        call_count += 1

    await apply_late_policy(
        exchange,
        state=state,
        policy=LatePolicy.DROP,
        side_output=side_sink,
    )

    assert call_count == 0, "DROP не должен дёргать side_output"
