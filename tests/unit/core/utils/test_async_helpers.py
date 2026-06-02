"""T-P0.1.10: unit-тесты для core/utils/async_helpers.py (AsyncChunkIterator).

Coverage: async_helpers.py 40% → 100% через тестирование:
- __init__ (state)
- __aiter__ (returns self)
- __anext__ (sequential, StopAsyncIteration at end)
- async for integration
"""

from __future__ import annotations

import pytest

from src.backend.core.utils.async_helpers import AsyncChunkIterator


class TestInit:
    def test_stores_chunks(self) -> None:
        it = AsyncChunkIterator([b"a", b"b"])
        assert it.chunks == [b"a", b"b"]
        assert it.index == 0

    def test_empty_chunks(self) -> None:
        it = AsyncChunkIterator([])
        assert it.chunks == []
        assert it.index == 0


class TestAiter:
    def test_returns_self(self) -> None:
        it = AsyncChunkIterator([b"x"])
        assert it.__aiter__() is it


class TestAnext:
    @pytest.mark.asyncio
    async def test_returns_sequential_chunks(self) -> None:
        it = AsyncChunkIterator([b"a", b"b", b"c"])
        assert await it.__anext__() == b"a"
        assert await it.__anext__() == b"b"
        assert await it.__anext__() == b"c"

    @pytest.mark.asyncio
    async def test_raises_at_end(self) -> None:
        it = AsyncChunkIterator([b"only"])
        await it.__anext__()
        with pytest.raises(StopAsyncIteration):
            await it.__anext__()

    @pytest.mark.asyncio
    async def test_empty_raises_immediately(self) -> None:
        it = AsyncChunkIterator([])
        with pytest.raises(StopAsyncIteration):
            await it.__anext__()

    @pytest.mark.asyncio
    async def test_index_increments(self) -> None:
        it = AsyncChunkIterator([b"x", b"y"])
        assert it.index == 0
        await it.__anext__()
        assert it.index == 1
        await it.__anext__()
        assert it.index == 2


class TestAsyncFor:
    @pytest.mark.asyncio
    async def test_async_for_collects_all(self) -> None:
        chunks = [b"chunk1", b"chunk2", b"chunk3"]
        it = AsyncChunkIterator(chunks)
        collected: list[bytes] = []
        async for chunk in it:
            collected.append(chunk)
        assert collected == chunks

    @pytest.mark.asyncio
    async def test_async_for_empty_yields_nothing(self) -> None:
        it = AsyncChunkIterator([])
        collected: list[bytes] = []
        async for chunk in it:
            collected.append(chunk)
        assert collected == []


class TestAllExports:
    def test_all(self) -> None:
        from src.backend.core.utils import async_helpers as a

        assert a.__all__ == ("AsyncChunkIterator",)
