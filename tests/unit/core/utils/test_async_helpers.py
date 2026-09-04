"""Tests for core/utils/async_helpers.py (S98 — coverage push)."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_async_chunk_iterator_yields_in_order() -> None:
    """async_chunk_iterator yields chunks in input order."""
    from src.backend.core.utils.async_helpers import async_chunk_iterator

    chunks = [b"hello", b" ", b"world"]
    result = []
    async for c in async_chunk_iterator(chunks):
        result.append(c)
    assert result == chunks


@pytest.mark.asyncio
async def test_async_chunk_iterator_empty() -> None:
    """async_chunk_iterator([]) yields nothing."""
    from src.backend.core.utils.async_helpers import async_chunk_iterator

    result = []
    async for c in async_chunk_iterator([]):
        result.append(c)
    assert result == []


@pytest.mark.asyncio
async def test_async_chunk_iterator_single_chunk() -> None:
    """async_chunk_iterator([b'x']) → yields one chunk."""
    from src.backend.core.utils.async_helpers import async_chunk_iterator

    result = []
    async for c in async_chunk_iterator([b"only"]):
        result.append(c)
    assert result == [b"only"]


@pytest.mark.asyncio
async def test_async_chunk_class_yields_chunks() -> None:
    """AsyncChunkIterator class: __aiter__ + __anext__ protocol."""
    from src.backend.core.utils.async_helpers import AsyncChunkIterator

    it = AsyncChunkIterator([b"a", b"b", b"c"])

    chunks = []
    async for c in it:
        chunks.append(c)
    assert chunks == [b"a", b"b", b"c"]


@pytest.mark.asyncio
async def test_async_chunk_class_raises_stop_after_exhaustion() -> None:
    """AsyncChunkIterator: raises StopAsyncIteration after exhausted."""
    from src.backend.core.utils.async_helpers import AsyncChunkIterator

    it = AsyncChunkIterator([b"only"])
    async for _ in it:
        pass
    with pytest.raises(StopAsyncIteration):
        await it.__anext__()


def test_async_chunk_iterator_default_index_zero() -> None:
    """AsyncChunkIterator: index starts at 0."""
    from src.backend.core.utils.async_helpers import AsyncChunkIterator

    it = AsyncChunkIterator([b"x"])
    assert it.index == 0
    assert it.chunks == [b"x"]


def test_async_helpers_module_dunder_all() -> None:
    """__all__ = ('AsyncChunkIterator', 'async_chunk_iterator')."""
    import src.backend.core.utils.async_helpers as mod

    assert mod.__all__ == ("AsyncChunkIterator", "async_chunk_iterator")
