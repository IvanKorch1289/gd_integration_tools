"""Тесты UnifiedMemoryGateway.recall_mem0 (Wave 4)."""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.services.ai.memory_gateway import UnifiedMemoryGateway


@pytest.mark.asyncio
async def test_recall_mem0_returns_empty_when_not_configured() -> None:
    """При отсутствии mem0 возвращает []."""
    gateway = UnifiedMemoryGateway(short_term=AsyncMock())
    result = await gateway.recall_mem0(
        tenant_id="t1", session_id="s1", query="hello"
    )
    assert result == []


@pytest.mark.asyncio
async def test_recall_mem0_delegates_to_backend() -> None:
    """recall_mem0 делегирует в Mem0MemoryAdapter.recall."""
    mem0 = AsyncMock()
    mem0.recall.return_value = [
        {"value": "fact1", "score": 0.9, "metadata": {"id": "1"}}
    ]
    gateway = UnifiedMemoryGateway(short_term=AsyncMock(), mem0=mem0)
    result = await gateway.recall_mem0(
        tenant_id="t1", session_id="s1", query="hello", top_k=3
    )
    assert len(result) == 1
    assert result[0].content == "fact1"
    assert result[0].confidence == 0.9
    mem0.recall.assert_awaited_once_with("t1:s1", "hello", k=3)
