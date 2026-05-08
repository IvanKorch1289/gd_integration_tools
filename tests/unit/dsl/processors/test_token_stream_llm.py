"""Тесты TokenStreamLLMProcessor: 3 chunks через mock-gateway → SSE events."""

from __future__ import annotations

from typing import Any, AsyncIterator
from unittest.mock import AsyncMock

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.streaming_llm import (
    TokenStreamLLMProcessor,
)
from src.backend.dsl.engine.processors.streaming_llm_publishers import SSEPublisher


class _FakeStream:
    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self._chunks = chunks
        self._closed = False

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._gen()

    async def _gen(self) -> AsyncIterator[Any]:
        for c in self._chunks:
            yield c

    async def aclose(self) -> None:
        self._closed = True


def _gateway_with_chunks(chunks: list[dict[str, Any]]) -> Any:
    gw = type("G", (), {})()
    gw.acompletion = AsyncMock(return_value=_FakeStream(chunks))
    return gw


@pytest.mark.asyncio
async def test_three_chunks_streamed_to_sse_publisher() -> None:
    chunks = [
        {"choices": [{"delta": {"content": "Hello"}}]},
        {"choices": [{"delta": {"content": " world"}}]},
        {"choices": [{"delta": {"content": "!"}, "finish_reason": "stop"}]},
    ]
    gw = _gateway_with_chunks(chunks)
    proc = TokenStreamLLMProcessor(
        output_mode="sse",
        publisher=SSEPublisher(),
        gateway=gw,
    )
    exchange = Exchange(properties={"_composed_prompt": "say hi"})
    await proc.process(exchange, ExecutionContext())

    events = exchange.properties["sse_events"]
    deltas = [e["data"] for e in events if e["event"] == "delta"]
    done = [e for e in events if e["event"] == "done"]
    assert deltas == ["Hello", " world", "!"]
    assert done and done[0]["data"] == "stop"
    assert exchange.properties["llm.streamed_text"] == "Hello world!"


@pytest.mark.asyncio
async def test_invalid_output_mode_raises() -> None:
    with pytest.raises(ValueError):
        TokenStreamLLMProcessor(output_mode="grpc")


def test_normalize_chunk_dict_form() -> None:
    chunk = {"choices": [{"delta": {"content": "x"}, "finish_reason": None}]}
    norm = TokenStreamLLMProcessor._normalize_chunk(chunk)
    assert norm == {"delta": "x", "finish_reason": None}


def test_normalize_chunk_finish_reason() -> None:
    chunk = {"choices": [{"delta": {"content": ""}, "finish_reason": "length"}]}
    norm = TokenStreamLLMProcessor._normalize_chunk(chunk)
    assert norm["finish_reason"] == "length"


def test_to_spec_serializes_kwargs() -> None:
    proc = TokenStreamLLMProcessor(
        output_mode="ws", model="openai/gpt-4o-mini", chunk_size=4
    )
    spec = proc.to_spec()
    assert spec == {
        "token_stream_llm": {
            "output_mode": "ws",
            "prompt_property": "_composed_prompt",
            "model": "openai/gpt-4o-mini",
            "chunk_size": 4,
        }
    }
