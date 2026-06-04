"""Tests for src.backend.core.utils.async_helpers."""

from __future__ import annotations

import pytest

from src.backend.core.utils.async_helpers import AsyncChunkIterator


@pytest.mark.unit
class TestAsyncChunkIterator:
    """Tests for AsyncChunkIterator."""

    @pytest.mark.asyncio
    async def test_empty_chunks(self) -> None:
        it = AsyncChunkIterator([])
        chunks = []
        async for chunk in it:
            chunks.append(chunk)
        assert chunks == []

    @pytest.mark.asyncio
    async def test_single_chunk(self) -> None:
        it = AsyncChunkIterator([b"hello"])
        chunks = []
        async for chunk in it:
            chunks.append(chunk)
        assert chunks == [b"hello"]

    @pytest.mark.asyncio
    async def test_multiple_chunks(self) -> None:
        it = AsyncChunkIterator([b"hello", b" ", b"world"])
        chunks = []
        async for chunk in it:
            chunks.append(chunk)
        assert chunks == [b"hello", b" ", b"world"]

    @pytest.mark.asyncio
    async def test_aiter_returns_self(self) -> None:
        it = AsyncChunkIterator([b"x"])
        assert it.__aiter__() is it

    @pytest.mark.asyncio
    async def test_index_advances(self) -> None:
        it = AsyncChunkIterator([b"a", b"b"])
        assert it.index == 0
        await it.__anext__()
        assert it.index == 1
        await it.__anext__()
        assert it.index == 2

    @pytest.mark.asyncio
    async def test_raises_stop_async_iteration(self) -> None:
        it = AsyncChunkIterator([b"a"])
        await it.__anext__()
        with pytest.raises(StopAsyncIteration):
            await it.__anext__()
