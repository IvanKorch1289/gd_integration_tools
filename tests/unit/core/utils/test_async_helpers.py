"""Tests for src.backend.core.utils.async_helpers."""

from __future__ import annotations

import pytest

from src.backend.core.utils.async_helpers import async_chunk_iterator


@pytest.mark.unit
class TestAsyncChunkIterator:
    """Tests for async_chunk_iterator."""

    @pytest.mark.asyncio
    async def test_empty_chunks(self) -> None:
        chunks = []
        async for chunk in async_chunk_iterator([]):
            chunks.append(chunk)
        assert chunks == []

    @pytest.mark.asyncio
    async def test_single_chunk(self) -> None:
        chunks = []
        async for chunk in async_chunk_iterator([b"hello"]):
            chunks.append(chunk)
        assert chunks == [b"hello"]

    @pytest.mark.asyncio
    async def test_multiple_chunks(self) -> None:
        chunks = []
        async for chunk in async_chunk_iterator([b"hello", b" ", b"world"]):
            chunks.append(chunk)
        assert chunks == [b"hello", b" ", b"world"]
