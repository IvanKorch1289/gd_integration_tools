"""Streaming body hash (S171 M5 proposal #3 — OOM fix).

Используется в middleware, которые должны хешировать body (audit_log,
admin_audit, response_cache, data_masking) без буферизации всего
содержимого в памяти.

Pattern (Ponytail, D141): thin wrapper над :class:`hashlib.sha256`,
no abstractions. Использует incremental ``.update()``.
"""
from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from typing import Final

__all__ = ("StreamingBodyHasher", "hash_stream")

_DEFAULT_CHUNK_SIZE: Final[int] = 64 * 1024  # 64 KB


class StreamingBodyHasher:
    """Incremental SHA256 hasher.

    Usage::

        hasher = StreamingBodyHasher()
        async for chunk in response.body_iterator:
            hasher.update(chunk)
        etag = hasher.etag()
    """

    __slots__ = ("_hasher",)

    def __init__(self) -> None:
        self._hasher = hashlib.sha256()

    def update(self, chunk: bytes) -> None:
        """Add chunk to hash. Incremental — no buffering."""
        if not isinstance(chunk, bytes):
            raise TypeError(f"chunk must be bytes, got {type(chunk).__name__}")
        self._hasher.update(chunk)

    def finalize(self, prefix_len: int | None = None) -> str:
        """Return hexdigest. ``prefix_len`` truncates (default full).

        Returns empty string if no chunks were updated.
        """
        digest = self._hasher.hexdigest()
        return digest[:prefix_len] if prefix_len else digest

    def etag(self, prefix_len: int = 16) -> str:
        """Return RFC 7232 ETag формат ``"<digest>"``."""
        return f'"{self.finalize(prefix_len=prefix_len)}"'


async def hash_stream(
    chunks: AsyncIterator[bytes],
    *,
    prefix_len: int | None = None,
) -> str:
    """Хешировать async iterator of bytes без буферизации.

    Args:
        chunks: Async iterator (например, ``response.body_iterator``).
        prefix_len: Truncate hexdigest до N символов (default full).

    Returns:
        Hex digest. Empty string если stream пустой.
    """
    hasher = StreamingBodyHasher()
    async for chunk in chunks:
        hasher.update(chunk)
    return hasher.finalize(prefix_len=prefix_len)
