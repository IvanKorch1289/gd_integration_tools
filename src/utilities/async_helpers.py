"""Асинхронные helper'ы общего назначения."""

from __future__ import annotations

__all__ = ("AsyncChunkIterator",)


class AsyncChunkIterator:
    """Преобразует list[bytes] в `async`-итератор для streaming-ответов."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.index = 0

    def __aiter__(self) -> "AsyncChunkIterator":
        return self

    async def __anext__(self) -> bytes:
        try:
            chunk = self.chunks[self.index]
        except IndexError as exc:
            raise StopAsyncIteration from exc
        self.index += 1
        return chunk
