"""Unit-тесты sequencing processors: Resequencer."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.eip.sequencing import ResequencerProcessor


def _ex(body: Any = None, headers: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers=headers or {}))


@pytest.mark.asyncio
async def test_resequencer_emits_on_batch_size() -> None:
    """При достижении batch_size сообщения сортируются и выдаются."""
    proc = ResequencerProcessor(
        correlation_key=lambda ex: "corr1",
        sequence_field="seq",
        batch_size=3,
    )
    ctx = AsyncMock()

    e1 = _ex(body={"seq": 3, "data": "c"})
    await proc.process(e1, ctx)
    assert e1.properties.get("resequenced") is False
    assert e1.stopped is True

    e2 = _ex(body={"seq": 1, "data": "a"})
    await proc.process(e2, ctx)
    assert e2.properties.get("resequenced") is False

    e3 = _ex(body={"seq": 2, "data": "b"})
    await proc.process(e3, ctx)
    assert e3.properties.get("resequenced") is True
    assert e3.out_message.body == [{"seq": 1, "data": "a"}, {"seq": 2, "data": "b"}, {"seq": 3, "data": "c"}]


@pytest.mark.asyncio
async def test_resequencer_uses_getattr() -> None:
    """Если body не dict, используется getattr."""

    class Item:
        def __init__(self, seq: int, val: str) -> None:
            self.seq = seq
            self.val = val

    proc = ResequencerProcessor(
        correlation_key=lambda ex: "corr1",
        sequence_field="seq",
        batch_size=2,
    )
    ctx = AsyncMock()

    e1 = _ex(body=Item(2, "second"))
    await proc.process(e1, ctx)
    assert e1.properties.get("resequenced") is False

    e2 = _ex(body=Item(1, "first"))
    await proc.process(e2, ctx)
    assert e2.properties.get("resequenced") is True
    assert [item.seq for item in e2.out_message.body] == [1, 2]
    assert [item.val for item in e2.out_message.body] == ["first", "second"]


@pytest.mark.asyncio
async def test_resequencer_max_keys_eviction() -> None:
    """При превышении _MAX_KEYS удаляется самый старый буфер."""
    proc = ResequencerProcessor(
        correlation_key=lambda ex: ex.meta.exchange_id,
        sequence_field="seq",
        batch_size=10,
    )
    ctx = AsyncMock()
    proc._MAX_KEYS = 2

    for i in range(3):
        e = _ex(body={"seq": i, "data": i})
        e.meta.exchange_id = f"ex{i}"
        await proc.process(e, ctx)

    assert len(proc._buffers) <= 2
