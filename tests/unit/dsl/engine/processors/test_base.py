"""Unit-тесты для base.py — BaseProcessor, CallableProcessor, SubPipelineExecutor."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.base import (
    BaseProcessor,
    CallableProcessor,
    SubPipelineExecutor,
    collect_route_results,
    run_sub_processors,
)


def _make_exchange(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


class DummyProcessor(BaseProcessor):
    """Тестовый процессор-заглушка."""

    side_effect = SideEffectKind.PURE

    def __init__(self, name: str | None = None) -> None:
        super().__init__(name=name)
        self.processed: list[Exchange[Any]] = []

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        self.processed.append(exchange)
        exchange.set_property("processed", True)


# ── BaseProcessor ──────────────────────────────────────────────────────────────


class TestBaseProcessor:
    def test_name_default(self) -> None:
        proc = DummyProcessor()
        assert proc.name == "DummyProcessor"

    def test_name_custom(self) -> None:
        proc = DummyProcessor(name="my_proc")
        assert proc.name == "my_proc"

    def test_default_side_effect(self) -> None:
        assert DummyProcessor.side_effect == SideEffectKind.PURE

    def test_default_compensatable(self) -> None:
        assert DummyProcessor.compensatable is True

    def test_to_spec_returns_none_by_default(self) -> None:
        proc = DummyProcessor()
        assert proc.to_spec() is None


# ── CallableProcessor ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_callable_processor_sync() -> None:
    captured: list[Any] = []

    def sync_func(exchange: Exchange[Any], ctx: Any) -> None:
        captured.append(exchange.in_message.body)

    proc = CallableProcessor(sync_func, name="sync_test")
    ex = _make_exchange(body={"key": "value"})
    await proc.process(ex, MagicMock())
    assert captured == [{"key": "value"}]


@pytest.mark.asyncio
async def test_callable_processor_async() -> None:
    captured: list[Any] = []

    async def async_func(exchange: Exchange[Any], ctx: Any) -> None:
        captured.append(exchange.in_message.body)

    proc = CallableProcessor(async_func, name="async_test")
    ex = _make_exchange(body="async_value")
    await proc.process(ex, MagicMock())
    assert captured == ["async_value"]


@pytest.mark.asyncio
async def test_callable_processor_uses_custom_name() -> None:
    def func(exchange: Exchange[Any], ctx: Any) -> None:
        pass

    proc = CallableProcessor(func, name="custom_name")
    assert proc.name == "custom_name"


@pytest.mark.asyncio
async def test_callable_processor_name_from_func() -> None:
    def my_named_func(exchange: Exchange[Any], ctx: Any) -> None:
        pass

    proc = CallableProcessor(my_named_func)
    assert proc.name == "my_named_func"


# ── SubPipelineExecutor ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_route_safe_returns_tuple_with_error() -> None:
    # NOTE: This test requires route_registry and ExecutionEngine setup
    # Here we test the safe version that doesn't raise
    ctx = MagicMock()
    route_id, result, error = await SubPipelineExecutor.execute_route_safe(
        route_id="nonexistent_route",
        body={"test": "data"},
        headers={"x-header": "value"},
        context=ctx,
    )
    assert route_id == "nonexistent_route"
    assert result is None
    assert error is not None


# ── run_sub_processors ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_sub_processors_empty_list() -> None:
    ex = _make_exchange(body="test")
    await run_sub_processors([], ex, MagicMock())
    assert ex.properties.get("processed") is None


@pytest.mark.asyncio
async def test_run_sub_processors_single_processor() -> None:
    proc = DummyProcessor()
    ex = _make_exchange(body="test")
    await run_sub_processors([proc], ex, MagicMock())
    assert len(proc.processed) == 1


@pytest.mark.asyncio
async def test_run_sub_processors_multiple_processors() -> None:
    proc1 = DummyProcessor()
    proc2 = DummyProcessor()
    ex = _make_exchange(body="test")
    await run_sub_processors([proc1, proc2], ex, MagicMock())
    assert len(proc1.processed) == 1
    assert len(proc2.processed) == 1


@pytest.mark.asyncio
async def test_run_sub_processors_stops_on_failed_exchange() -> None:
    proc1 = DummyProcessor()
    proc2 = DummyProcessor()

    ex = _make_exchange(body="test")
    ex.status = ExchangeStatus.failed  # Simulate failure before processing

    await run_sub_processors([proc1, proc2], ex, MagicMock())
    assert len(proc1.processed) == 0
    assert len(proc2.processed) == 0


@pytest.mark.asyncio
async def test_run_sub_processors_stops_on_stopped_exchange() -> None:
    proc1 = DummyProcessor()
    proc2 = DummyProcessor()

    ex = _make_exchange(body="test")
    ex.stop()  # Mark as stopped

    await run_sub_processors([proc1, proc2], ex, MagicMock())
    assert len(proc1.processed) == 0
    assert len(proc2.processed) == 0


# ── collect_route_results ──────────────────────────────────────────────────────


def test_collect_route_results_all_success() -> None:
    raw = [("route1", {"result": "data1"}, None), ("route2", {"result": "data2"}, None)]
    results, errors = collect_route_results(raw)
    assert results == {"route1": {"result": "data1"}, "route2": {"result": "data2"}}
    assert errors == {}


def test_collect_route_results_with_errors() -> None:
    raw = [
        ("route1", {"result": "data1"}, None),
        ("route2", None, "Something went wrong"),
    ]
    results, errors = collect_route_results(raw)
    assert results == {"route1": {"result": "data1"}}
    assert errors == {"route2": "Something went wrong"}


def test_collect_route_results_with_exception() -> None:
    raw = [("route1", {"result": "data1"}, None), Exception("Connection failed")]
    results, errors = collect_route_results(raw)
    assert results == {"route1": {"result": "data1"}}
    assert errors == {"_exception": "Connection failed"}


def test_collect_route_results_all_errors() -> None:
    raw = [("route1", None, "Error 1"), ("route2", None, "Error 2")]
    results, errors = collect_route_results(raw)
    assert results == {}
    assert errors == {"route1": "Error 1", "route2": "Error 2"}


def test_collect_route_results_empty() -> None:
    results, errors = collect_route_results([])
    assert results == {}
    assert errors == {}


# ── Subclass with non-default attributes ───────────────────────────────────────


class CustomSideEffectProcessor(BaseProcessor):
    side_effect = SideEffectKind.SIDE_EFFECTING
    compensatable = False

    def __init__(self, name: str | None = None) -> None:
        super().__init__(name=name)

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        pass


def test_subclass_custom_side_effect() -> None:
    proc = CustomSideEffectProcessor()
    assert proc.side_effect == SideEffectKind.SIDE_EFFECTING
    assert proc.compensatable is False


def test_subclass_custom_name() -> None:
    proc = CustomSideEffectProcessor(name="custom")
    assert proc.name == "custom"


def test_to_spec_can_be_overridden() -> None:
    class ProcessorWithSpec(BaseProcessor):
        side_effect = SideEffectKind.PURE

        def __init__(self, name: str | None = None) -> None:
            super().__init__(name=name)

        async def process(self, exchange: Exchange[Any], context: Any) -> None:
            pass

        def to_spec(self) -> dict[str, Any]:
            return {"custom": {"key": "value"}}

    proc = ProcessorWithSpec()
    assert proc.to_spec() == {"custom": {"key": "value"}}


def test_stateful_side_effect() -> None:
    class StatefulProcessor(BaseProcessor):
        side_effect = SideEffectKind.STATEFUL

        def __init__(self, name: str | None = None) -> None:
            super().__init__(name=name)

        async def process(self, exchange: Exchange[Any], context: Any) -> None:
            pass

    proc = StatefulProcessor()
    assert proc.side_effect == SideEffectKind.STATEFUL
