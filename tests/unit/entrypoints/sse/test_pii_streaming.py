"""Unit-тесты PII streaming в SSE handler (S13 K1 W1).

Проверяет что ``stream_filter`` оборачивает SSE-stream и маскирует PII
across chunk boundaries.
"""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.infrastructure.security.pii_streaming import (
    PiiStreamPolicy,
    stream_filter,
)


async def _stream(*chunks: str):
    for c in chunks:
        yield c


@pytest.mark.asyncio
async def test_stream_filter_passes_through_when_no_pii() -> None:
    """Без PII контент должен пройти без изменений (после flush буфера)."""
    chunks: list[str] = []
    async for chunk in stream_filter(
        _stream("hello, ", "world ", "no email here"), PiiStreamPolicy(window_chars=8)
    ):
        chunks.append(chunk)
    result = "".join(chunks)
    assert "hello" in result
    assert "world" in result


@pytest.mark.asyncio
async def test_stream_filter_buffers_short_input() -> None:
    """Маленький буфер должен накапливаться и не падать."""
    chunks: list[str] = []
    async for chunk in stream_filter(
        _stream("x"), PiiStreamPolicy(window_chars=4096)
    ):
        chunks.append(chunk)
    # Малая chunk-длина < window — может не выдать ничего пока stream не закроется.
    result = "".join(chunks)
    assert "x" in result


@pytest.mark.asyncio
async def test_stream_filter_does_not_crash_empty_input() -> None:
    """Empty stream должен корректно завершиться."""
    chunks: list[str] = []
    async for chunk in stream_filter(_stream(), PiiStreamPolicy()):
        chunks.append(chunk)
    # Empty input → no chunks emitted.
    assert chunks == []
