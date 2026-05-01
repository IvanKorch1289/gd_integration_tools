"""Wave 6.3 — unit-тесты ``ComposedMessageProcessor`` (последний EIP, 30/30).

Покрывает:
* split + 1 sub-processor (smoke-проверка пути через все этапы);
* split + multi-sub (несколько процессоров последовательно для каждой части);
* пустой split (aggregator получает пустой список);
* ошибка splitter обрабатывается;
* sync и async splitter / aggregator поддерживаются.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import pytest

from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.dsl.engine.processors.base import BaseProcessor
from src.dsl.engine.processors.composed_message import ComposedMessageProcessor


def _ctx() -> ExecutionContext:
    return ExecutionContext()


class _DoubleProcessor(BaseProcessor):
    """Удваивает body как число."""

    async def process(
        self, exchange: Exchange[Any], context: ExecutionContext
    ) -> None:
        body = exchange.in_message.body
        new_body = (body or 0) * 2
        exchange.set_out(body=new_body, headers=dict(exchange.in_message.headers))
        # Чтобы следующий процессор увидел значение в in_message:
        exchange.in_message.body = new_body


class _PlusOneProcessor(BaseProcessor):
    async def process(
        self, exchange: Exchange[Any], context: ExecutionContext
    ) -> None:
        body = exchange.in_message.body
        new_body = (body or 0) + 1
        exchange.set_out(body=new_body, headers=dict(exchange.in_message.headers))
        exchange.in_message.body = new_body


def _split_list(ex: Exchange[Any]) -> list[Exchange[Any]]:
    items = ex.in_message.body or []
    return [
        Exchange(in_message=Message(body=item, headers=dict(ex.in_message.headers)))
        for item in items
    ]


def _aggregate_sum(parts: list[Exchange[Any]]) -> Exchange[Any]:
    total = 0
    for p in parts:
        body = p.out_message.body if p.out_message else p.in_message.body
        total += body or 0
    out = Exchange(in_message=Message(body=total, headers={}))
    out.set_out(body=total, headers={})
    return out


@pytest.mark.asyncio
async def test_composed_split_one_sub_processor() -> None:
    """split + 1 sub-processor: каждая часть удваивается, затем сумма."""
    proc = ComposedMessageProcessor(
        splitter=_split_list,
        processors=[_DoubleProcessor()],
        aggregator=_aggregate_sum,
    )
    ex = Exchange(in_message=Message(body=[1, 2, 3], headers={}))
    await proc.process(ex, _ctx())
    # 1*2 + 2*2 + 3*2 = 12
    assert ex.out_message.body == 12
    assert ex.properties["composed_part_count"] == 3


@pytest.mark.asyncio
async def test_composed_split_multi_sub_processors() -> None:
    """split + multi-sub: применяется последовательно DoubleProcessor → PlusOneProcessor."""
    proc = ComposedMessageProcessor(
        splitter=_split_list,
        processors=[_DoubleProcessor(), _PlusOneProcessor()],
        aggregator=_aggregate_sum,
    )
    ex = Exchange(in_message=Message(body=[1, 2, 3], headers={}))
    await proc.process(ex, _ctx())
    # (1*2 + 1) + (2*2 + 1) + (3*2 + 1) = 3 + 5 + 7 = 15
    assert ex.out_message.body == 15
    assert ex.properties["composed_part_count"] == 3


@pytest.mark.asyncio
async def test_composed_empty_split() -> None:
    """Пустой split → aggregator получает пустой список."""
    proc = ComposedMessageProcessor(
        splitter=lambda ex: [],
        processors=[_DoubleProcessor()],
        aggregator=_aggregate_sum,
    )
    ex = Exchange(in_message=Message(body=[], headers={}))
    await proc.process(ex, _ctx())
    assert ex.out_message.body == 0
    assert ex.properties["composed_part_count"] == 0


@pytest.mark.asyncio
async def test_composed_async_splitter_aggregator() -> None:
    """async splitter и async aggregator поддерживаются."""

    async def _async_split(ex: Exchange[Any]) -> list[Exchange[Any]]:
        return _split_list(ex)

    async def _async_aggregate(parts: list[Exchange[Any]]) -> Exchange[Any]:
        return _aggregate_sum(parts)

    proc = ComposedMessageProcessor(
        splitter=_async_split,
        processors=[_DoubleProcessor()],
        aggregator=_async_aggregate,
    )
    ex = Exchange(in_message=Message(body=[10, 20], headers={}))
    await proc.process(ex, _ctx())
    assert ex.out_message.body == 60  # (10+20) * 2


@pytest.mark.asyncio
async def test_composed_splitter_error_marks_exchange_failed() -> None:
    """Исключение в splitter ловится и метит exchange как failed."""

    def _bad_split(ex: Exchange[Any]) -> list[Exchange[Any]]:
        raise RuntimeError("split boom")

    proc = ComposedMessageProcessor(
        splitter=_bad_split,
        processors=[],
        aggregator=_aggregate_sum,
    )
    ex = Exchange(in_message=Message(body=None, headers={}))
    await proc.process(ex, _ctx())
    assert ex.status == ExchangeStatus.failed
    assert "split" in (ex.error or "")


@pytest.mark.asyncio
async def test_composed_splitter_returns_non_list_fails() -> None:
    """splitter, вернувший не-list → fail."""
    proc = ComposedMessageProcessor(
        splitter=lambda ex: "not a list",  # type: ignore[arg-type,return-value]
        processors=[],
        aggregator=_aggregate_sum,
    )
    ex = Exchange(in_message=Message(body=None, headers={}))
    await proc.process(ex, _ctx())
    assert ex.status == ExchangeStatus.failed


def test_composed_to_spec_returns_none() -> None:
    """ComposedMessage не сериализуется (callable splitter/aggregator)."""
    proc = ComposedMessageProcessor(
        splitter=_split_list,
        processors=[_DoubleProcessor()],
        aggregator=_aggregate_sum,
    )
    assert proc.to_spec() is None
