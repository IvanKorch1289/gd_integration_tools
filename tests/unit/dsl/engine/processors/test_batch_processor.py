"""Unit-тесты ``BatchWindowProcessor`` (S13 K3 W1).

Покрывают:

* flush по достижению ``max_size``;
* flush по таймауту;
* группировка по ``header.*`` / ``body.*`` / ``property.*``;
* отдельные счётчики per-group (буфер не пересекается);
* concurrency safety (asyncio.gather × N).
"""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.patterns import BatchWindowProcessor


def _ex(body: Any = None, headers: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers=headers or {}))


@pytest.mark.asyncio
async def test_flush_by_size() -> None:
    proc = BatchWindowProcessor(window_seconds=60.0, max_size=3)
    ctx = AsyncMock()
    e1, e2, e3 = _ex(body={"i": 1}), _ex(body={"i": 2}), _ex(body={"i": 3})
    for ex in (e1, e2, e3):
        await proc.process(ex, ctx)
    out = e3.out_message
    assert out is not None
    assert isinstance(out.body, list)
    assert len(out.body) == 3
    assert e3.properties["batch_size"] == 3
    assert e3.properties["batch_flush_reason"] == "size_reached"


@pytest.mark.asyncio
async def test_no_flush_when_under_size() -> None:
    proc = BatchWindowProcessor(window_seconds=60.0, max_size=10)
    ctx = AsyncMock()
    ex = _ex(body={"i": 1})
    await proc.process(ex, ctx)
    assert ex.stopped
    assert ex.properties["buffer_size"] == 1
    assert ex.properties["batched"] is False


@pytest.mark.asyncio
async def test_flush_by_timeout() -> None:
    proc = BatchWindowProcessor(window_seconds=0.02, max_size=100)
    ctx = AsyncMock()
    ex1 = _ex(body={"i": 1})
    await proc.process(ex1, ctx)
    assert ex1.stopped
    await asyncio.sleep(0.05)
    ex2 = _ex(body={"i": 2})
    await proc.process(ex2, ctx)
    assert ex2.out_message is not None
    assert ex2.properties["batch_flush_reason"] == "timeout_reached"
    assert len(ex2.out_message.body) == 2


@pytest.mark.asyncio
async def test_group_by_header_isolates_buffers() -> None:
    proc = BatchWindowProcessor(
        window_seconds=60.0, max_size=2, group_by="header.tenant_id"
    )
    ctx = AsyncMock()
    # Тенант A — 2 события → flush
    ex_a1 = _ex(body={"a": 1}, headers={"tenant_id": "A"})
    ex_a2 = _ex(body={"a": 2}, headers={"tenant_id": "A"})
    # Тенант B — 1 событие → НЕ flush
    ex_b1 = _ex(body={"b": 1}, headers={"tenant_id": "B"})

    await proc.process(ex_a1, ctx)
    await proc.process(ex_b1, ctx)
    await proc.process(ex_a2, ctx)

    assert ex_a2.out_message is not None
    assert len(ex_a2.out_message.body) == 2
    assert ex_a2.properties["batch_group"] == "A"

    # Тенант B остался в буфере
    assert ex_b1.stopped
    assert ex_b1.properties["batch_group"] == "B"


@pytest.mark.asyncio
async def test_group_by_body_path() -> None:
    proc = BatchWindowProcessor(window_seconds=60.0, max_size=2, group_by="body.region")
    ctx = AsyncMock()
    e1 = _ex(body={"region": "EU"})
    e2 = _ex(body={"region": "EU"})
    e3 = _ex(body={"region": "US"})
    await proc.process(e1, ctx)
    await proc.process(e3, ctx)
    await proc.process(e2, ctx)
    assert e2.out_message is not None
    assert e2.properties["batch_group"] == "EU"
    assert e3.stopped


@pytest.mark.asyncio
async def test_concurrency_safety() -> None:
    proc = BatchWindowProcessor(window_seconds=60.0, max_size=10)
    ctx = AsyncMock()
    exchanges = [_ex(body={"i": i}) for i in range(50)]

    async def _run(ex: Exchange[Any]) -> None:
        await proc.process(ex, ctx)

    await asyncio.gather(*(_run(ex) for ex in exchanges))
    flushed = [ex for ex in exchanges if ex.out_message is not None]
    pending = [ex for ex in exchanges if ex.stopped]
    # 50 сообщений / 10 = 5 батчей (1 flushed exchange на батч) + 45 pending.
    assert len(flushed) + len(pending) == 50
    # В сумме всех батчей — 50 уникальных messages.
    total_in_batches = sum(len(ex.out_message.body) for ex in flushed)
    assert total_in_batches == 5 * 10


@pytest.mark.asyncio
async def test_default_group_falls_back_to_default() -> None:
    proc = BatchWindowProcessor(
        window_seconds=60.0, max_size=2, group_by="header.x_missing"
    )
    ctx = AsyncMock()
    e1 = _ex(body={"i": 1})
    e2 = _ex(body={"i": 2})
    await proc.process(e1, ctx)
    await proc.process(e2, ctx)
    assert e2.out_message is not None
    assert e2.properties["batch_group"] == "_default"
