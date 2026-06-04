"""Unit-тесты для composed_message.py — ComposedMessageProcessor."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.composed_message import (
    AggregatorCallable,
    ComposedMessageProcessor,
    SplitterCallable,
)


def _make_exchange(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


class DummyProcessor(BaseProcessor):
    """Тестовый процессор-заглушка."""

    side_effect = None  # type: ignore

    def __init__(self) -> None:
        super().__init__(name="dummy")
        self.calls = 0

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        self.calls += 1
        # Double the body value
        if isinstance(exchange.in_message.body, int):
            exchange.set_out(body=exchange.in_message.body * 2)


class TestComposedMessageProcessor:
    def test_name_default(self) -> None:
        splitter: SplitterCallable = lambda ex: [ex]
        agg: AggregatorCallable = lambda parts: parts[0] if parts else _make_exchange()
        proc = ComposedMessageProcessor(splitter, [], agg)
        assert proc.name == "composed_message"

    def test_name_custom(self) -> None:
        splitter: SplitterCallable = lambda ex: [ex]
        agg: AggregatorCallable = lambda parts: parts[0] if parts else _make_exchange()
        proc = ComposedMessageProcessor(splitter, [], agg, name="custom")
        assert proc.name == "custom"

    def test_processors_list_copied(self) -> None:
        procs = [DummyProcessor()]
        splitter: SplitterCallable = lambda ex: [ex]
        agg: AggregatorCallable = lambda parts: parts[0] if parts else _make_exchange()
        proc = ComposedMessageProcessor(splitter, procs, agg)
        assert proc._processors == procs
        assert proc._processors is not procs  # Should be a copy


class TestComposedMessageProcessorProcess:
    @pytest.mark.asyncio
    async def test_basic_split_and_aggregate(self) -> None:
        def splitter(ex: Exchange[Any]) -> list[Exchange[Any]]:
            return [
                Exchange(in_message=Message(body=1)),
                Exchange(in_message=Message(body=2)),
            ]

        def aggregator(parts: list[Exchange[Any]]) -> Exchange[Any]:
            total = sum(p.out_message.body or p.in_message.body for p in parts)
            return Exchange(in_message=Message(body=total))

        proc = ComposedMessageProcessor(splitter, [DummyProcessor()], aggregator)
        ex = _make_exchange(body="ignored")
        await proc.process(ex, MagicMock())

        # Each part was processed by DummyProcessor (doubled)
        # Part 1: 1 * 2 = 2, Part 2: 2 * 2 = 4
        # Aggregator sums them: 2 + 4 = 6
        assert ex.out_message.body == 6
        assert ex.properties["composed_part_count"] == 2

    @pytest.mark.asyncio
    async def test_empty_parts_calls_aggregator_with_empty_list(self) -> None:
        empty_parts: list[Exchange[Any]] = []

        def splitter(ex: Exchange[Any]) -> list[Exchange[Any]]:
            return []

        def aggregator(parts: list[Exchange[Any]]) -> Exchange[Any]:
            return Exchange(in_message=Message(body=len(parts)))

        proc = ComposedMessageProcessor(splitter, [DummyProcessor()], aggregator)
        ex = _make_exchange(body="test")
        await proc.process(ex, MagicMock())

        assert ex.out_message.body == 0
        assert ex.properties["composed_part_count"] == 0

    @pytest.mark.asyncio
    async def test_splitter_exception_sets_error(self) -> None:
        def bad_splitter(ex: Exchange[Any]) -> list[Exchange[Any]]:
            raise RuntimeError("Split failed")

        agg: AggregatorCallable = lambda parts: _make_exchange()

        proc = ComposedMessageProcessor(bad_splitter, [], agg)
        ex = _make_exchange(body="test")
        await proc.process(ex, MagicMock())

        assert ex.error is not None
        assert "Split failed" in str(ex.error)
        assert ex.status == ExchangeStatus.failed

    @pytest.mark.asyncio
    async def test_splitter_not_list_sets_error(self) -> None:
        def not_list_splitter(ex: Exchange[Any]) -> Any:
            return "not a list"

        agg: AggregatorCallable = lambda parts: _make_exchange()

        proc = ComposedMessageProcessor(not_list_splitter, [], agg)
        ex = _make_exchange(body="test")
        await proc.process(ex, MagicMock())

        assert "must return list" in str(ex.error)
        assert ex.status == ExchangeStatus.failed

    @pytest.mark.asyncio
    async def test_non_exchange_parts_wrapped(self) -> None:
        def splitter(ex: Exchange[Any]) -> list[Exchange[Any]]:
            # Return raw values instead of Exchange objects
            return [1, 2, 3]

        def aggregator(parts: list[Exchange[Any]]) -> Exchange[Any]:
            total = sum(p.out_message.body or p.in_message.body for p in parts)
            return Exchange(in_message=Message(body=total))

        proc = ComposedMessageProcessor(splitter, [DummyProcessor()], aggregator)
        ex = _make_exchange(body="test")
        await proc.process(ex, MagicMock())

        # Raw values were wrapped and then processed (doubled)
        # Part 1: 1 * 2 = 2, Part 2: 2 * 2 = 4, Part 3: 3 * 2 = 6
        # Total: 2 + 4 + 6 = 12
        assert ex.out_message.body == 12

    @pytest.mark.asyncio
    async def test_part_already_failed_skips_processors(self) -> None:
        failed_part = Exchange(in_message=Message(body=1))
        failed_part.fail("Already failed")

        def splitter(ex: Exchange[Any]) -> list[Exchange[Any]]:
            return [failed_part]

        def aggregator(parts: list[Exchange[Any]]) -> Exchange[Any]:
            return Exchange(in_message=Message(body="aggregated"))

        proc = ComposedMessageProcessor(splitter, [DummyProcessor()], aggregator)
        ex = _make_exchange(body="test")
        await proc.process(ex, MagicMock())

        # The DummyProcessor should not have been called on the failed part
        assert ex.out_message.body == "aggregated"

    @pytest.mark.asyncio
    async def test_part_stopped_skips_processors(self) -> None:
        stopped_part = Exchange(in_message=Message(body=1))
        stopped_part.stop()

        def splitter(ex: Exchange[Any]) -> list[Exchange[Any]]:
            return [stopped_part]

        def aggregator(parts: list[Exchange[Any]]) -> Exchange[Any]:
            return Exchange(in_message=Message(body="aggregated"))

        proc = ComposedMessageProcessor(splitter, [DummyProcessor()], aggregator)
        ex = _make_exchange(body="test")
        await proc.process(ex, MagicMock())

        assert ex.out_message.body == "aggregated"

    @pytest.mark.asyncio
    async def test_aggregator_exception_sets_error(self) -> None:
        def splitter(ex: Exchange[Any]) -> list[Exchange[Any]]:
            return [Exchange(in_message=Message(body=1))]

        def bad_aggregator(parts: list[Exchange[Any]]) -> Exchange[Any]:
            raise RuntimeError("Aggregate failed")

        proc = ComposedMessageProcessor(splitter, [], bad_aggregator)
        ex = _make_exchange(body="test")
        await proc.process(ex, MagicMock())

        assert "Aggregate failed" in str(ex.error)
        assert ex.status == ExchangeStatus.failed

    @pytest.mark.asyncio
    async def test_aggregator_not_exchange_sets_error(self) -> None:
        def splitter(ex: Exchange[Any]) -> list[Exchange[Any]]:
            return [Exchange(in_message=Message(body=1))]

        def not_exchange_aggregator(parts: list[Exchange[Any]]) -> Any:
            return "not an exchange"

        proc = ComposedMessageProcessor(splitter, [], not_exchange_aggregator)
        ex = _make_exchange(body="test")
        await proc.process(ex, MagicMock())

        assert "must return Exchange" in str(ex.error)
        assert ex.status == ExchangeStatus.failed

    @pytest.mark.asyncio
    async def test_aggregator_returns_out_message_body(self) -> None:
        def splitter(ex: Exchange[Any]) -> list[Exchange[Any]]:
            return [Exchange(in_message=Message(body=1))]

        def aggregator(parts: list[Exchange[Any]]) -> Exchange[Any]:
            result = Exchange(in_message=Message(body="input"))
            result.set_out(body="output")
            return result

        proc = ComposedMessageProcessor(splitter, [], aggregator)
        ex = _make_exchange(body="test")
        await proc.process(ex, MagicMock())

        # Should use out_message.body, not in_message.body
        assert ex.out_message.body == "output"

    @pytest.mark.asyncio
    async def test_headers_preserved(self) -> None:
        def splitter(ex: Exchange[Any]) -> list[Exchange[Any]]:
            return [Exchange(in_message=Message(body=1, headers={"X-Req": "123"}))]

        def aggregator(parts: list[Exchange[Any]]) -> Exchange[Any]:
            return Exchange(in_message=Message(body="result", headers={"X-Res": "456"}))

        proc = ComposedMessageProcessor(splitter, [], aggregator)
        ex = _make_exchange(body="test")
        await proc.process(ex, MagicMock())

        assert ex.out_message.headers.get("X-Res") == "456"

    @pytest.mark.asyncio
    async def test_to_spec_returns_none(self) -> None:
        splitter: SplitterCallable = lambda ex: [ex]
        agg: AggregatorCallable = lambda parts: parts[0] if parts else _make_exchange()
        proc = ComposedMessageProcessor(splitter, [], agg)
        assert proc.to_spec() is None
