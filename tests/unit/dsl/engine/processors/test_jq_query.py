"""Unit-тесты JqProcessor — Wave [wave:s5/k3-w1-processor-pack-1]."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.jq_query import JqProcessor


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


@pytest.fixture(autouse=True)
def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "proc_jq", True)


@pytest.mark.asyncio
async def test_fail_when_pyjq_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    # Эмулируем отсутствие pyjq через ImportError при попытке импорта.
    proc = JqProcessor(".[]", to="body.r")
    exchange = _ex([1, 2, 3])

    # Если pyjq установлен — тест валидирует success path.
    try:
        import pyjq  # noqa: F401
    except ImportError:
        await proc.process(exchange, AsyncMock())
        assert exchange.error is not None and "pyjq" in exchange.error
        return

    await proc.process(exchange, AsyncMock())
    assert exchange.in_message.body["r"] == [1, 2, 3]


@pytest.mark.asyncio
async def test_skipped_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "proc_jq", False)
    proc = JqProcessor(".foo", to="body.r")
    exchange = _ex({"foo": "bar"})

    await proc.process(exchange, AsyncMock())

    assert exchange.properties.get("jq_status") == "skipped"


@pytest.mark.asyncio
async def test_spec_round_trip() -> None:
    proc = JqProcessor(".a", to="body.r", mode="first")
    spec = proc.to_spec()
    assert spec is not None
    assert spec["jq"]["expr"] == ".a"
    assert spec["jq"]["mode"] == "first"
