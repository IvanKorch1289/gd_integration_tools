"""Unit-тесты DataStore processors."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.data_store import (
    DataStoreDeleteProcessor,
    DataStoreGetProcessor,
    DataStoreSetProcessor,
)


def _ex(body: Any = None, headers: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers=headers or {}))


@pytest.mark.asyncio
async def test_data_store_set() -> None:
    proc = DataStoreSetProcessor(key="foo", value="bar")
    exchange = _ex({})
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.properties["_data_store"]["foo"] == "bar"


@pytest.mark.asyncio
async def test_data_store_get_existing() -> None:
    exchange = _ex({})
    exchange.properties["_data_store"] = {"foo": "bar"}
    proc = DataStoreGetProcessor(key="foo", result_property="out")
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.properties["out"] == "bar"


@pytest.mark.asyncio
async def test_data_store_get_default() -> None:
    exchange = _ex({})
    proc = DataStoreGetProcessor(
        key="missing", default="fallback", result_property="out"
    )
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.properties["out"] == "fallback"


@pytest.mark.asyncio
async def test_data_store_delete() -> None:
    exchange = _ex({})
    exchange.properties["_data_store"] = {"foo": "bar"}
    proc = DataStoreDeleteProcessor(key="foo")
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert "foo" not in exchange.properties["_data_store"]


@pytest.mark.asyncio
async def test_data_store_delete_missing_noop() -> None:
    exchange = _ex({})
    proc = DataStoreDeleteProcessor(key="foo")
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert "_data_store" not in exchange.properties
