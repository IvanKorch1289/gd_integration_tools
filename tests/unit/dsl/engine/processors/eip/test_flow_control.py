"""Unit-тесты flow_control processors: WireTap, Throttler, Delay, Aggregator,
Loop, ForEach, OnCompletion.

Паттерн: async tests, _ex fixture, моки для task_registry / redis / time.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.eip.flow_control import (
    AggregatorProcessor,
    DelayProcessor,
    ForEachProcessor,
    LoopProcessor,
    OnCompletionProcessor,
    ThrottlerProcessor,
    WireTapProcessor,
)


def _ex(body: Any = None, headers: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers=headers or {}))


class DummyProcessor(BaseProcessor):
    def __init__(self, payload: Any, name: str | None = None) -> None:
        super().__init__(name=name or "dummy")
        self._payload = payload

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        exchange.out_message = Message(body=self._payload)


class FailingProcessor(BaseProcessor):
    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        raise RuntimeError("fail")


class SetFailProcessor(BaseProcessor):
    def __init__(self, error: str = "fail", name: str | None = None) -> None:
        super().__init__(name=name or "set_fail")
        self._error = error

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        exchange.fail(self._error)


# =============================================================================
# WireTapProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_wire_tap_runs_async() -> None:
    """WireTap запускает tap-процессоры асинхронно, не меняя основной exchange."""
    dummy = DummyProcessor("tapped")
    proc = WireTapProcessor(tap_processors=[dummy])
    ctx = AsyncMock()
    e = _ex(body={"main": True})

    mock_task = MagicMock()
    with patch(
        "src.backend.dsl.engine.processors.eip.flow_control.get_task_registry"
    ) as mock_reg:
        mock_registry = MagicMock()
        mock_registry.create_task.return_value = mock_task
        mock_reg.return_value = mock_registry
        await proc.process(e, ctx)

    mock_registry.create_task.assert_called_once()
    assert e.in_message.body == {"main": True}
    assert e.out_message is None


@pytest.mark.asyncio
async def test_wire_tap_ignores_tap_failure() -> None:
    """Ошибка в tap-процессоре логируется, но не ломает основной поток."""
    failing = FailingProcessor()
    proc = WireTapProcessor(tap_processors=[failing])
    ctx = AsyncMock()
    e = _ex(body={"main": True})

    mock_task = MagicMock()
    with patch(
        "src.backend.dsl.engine.processors.eip.flow_control.get_task_registry"
    ) as mock_reg:
        mock_registry = MagicMock()
        mock_registry.create_task.return_value = mock_task
        mock_reg.return_value = mock_registry
        await proc.process(e, ctx)

    assert e.in_message.body == {"main": True}


# =============================================================================
# ThrottlerProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_throttler_allows_under_rate() -> None:
    """При наличии токенов задержки нет."""
    proc = ThrottlerProcessor(rate=10, burst=2)
    ctx = AsyncMock()
    e = _ex(body=1)

    with patch(
        "src.backend.dsl.engine.processors.eip.flow_control.asyncio.sleep"
    ) as mock_sleep:
        await proc.process(e, ctx)

    mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_throttler_sleeps_when_over_rate() -> None:
    """При исчерпании токенов вызывается sleep."""
    proc = ThrottlerProcessor(rate=1, burst=1)
    ctx = AsyncMock()
    e = _ex(body=1)

    # First call consumes token
    await proc.process(e, ctx)

    with patch(
        "src.backend.dsl.engine.processors.eip.flow_control.asyncio.sleep"
    ) as mock_sleep:
        await proc.process(e, ctx)
        mock_sleep.assert_called_once()


@pytest.mark.asyncio
async def test_throttler_to_spec() -> None:
    """to_spec сериализует параметры."""
    proc = ThrottlerProcessor(rate=5.5, burst=3)
    assert proc.to_spec() == {"throttle": {"rate": 5.5, "burst": 3}}


# =============================================================================
# DelayProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_delay_by_ms() -> None:
    """DelayProcessor ждёт указанное количество миллисекунд."""
    proc = DelayProcessor(delay_ms=100)
    ctx = AsyncMock()
    e = _ex(body=1)

    with patch(
        "src.backend.dsl.engine.processors.eip.flow_control.asyncio.sleep"
    ) as mock_sleep:
        await proc.process(e, ctx)
        mock_sleep.assert_called_once_with(0.1)


@pytest.mark.asyncio
async def test_delay_by_scheduled_time() -> None:
    """DelayProcessor ждёт до указанного timestamp."""
    proc = DelayProcessor(scheduled_time_fn=lambda ex: 1000.0)
    ctx = AsyncMock()
    e = _ex(body=1)

    with patch(
        "src.backend.dsl.engine.processors.eip.flow_control.time.time",
        return_value=500.0,
    ):
        with patch(
            "src.backend.dsl.engine.processors.eip.flow_control.asyncio.sleep"
        ) as mock_sleep:
            await proc.process(e, ctx)
            mock_sleep.assert_called_once_with(500.0)


@pytest.mark.asyncio
async def test_delay_no_sleep_when_past() -> None:
    """Если scheduled time уже прошёл, sleep не вызывается."""
    proc = DelayProcessor(scheduled_time_fn=lambda ex: 100.0)
    ctx = AsyncMock()
    e = _ex(body=1)

    with patch(
        "src.backend.dsl.engine.processors.eip.flow_control.time.time",
        return_value=500.0,
    ):
        with patch(
            "src.backend.dsl.engine.processors.eip.flow_control.asyncio.sleep"
        ) as mock_sleep:
            await proc.process(e, ctx)
            mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_delay_to_spec_with_fn() -> None:
    """Если задан scheduled_time_fn, to_spec возвращает None."""
    proc = DelayProcessor(scheduled_time_fn=lambda ex: 0.0)
    assert proc.to_spec() is None


@pytest.mark.asyncio
async def test_delay_to_spec_without_fn() -> None:
    """Без scheduled_time_fn сериализуется delay_ms."""
    proc = DelayProcessor(delay_ms=250)
    assert proc.to_spec() == {"delay": {"delay_ms": 250}}


# =============================================================================
# AggregatorProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_aggregator_waits_for_batch() -> None:
    """До достижения batch_size exchange останавливается."""
    proc = AggregatorProcessor(correlation_key=lambda ex: "k1", batch_size=3)
    ctx = AsyncMock()
    e1 = _ex(body="a")
    await proc.process(e1, ctx)
    assert e1.properties.get("aggregated") is False
    assert e1.stopped is True

    e2 = _ex(body="b")
    await proc.process(e2, ctx)
    assert e2.properties.get("aggregated") is False

    e3 = _ex(body="c")
    await proc.process(e3, ctx)
    assert e3.properties.get("aggregated") is True
    assert e3.out_message.body == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_aggregator_flush_expired() -> None:
    """Просроченные буферы очищаются."""
    proc = AggregatorProcessor(
        correlation_key=lambda ex: "k1", batch_size=10, timeout_seconds=0.001
    )
    ctx = AsyncMock()
    e = _ex(body="a")
    await proc.process(e, ctx)
    assert e.properties.get("aggregated") is False

    import asyncio

    await asyncio.sleep(0.01)

    e2 = _ex(body="b")
    await proc.process(e2, ctx)
    # Previous buffer expired, new buffer starts
    assert e2.properties.get("aggregated") is False


@pytest.mark.asyncio
async def test_aggregator_max_keys_eviction() -> None:
    """При превышении _MAX_CORRELATION_KEYS удаляется старый буфер."""
    proc = AggregatorProcessor(
        correlation_key=lambda ex: ex.meta.exchange_id, batch_size=10
    )
    ctx = AsyncMock()
    proc._MAX_CORRELATION_KEYS = 2
    for i in range(3):
        e = _ex(body=i)
        e.meta.exchange_id = f"ex{i}"
        await proc.process(e, ctx)
    assert len(proc._buffers) <= 2


# =============================================================================
# LoopProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_loop_count() -> None:
    """Loop выполняется заданное количество раз."""
    dummy = DummyProcessor("res")
    proc = LoopProcessor(processors=[dummy], count=3)
    ctx = AsyncMock()
    e = _ex(body="start")

    await proc.process(e, ctx)
    assert e.properties.get("loop_count") == 3
    assert len(e.properties.get("loop_results", [])) == 3


@pytest.mark.asyncio
async def test_loop_until_condition() -> None:
    """Loop останавливается по условию until."""
    dummy = DummyProcessor("res")
    proc2 = LoopProcessor(processors=[dummy], until=lambda ex: True, max_iterations=5)
    e2 = _ex(body="start")
    await proc2.process(e2, AsyncMock())
    assert e2.properties.get("loop_count") == 1


@pytest.mark.asyncio
async def test_loop_max_iterations() -> None:
    """Loop не превышает max_iterations."""
    dummy = DummyProcessor("res")
    proc = LoopProcessor(processors=[dummy], count=10000, max_iterations=5)
    ctx = AsyncMock()
    e = _ex(body="start")
    await proc.process(e, ctx)
    assert e.properties.get("loop_count") == 5


@pytest.mark.asyncio
async def test_loop_stops_on_failure() -> None:
    """Loop останавливается при failed exchange."""
    set_fail = SetFailProcessor("err")
    proc = LoopProcessor(processors=[set_fail], count=10, max_iterations=100)
    ctx = AsyncMock()
    e = _ex(body="start")
    await proc.process(e, ctx)
    assert e.properties.get("loop_count") == 1
    assert e.status == ExchangeStatus.failed


@pytest.mark.asyncio
async def test_loop_count_zero() -> None:
    """count=0 → ни одной итерации."""
    dummy = DummyProcessor("res")
    proc = LoopProcessor(processors=[dummy], count=0)
    ctx = AsyncMock()
    e = _ex(body="start")
    await proc.process(e, ctx)
    assert e.properties.get("loop_count") == 0


# =============================================================================
# ForEachProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_for_each_iterates_list() -> None:
    """ForEach перебирает элементы списка."""
    dummy = DummyProcessor("res")
    proc = ForEachProcessor(items_path="data.items", processors=[dummy])
    ctx = AsyncMock()
    e = _ex(body={"data": {"items": [1, 2, 3]}})

    with patch("jmespath.search", return_value=[1, 2, 3]):
        await proc.process(e, ctx)

    assert e.properties.get("for_each_count") == 3
    assert len(e.properties.get("for_each_results", [])) == 3


@pytest.mark.asyncio
async def test_for_each_empty_list() -> None:
    """Пустой список → 0 итераций."""
    dummy = DummyProcessor("res")
    proc = ForEachProcessor(items_path="data.items", processors=[dummy])
    ctx = AsyncMock()
    e = _ex(body={"data": {"items": []}})

    with patch("jmespath.search", return_value=[]):
        await proc.process(e, ctx)

    assert e.properties.get("for_each_count") == 0


@pytest.mark.asyncio
async def test_for_each_jmespath_none_defaults_empty() -> None:
    """Если jmespath возвращает None, используется пустой список."""
    dummy = DummyProcessor("res")
    proc = ForEachProcessor(items_path="data.missing", processors=[dummy])
    ctx = AsyncMock()
    e = _ex(body={"data": {}})

    with patch("jmespath.search", return_value=None):
        await proc.process(e, ctx)

    assert e.properties.get("for_each_count") == 0


@pytest.mark.asyncio
async def test_for_each_max_iterations() -> None:
    """Не более max_iterations элементов."""
    dummy = DummyProcessor("res")
    proc = ForEachProcessor(
        items_path="data.items", processors=[dummy], max_iterations=2
    )
    ctx = AsyncMock()
    e = _ex(body={"data": {"items": [1, 2, 3, 4]}})

    with patch("jmespath.search", return_value=[1, 2, 3, 4]):
        await proc.process(e, ctx)

    assert e.properties.get("for_each_count") == 2


# =============================================================================
# OnCompletionProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_on_completion_always_runs() -> None:
    """OnCompletion вызывает процессоры независимо от статуса."""
    dummy = DummyProcessor("done")
    proc = OnCompletionProcessor(processors=[dummy])
    ctx = AsyncMock()
    e = _ex(body=1)
    e.status = ExchangeStatus.failed
    e.error = "boom"

    await proc.process(e, ctx)
    assert e.out_message.body == "done"
    assert e.status == ExchangeStatus.failed
    assert e.error == "boom"


@pytest.mark.asyncio
async def test_on_completion_success_only() -> None:
    """on_success_only пропускает при failed."""
    dummy = DummyProcessor("done")
    proc = OnCompletionProcessor(processors=[dummy], on_success_only=True)
    ctx = AsyncMock()
    e = _ex(body=1)
    e.status = ExchangeStatus.failed

    await proc.process(e, ctx)
    assert e.out_message is None


@pytest.mark.asyncio
async def test_on_completion_failure_only() -> None:
    """on_failure_only пропускает при success."""
    dummy = DummyProcessor("done")
    proc = OnCompletionProcessor(processors=[dummy], on_failure_only=True)
    ctx = AsyncMock()
    e = _ex(body=1)
    e.status = ExchangeStatus.processing

    await proc.process(e, ctx)
    assert e.out_message is None


@pytest.mark.asyncio
async def test_on_completion_failure_runs_on_failed() -> None:
    """on_failure_only вызывается при failed."""
    dummy = DummyProcessor("done")
    proc = OnCompletionProcessor(processors=[dummy], on_failure_only=True)
    ctx = AsyncMock()
    e = _ex(body=1)
    e.status = ExchangeStatus.failed

    await proc.process(e, ctx)
    assert e.out_message.body == "done"


@pytest.mark.asyncio
async def test_on_completion_ignores_processor_error() -> None:
    """Ошибка в completion-процессоре логируется, не ломает exchange."""
    failing = FailingProcessor()
    proc = OnCompletionProcessor(processors=[failing])
    ctx = AsyncMock()
    e = _ex(body=1)
    original_status = ExchangeStatus.processing
    e.status = original_status

    await proc.process(e, ctx)
    assert e.status == original_status
    assert e.error is None
