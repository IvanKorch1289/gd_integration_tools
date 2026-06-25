"""Tests for streaming body hash (S171 M5 proposal #3).

Fixes OOM risk in data_masking.py which buffers entire response body
in memory for hash computation.
"""
from __future__ import annotations
import hashlib
import io
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestStreamingBodyHasher:
    def test_init_creates_hasher(self) -> None:
        from src.backend.entrypoints.middlewares._streaming_hash import StreamingBodyHasher
        h = StreamingBodyHasher()
        assert h is not None
        assert h.finalize() == hashlib.sha256(b"").hexdigest()

    def test_update_accumulates(self) -> None:
        from src.backend.entrypoints.middlewares._streaming_hash import StreamingBodyHasher
        h = StreamingBodyHasher()
        h.update(b"hello ")
        h.update(b"world")
        assert h.finalize() == hashlib.sha256(b"hello world").hexdigest()

    def test_finalize_returns_prefix_when_requested(self) -> None:
        from src.backend.entrypoints.middlewares._streaming_hash import StreamingBodyHasher
        h = StreamingBodyHasher()
        h.update(b"x" * 1000)
        result = h.finalize(prefix_len=16)
        assert len(result) == 16
        # Must match sha256(b'x'*1000)[:16]
        expected = hashlib.sha256(b"x" * 1000).hexdigest()[:16]
        assert result == expected

    def test_etag_format(self) -> None:
        from src.backend.entrypoints.middlewares._streaming_hash import StreamingBodyHasher
        h = StreamingBodyHasher()
        h.update(b"payload")
        etag = h.etag()
        assert etag.startswith('"') and etag.endswith('"')

    @pytest.mark.asyncio
    async def test_hash_stream_chunks(self) -> None:
        """Хеширует поток чанков без буферизации всего body."""
        from src.backend.entrypoints.middlewares._streaming_hash import hash_stream

        async def chunk_iter():
            yield b"chunk1-"
            yield b"chunk2-"
            yield b"chunk3"

        result = await hash_stream(chunk_iter())
        expected = hashlib.sha256(b"chunk1-chunk2-chunk3").hexdigest()
        assert result == expected

    @pytest.mark.asyncio
    async def test_hash_stream_returns_prefix(self) -> None:
        from src.backend.entrypoints.middlewares._streaming_hash import hash_stream

        async def chunk_iter():
            yield b"abc" * 100

        result = await hash_stream(chunk_iter(), prefix_len=8)
        assert len(result) == 8
