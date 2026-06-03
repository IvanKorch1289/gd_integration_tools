"""Unit-тесты collection processors: Collect, FindAll, GroupBy, OrElse.

Покрывают поведение (не сериализацию round-trip).
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.eip.collection import (
    CollectProcessor,
    FindAllProcessor,
    GroupByProcessor,
    OrElseProcessor,
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
    exchange = _ex([
        {"category": "A", "value": 1},
        {"category": "B", "value": 2},
        {"category": "A", "value": 3},
    ])
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
