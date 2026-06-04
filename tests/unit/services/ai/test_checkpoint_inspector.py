"""Тесты Sprint 11 K4 W4 — CheckpointInspector."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.services.ai.agents.checkpoint_inspector import (
    CheckpointInspector,
    CheckpointSnapshot,
    SessionInfo,
)


@pytest.mark.asyncio
async def test_list_sessions_returns_empty_without_wrapper() -> None:
    """Без saver_wrapper list возвращает []."""
    inspector = CheckpointInspector(saver_wrapper=None)
    sessions = await inspector.list_sessions()
    assert sessions == []


@pytest.mark.asyncio
async def test_list_sessions_returns_empty_when_disabled() -> None:
    """Wrapper с enabled=False тоже даёт [] (feature-flag off)."""
    wrapper = SimpleNamespace(enabled=False)
    inspector = CheckpointInspector(saver_wrapper=wrapper)
    sessions = await inspector.list_sessions()
    assert sessions == []


@pytest.mark.asyncio
async def test_get_state_returns_none_when_disabled() -> None:
    """get_state без enabled saver → None."""
    inspector = CheckpointInspector(saver_wrapper=None)
    snapshot = await inspector.get_state("session-x")
    assert snapshot is None


@pytest.mark.asyncio
async def test_get_state_uses_aget_tuple() -> None:
    """get_state вызывает saver.aget_tuple и оборачивает результат."""
    fake_saver = MagicMock()
    fake_saver.aget_tuple = AsyncMock(
        return_value=SimpleNamespace(
            config={"configurable": {"thread_id": "s1", "checkpoint_id": "ckpt-42"}},
            checkpoint={"ts": "2026-05-20T10:00:00Z", "data": {"x": 1}},
            metadata={"author": "test"},
        )
    )

    wrapper = MagicMock()
    wrapper.enabled = True
    wrapper.acquire = AsyncMock(return_value=fake_saver)

    inspector = CheckpointInspector(saver_wrapper=wrapper)
    snapshot = await inspector.get_state("s1")

    assert isinstance(snapshot, CheckpointSnapshot)
    assert snapshot.checkpoint_id == "ckpt-42"
    assert snapshot.state["data"] == {"x": 1}


@pytest.mark.asyncio
async def test_restore_returns_false_when_not_found() -> None:
    """restore → False если aget_tuple вернул None."""
    fake_saver = MagicMock()
    fake_saver.aget_tuple = AsyncMock(return_value=None)
    wrapper = MagicMock()
    wrapper.enabled = True
    wrapper.acquire = AsyncMock(return_value=fake_saver)
    inspector = CheckpointInspector(saver_wrapper=wrapper)

    ok = await inspector.restore("s1", "missing-ckpt")
    assert ok is False


@pytest.mark.asyncio
async def test_restore_returns_true_when_checkpoint_exists() -> None:
    """restore → True для существующего checkpoint."""
    fake_saver = MagicMock()
    fake_saver.aget_tuple = AsyncMock(return_value=SimpleNamespace(config={}))
    wrapper = MagicMock()
    wrapper.enabled = True
    wrapper.acquire = AsyncMock(return_value=fake_saver)
    inspector = CheckpointInspector(saver_wrapper=wrapper)

    ok = await inspector.restore("s1", "ckpt-1")
    assert ok is True
