"""Unit-тесты collection processors: Collect, FindAll, GroupBy, OrElse +
Sprint 37 Foundation: Partition, Unique, Flatten, Intersect, Diff,
SumBy, MaxBy, MinBy, SortBy.

Покрывают поведение (не сериализацию round-trip).
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.eip.collection import (
    CollectProcessor,
    DiffProcessor,
    FindAllProcessor,
    FlattenProcessor,
    GroupByProcessor,
    IntersectProcessor,
    MaxByProcessor,
    MinByProcessor,
    OrElseProcessor,
    PartitionProcessor,
    SortByProcessor,
    SumByProcessor,
    UniqueProcessor,
)


def _ex(body: Any = None, headers: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers=headers or {}))


# =============================================================================
# CollectProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_collect_by_field_dict() -> None:
    proc = CollectProcessor(field="name")
    exchange = _ex([{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}])
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == ["Alice", "Bob"]


@pytest.mark.asyncio
async def test_collect_by_key_fn() -> None:
    proc = CollectProcessor(key_fn=lambda item: item["age"] * 2)
    exchange = _ex([{"age": 10}, {"age": 20}])
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == [20, 40]


@pytest.mark.asyncio
async def test_collect_non_list_noop() -> None:
    proc = CollectProcessor(field="x")
    exchange = _ex("not a list")
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == "not a list"


@pytest.mark.asyncio
async def test_collect_missing_field() -> None:
    proc = CollectProcessor(field="missing")
    exchange = _ex([{"a": 1}, {"b": 2}])
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == [None, None]


# =============================================================================
# FindAllProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_find_all_by_predicate() -> None:
    proc = FindAllProcessor(predicate=lambda item: item["age"] > 18)
    exchange = _ex([{"age": 20}, {"age": 16}, {"age": 30}])
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == [{"age": 20}, {"age": 30}]


@pytest.mark.asyncio
async def test_find_all_by_condition() -> None:
    proc = FindAllProcessor(condition="age > 18")
    exchange = _ex([{"age": 20}, {"age": 16}, {"age": 30}])
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == [{"age": 20}, {"age": 30}]


@pytest.mark.asyncio
async def test_find_all_non_list_noop() -> None:
    proc = FindAllProcessor(predicate=lambda x: True)
    exchange = _ex("text")
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == "text"


@pytest.mark.asyncio
async def test_find_all_empty_result() -> None:
    proc = FindAllProcessor(predicate=lambda item: item["active"])
    exchange = _ex([{"active": False}, {"active": False}])
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == []


# =============================================================================
# GroupByProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_group_by_field() -> None:
    proc = GroupByProcessor(field="category")
    exchange = _ex(
        [
            {"category": "A", "value": 1},
            {"category": "B", "value": 2},
            {"category": "A", "value": 3},
        ]
    )
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == {
        "A": [{"category": "A", "value": 1}, {"category": "A", "value": 3}],
        "B": [{"category": "B", "value": 2}],
    }


@pytest.mark.asyncio
async def test_group_by_key_fn() -> None:
    proc = GroupByProcessor(key_fn=lambda item: item["name"][0])
    exchange = _ex([{"name": "Alice"}, {"name": "Bob"}, {"name": "Anna"}])
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == {
        "A": [{"name": "Alice"}, {"name": "Anna"}],
        "B": [{"name": "Bob"}],
    }


@pytest.mark.asyncio
async def test_group_by_non_list_noop() -> None:
    proc = GroupByProcessor(field="x")
    exchange = _ex("text")
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == "text"


# =============================================================================
# OrElseProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_or_else_on_none() -> None:
    proc = OrElseProcessor(default="fallback")
    exchange = _ex(None)
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == "fallback"


@pytest.mark.asyncio
async def test_or_else_on_empty_list() -> None:
    proc = OrElseProcessor(default=["default"])
    exchange = _ex([])
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == ["default"]


@pytest.mark.asyncio
async def test_or_else_on_empty_string() -> None:
    proc = OrElseProcessor(default="N/A")
    exchange = _ex("")
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == "N/A"


@pytest.mark.asyncio
async def test_or_else_on_empty_dict() -> None:
    proc = OrElseProcessor(default={"default": True})
    exchange = _ex({})
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == {"default": True}


@pytest.mark.asyncio
async def test_or_else_preserve_value() -> None:
    proc = OrElseProcessor(default="fallback")
    exchange = _ex([1, 2, 3])
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == [1, 2, 3]


# =============================================================================
# PartitionProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_partition_by_predicate() -> None:
    proc = PartitionProcessor(predicate=lambda item: item["age"] >= 18)
    exchange = _ex([{"age": 20}, {"age": 16}, {"age": 30}])
    await proc.process(exchange, None)  # type: ignore[arg-type]
    matched, unmatched = exchange.out_message.body
    assert matched == [{"age": 20}, {"age": 30}]
    assert unmatched == [{"age": 16}]


@pytest.mark.asyncio
async def test_partition_by_field() -> None:
    proc = PartitionProcessor(field="active")
    exchange = _ex([{"active": True}, {"active": False}, {"active": 1}])
    await proc.process(exchange, None)  # type: ignore[arg-type]
    matched, unmatched = exchange.out_message.body
    assert matched == [{"active": True}, {"active": 1}]
    assert unmatched == [{"active": False}]


@pytest.mark.asyncio
async def test_partition_non_list_noop() -> None:
    proc = PartitionProcessor(predicate=lambda x: True)
    exchange = _ex("text")
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == "text"


# =============================================================================
# UniqueProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_unique_by_field() -> None:
    proc = UniqueProcessor(field="email")
    exchange = _ex(
        [
            {"email": "a@x.com", "v": 1},
            {"email": "b@x.com", "v": 2},
            {"email": "a@x.com", "v": 3},
        ]
    )
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == [
        {"email": "a@x.com", "v": 1},
        {"email": "b@x.com", "v": 2},
    ]


@pytest.mark.asyncio
async def test_unique_by_key_fn() -> None:
    proc = UniqueProcessor(key_fn=lambda item: item["email"].lower())
    exchange = _ex([{"email": "A@X.COM"}, {"email": "a@x.com"}, {"email": "B@X.COM"}])
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == [{"email": "A@X.COM"}, {"email": "B@X.COM"}]


@pytest.mark.asyncio
async def test_unique_non_list_noop() -> None:
    proc = UniqueProcessor(field="x")
    exchange = _ex("text")
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == "text"


# =============================================================================
# FlattenProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_flatten_depth_1() -> None:
    proc = FlattenProcessor(depth=1)
    exchange = _ex([[1, 2], [3, 4]])
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_flatten_depth_2() -> None:
    proc = FlattenProcessor(depth=2)
    exchange = _ex([[[1, 2]], [[3, 4]]])
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_flatten_non_list_noop() -> None:
    proc = FlattenProcessor(depth=1)
    exchange = _ex("text")
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == "text"


# =============================================================================
# IntersectProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_intersect() -> None:
    proc = IntersectProcessor(other=[2, 3, 4])
    exchange = _ex([1, 2, 3])
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == [2, 3]


@pytest.mark.asyncio
async def test_intersect_non_list_noop() -> None:
    proc = IntersectProcessor(other=[1])
    exchange = _ex("text")
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == "text"


# =============================================================================
# DiffProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_diff() -> None:
    proc = DiffProcessor(other=[2, 4])
    exchange = _ex([1, 2, 3])
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == [1, 3]


@pytest.mark.asyncio
async def test_diff_non_list_noop() -> None:
    proc = DiffProcessor(other=[1])
    exchange = _ex("text")
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == "text"


# =============================================================================
# SumByProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_sum_by() -> None:
    proc = SumByProcessor(field="amount")
    exchange = _ex([{"amount": 10}, {"amount": 20.5}, {"amount": None}])
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == 30.5


@pytest.mark.asyncio
async def test_sum_by_non_list_noop() -> None:
    proc = SumByProcessor(field="x")
    exchange = _ex("text")
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == "text"


# =============================================================================
# MaxByProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_max_by() -> None:
    proc = MaxByProcessor(field="score")
    exchange = _ex([{"score": 10}, {"score": 50}, {"score": 30}])
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == {"score": 50}


@pytest.mark.asyncio
async def test_max_by_non_list_noop() -> None:
    proc = MaxByProcessor(field="x")
    exchange = _ex("text")
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == "text"


@pytest.mark.asyncio
async def test_max_by_empty_list_noop() -> None:
    proc = MaxByProcessor(field="x")
    exchange = _ex([])
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == []


# =============================================================================
# MinByProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_min_by() -> None:
    proc = MinByProcessor(field="price")
    exchange = _ex([{"price": 100}, {"price": 20}, {"price": 50}])
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == {"price": 20}


@pytest.mark.asyncio
async def test_min_by_non_list_noop() -> None:
    proc = MinByProcessor(field="x")
    exchange = _ex("text")
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == "text"


# =============================================================================
# SortByProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_sort_by_asc() -> None:
    proc = SortByProcessor(field="name")
    exchange = _ex([{"name": "Charlie"}, {"name": "Alice"}, {"name": "Bob"}])
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == [
        {"name": "Alice"},
        {"name": "Bob"},
        {"name": "Charlie"},
    ]


@pytest.mark.asyncio
async def test_sort_by_reverse() -> None:
    proc = SortByProcessor(field="value", reverse=True)
    exchange = _ex([{"value": 10}, {"value": 30}, {"value": 20}])
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == [{"value": 30}, {"value": 20}, {"value": 10}]


@pytest.mark.asyncio
async def test_sort_by_non_list_noop() -> None:
    proc = SortByProcessor(field="x")
    exchange = _ex("text")
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.out_message.body == "text"
