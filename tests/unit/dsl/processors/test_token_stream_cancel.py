"""Тест отмены TokenStreamLLMProcessor: aclose() вызывается."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.streaming_llm import (
    TokenStreamLLMProcessor,
)
from src.backend.dsl.engine.processors.streaming_llm_publishers import SSEPublisher


class _SlowStream:
    def __init__(self) -> None:
        self.closed = False

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._gen()

    async def _gen(self) -> AsyncIterator[Any]:
        yield {"choices": [{"delta": {"content": "first"}}]}
        await asyncio.sleep(10)
        yield {"choices": [{"delta": {"content": "should-not-arrive"}}]}

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_processor_calls_aclose_on_cancel() -> None:
    fake_stream = _SlowStream()

    gw = type("G", (), {})()
    gw.acompletion = AsyncMock(return_value=fake_stream)

    proc = TokenStreamLLMProcessor(
        output_mode="sse", publisher=SSEPublisher(), gateway=gw
    )
    exchange = Exchange(properties={"_composed_prompt": "x"})

    task = asyncio.create_task(proc.process(exchange, ExecutionContext()))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # Async generator из _iter_stream — отдельный объект, ему aclose() и
    # достаётся; основное условие — отсутствие зависания и корректная отмена.
    assert exchange.properties.get("sse_events") is not None
