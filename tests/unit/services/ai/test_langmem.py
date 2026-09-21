"""Stream E.7: тесты разделённой LangMem (episodic / semantic / procedural).

Используются in-process mock'и для session_factory (контекстный
менеджер с AsyncMock для add/commit/refresh). Реальная PG/Qdrant
интеграция помечена ``@pytest.mark.integration`` и пропускается
при отсутствии инфраструктуры.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.services.ai.memory.langmem import (
    EpisodicMemory,
    ProceduralMemory,
    SemanticMemory,
)


def _make_session_factory() -> tuple[Any, Any]:
    """Возвращает (factory, session) — session это MagicMock с записанными вызовами."""
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "id", 1))
    session.execute = AsyncMock()

    @asynccontextmanager
    async def factory():
        yield session

    return factory, session


@pytest.mark.asyncio
async def test_episodic_add_writes_row() -> None:
    """EpisodicMemory.add вызывает session.add + commit + refresh."""
    factory, session = _make_session_factory()
    mem = EpisodicMemory(session_factory=factory)
    row_id = await mem.add(
        session_id="s1",
        role="user",
        content="hi",
        tenant="acme",
        meta={"source": "test"},
    )
    assert row_id == 1
    session.add.assert_called_once()
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_procedural_add_writes_row() -> None:
    """ProceduralMemory.add создаёт запись с steps."""
    factory, session = _make_session_factory()
    mem = ProceduralMemory(session_factory=factory)
    row_id = await mem.add(
        name="run-tests",
        description="запустить unit-тесты",
        steps={"1": "make lint", "2": "make test"},
    )
    assert row_id == 1
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_semantic_add_upserts_via_qdrant() -> None:
    """SemanticMemory.add embed'ит и upsert'ит в qdrant."""
    embedder = type("E", (), {})()
    embedder.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    client = type("C", (), {})()
    client.upsert = AsyncMock(return_value=None)

    mem = SemanticMemory(
        qdrant_client=client, embedder=embedder, collection="langmem_semantic"
    )
    assert mem.is_configured is True

    pid = await mem.add(text="fact about X", tenant="t1", meta={"src": "doc1"})
    assert isinstance(pid, str) and len(pid) > 0
    embedder.embed.assert_awaited_once_with(["fact about X"])
    client.upsert.assert_awaited_once()
    call = client.upsert.await_args
    assert call.kwargs["collection"] == "langmem_semantic"
    assert call.kwargs["points"][0]["payload"]["text"] == "fact about X"
    assert call.kwargs["points"][0]["payload"]["tenant"] == "t1"


@pytest.mark.asyncio
async def test_semantic_unconfigured_raises() -> None:
    """SemanticMemory без client/embedder поднимает RuntimeError."""
    mem = SemanticMemory()
    assert mem.is_configured is False
    with pytest.raises(RuntimeError):
        await mem.add(text="x")


# --- Integration (skip if PG/Qdrant unavailable) -------------------------


@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("LANGMEM_INTEGRATION_DSN"),
    reason="требуется LANGMEM_INTEGRATION_DSN + Qdrant; integration test",
)
@pytest.mark.asyncio
async def test_langmem_integration_pg_qdrant() -> None:
    """Integration smoke: реальный PG + Qdrant. Helper в conftest, если есть."""
    pytest.skip("integration harness не настроен; placeholder")
