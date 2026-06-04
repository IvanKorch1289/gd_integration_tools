"""Тесты LLMStreamingService (Wave D.3)."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock

import pytest

from src.backend.services.ai.streaming_service import (
    LLMStreamingService,
    StreamChunk,
    _normalize_chunk,
)


class _FakeStreamCM:
    """Имитация async-iterator стрима litellm."""

    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = list(chunks)
        self.aclosed = False

    def __aiter__(self) -> AsyncIterator[Any]:
        return self

    async def __anext__(self) -> Any:
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)

    async def aclose(self) -> None:
        self.aclosed = True


def _make_chunk(content: str = "", finish: str | None = None) -> dict[str, Any]:
    return {
        "choices": [
            {"delta": {"content": content} if content else {}, "finish_reason": finish}
        ]
    }


@pytest.mark.asyncio
async def test_astream_yields_normalized_chunks() -> None:
    chunks = [_make_chunk("Hello"), _make_chunk(" world"), _make_chunk(finish="stop")]
    gateway = type("G", (), {})()
    gateway.acompletion = AsyncMock(return_value=_FakeStreamCM(chunks))
    service = LLMStreamingService(gateway=gateway, chunk_size=1)

    received: list[StreamChunk] = []
    async for ch in service.astream([{"role": "user", "content": "hi"}]):
        received.append(ch)

    assert any(c.delta == "Hello" for c in received)
    assert any(c.delta == " world" for c in received)
    assert received[-1].finish_reason == "stop"


@pytest.mark.asyncio
async def test_astream_chunk_size_buffering() -> None:
    chunks = [
        _make_chunk("a"),
        _make_chunk("b"),
        _make_chunk("c"),
        _make_chunk(finish="stop"),
    ]
    gateway = type("G", (), {})()
    gateway.acompletion = AsyncMock(return_value=_FakeStreamCM(chunks))
    service = LLMStreamingService(gateway=gateway, chunk_size=2)

    received = []
    async for ch in service.astream([{"role": "user", "content": "x"}]):
        received.append(ch)
    deltas = [c.delta for c in received if c.delta]
    assert deltas == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_astream_fallback_when_bad_request() -> None:
    class BadRequestError(Exception):
        pass

    gateway = type("G", (), {})()
    response = {
        "choices": [{"message": {"content": "full-text"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    }

    async def _ac(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("stream"):
            raise BadRequestError("streaming not supported by provider")
        return response

    gateway.acompletion = _ac
    service = LLMStreamingService(gateway=gateway)

    out: list[StreamChunk] = []
    async for ch in service.astream([{"role": "user", "content": "x"}]):
        out.append(ch)
    assert len(out) == 1
    assert out[0].delta == "full-text"
    assert out[0].finish_reason == "stop"
    assert out[0].usage and out[0].usage["total_tokens"] == 3


@pytest.mark.asyncio
async def test_astream_cancellation_calls_aclose() -> None:
    """При CancelledError внутри astream() upstream stream закрывается через aclose."""

    class _SlowStream:
        def __init__(self) -> None:
            self.aclosed = False

        def __aiter__(self) -> AsyncIterator[Any]:
            return self

        async def __anext__(self) -> Any:
            await asyncio.sleep(10)  # бесконечно ждём, пока нас не отменят
            return _make_chunk("x")

        async def aclose(self) -> None:
            self.aclosed = True

    slow = _SlowStream()
    gateway = type("G", (), {})()
    gateway.acompletion = AsyncMock(return_value=slow)
    service = LLMStreamingService(gateway=gateway, chunk_size=1)

    async def _consumer() -> None:
        async for _ in service.astream([{"role": "user", "content": "x"}]):
            pass

    task = asyncio.create_task(_consumer())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert slow.aclosed is True


def test_normalize_chunk_extracts_delta_and_finish() -> None:
    result = _normalize_chunk(_make_chunk("hello", finish="stop"))
    assert result.delta == "hello"
    assert result.finish_reason == "stop"
