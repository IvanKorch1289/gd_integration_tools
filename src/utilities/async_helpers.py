"""Асинхронные helper'ы общего назначения."""

from __future__ import annotations

from typing import Any

__all__ = ("AsyncChunkIterator", "safe_get")


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


async def safe_get(data: dict[str, Any], keys: str, default: Any = None) -> Any:
    """Безопасный доступ к вложенным dict-ключам через dot-нотацию."""
    current: Any = data
    for key in keys.split("."):
        if not isinstance(current, dict):
            return default
        if key not in current:
            return default
        current = current[key]
    return current if current is not None else default
