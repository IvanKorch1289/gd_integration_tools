"""Smoke-тесты LangMemService: default-OFF, recall с mock-сессией."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.services.ai.langmem_service import (
    LangMemDisabled,
    LangMemService,
)


def test_langmem_disabled_by_default() -> None:
    svc = LangMemService(enabled=False)
    assert svc._enabled is False


@pytest.mark.asyncio
async def test_add_episodic_raises_when_disabled() -> None:
    svc = LangMemService(enabled=False)
    with pytest.raises(LangMemDisabled):
        await svc.add_episodic(session_id="s1", role="user", content="hi")


@pytest.mark.asyncio
async def test_add_semantic_requires_embedder_and_client() -> None:
    svc = LangMemService(enabled=True)
    with pytest.raises(LangMemDisabled):
        await svc.add_semantic(text="fact")


@pytest.mark.asyncio
async def test_add_semantic_upserts_with_embedder() -> None:
    embedder = type("E", (), {})()
    embedder.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    client = type("C", (), {})()
    client.upsert = AsyncMock(return_value=None)
    svc = LangMemService(
        enabled=True,
        qdrant_client=client,
        embedder=embedder,
        qdrant_collection="langmem_semantic",
    )
    pid = await svc.add_semantic(text="fact about X", tenant="t1")
    assert isinstance(pid, str) and len(pid) > 0
    client.upsert.assert_awaited_once()
    embedder.embed.assert_awaited_once_with(["fact about X"])


@pytest.mark.asyncio
async def test_recall_unknown_kind_raises() -> None:
    svc = LangMemService(enabled=True, session_factory=MagicMock())
    with pytest.raises(ValueError):
        await svc.recall(kind="invalid")
