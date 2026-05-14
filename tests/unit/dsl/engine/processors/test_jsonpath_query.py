"""Unit-тесты JsonPathProcessor — Wave [wave:s5/k3-w1-processor-pack-1]."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.jsonpath_query import JsonPathProcessor


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


@pytest.fixture(autouse=True)
def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "proc_jsonpath", True)


@pytest.mark.asyncio
async def test_extract_all_matches() -> None:
    pytest.importorskip("jsonpath_ng")
    proc = JsonPathProcessor("$.users[*].name", to="body.names", mode="all")
    exchange = _ex(
        {"users": [{"name": "Alice"}, {"name": "Bob"}]}
    )

    await proc.process(exchange, AsyncMock())

    assert exchange.in_message.body["names"] == ["Alice", "Bob"]


@pytest.mark.asyncio
async def test_extract_first_with_default() -> None:
    pytest.importorskip("jsonpath_ng")
    proc = JsonPathProcessor(
        "$.missing", to="body.x", mode="first", default="fallback"
    )
    exchange = _ex({"users": [{"name": "Alice"}]})

    await proc.process(exchange, AsyncMock())

    assert exchange.in_message.body["x"] == "fallback"


@pytest.mark.asyncio
async def test_skipped_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "proc_jsonpath", False)
    proc = JsonPathProcessor("$.x", to="body.y")
    exchange = _ex({"x": 1})

    await proc.process(exchange, AsyncMock())

    assert exchange.properties.get("jsonpath_status") == "skipped"
