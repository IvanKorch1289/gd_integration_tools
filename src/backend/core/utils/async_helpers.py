"""Асинхронные helper'ы общего назначения."""

from __future__ import annotations

from collections.abc import AsyncIterator

__all__ = ("AsyncChunkIterator", "async_chunk_iterator")


class AsyncChunkIterator:
    """Преобразует list[bytes] в async-итератор для streaming-ответов.

    Используется в ASGI middlewares: ``response.body_iterator = AsyncChunkIterator(chunks)``.
    """

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.index = 0

    def __aiter__(self) -> AsyncChunkIterator:
        return self

    async def __anext__(self) -> bytes:
        try:
            chunk = self.chunks[self.index]
        except IndexError as exc:
            raise StopAsyncIteration from exc
        self.index += 1
        return chunk


# ponytail: convenience alias — async generator для caller sites
# которые предпочитают `async_chunk_iterator(chunks)` over `AsyncChunkIterator(chunks)`.
# Ceiling: O(n) memory (full list in memory). For true streaming use async-gen directly.
async def async_chunk_iterator(chunks: list[bytes]) -> AsyncIterator[bytes]:
    """Async generator: yields chunks from list."""
    for chunk in chunks:
        yield chunk
