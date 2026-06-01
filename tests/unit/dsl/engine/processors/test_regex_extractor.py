"""Unit-тесты RegexExtractorProcessor — Wave [wave:s5/k3-w1-processor-pack-1]."""

# ruff: noqa: S101

from __future__ import annotations

import re
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.regex_extractor import (
    RegexExtractorProcessor,
)


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


@pytest.fixture(autouse=True)
def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "proc_regex_extractor", True)


@pytest.mark.asyncio
async def test_extract_named_groups_first() -> None:
    proc = RegexExtractorProcessor(
        pattern=r"order_(?P<id>\d+)_(?P<status>\w+)",
        source="body",
        to="body.parsed",
        mode="first_named",
    )
    exchange = _ex("order_42_paid")

    await proc.process(exchange, AsyncMock())

    assert exchange.in_message.body["parsed"] == {"id": "42", "status": "paid"}


@pytest.mark.asyncio
async def test_extract_all_findall() -> None:
    proc = RegexExtractorProcessor(
        pattern=r"\d+",
        source="body",
        to="body.numbers",
        mode="all",
    )
    exchange = _ex("a1 b22 c333")

    await proc.process(exchange, AsyncMock())

    assert exchange.in_message.body["numbers"] == ["1", "22", "333"]


@pytest.mark.asyncio
async def test_flags_ignore_case() -> None:
    proc = RegexExtractorProcessor(
        pattern=r"ERROR: (?P<msg>\w+)",
        source="body",
        to="body.parsed",
        mode="first_named",
        flags=re.IGNORECASE,
    )
    exchange = _ex("error: timeout")

    await proc.process(exchange, AsyncMock())

    assert exchange.in_message.body["parsed"] == {"msg": "timeout"}


@pytest.mark.asyncio
async def test_skipped_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "proc_regex_extractor", False)
    proc = RegexExtractorProcessor(pattern=r"\d+", to="body.x")
    exchange = _ex("a1 b2")

    await proc.process(exchange, AsyncMock())

    assert exchange.properties.get("regex_extractor_status") == "skipped"
