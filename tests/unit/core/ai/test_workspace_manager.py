"""Тесты :class:`AIWorkspaceManager` (V15 R-V15-4)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.backend.core.ai.errors import (
    WorkspaceQuotaExceededError,
    WorkspaceTTLExpiredError,
)
from src.backend.core.ai.workspace_manager import AIWorkspaceManager


@pytest.fixture()
def workspace_root(tmp_path: Path) -> Path:
    return tmp_path / "ai_workspace"


@pytest.mark.asyncio
async def test_create_new_returns_unique_handle(workspace_root: Path) -> None:
    manager = AIWorkspaceManager(root=workspace_root)
    h1 = await manager.create_new(tenant="t1")
    h2 = await manager.create_new(tenant="t1")
    assert h1.session_id != h2.session_id
    assert h1.path.exists() and h2.path.exists()
    assert h1.path.parent == workspace_root / "t1"


@pytest.mark.asyncio
async def test_create_new_emits_audit_event(
    workspace_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """create_new эмитит audit-event через canonical facade.emit_ai_workspace.

    S108 W3: после TD-004 migration домена AI legacy `audit=callback`
    параметр удалён. Тест мокает ``emit_ai_workspace`` напрямую через
    monkeypatch — новый паттерн для audit-tests.
    """
    captured_events: list[dict[str, object]] = []

    async def _capture(event: dict[str, object]) -> None:
        captured_events.append(event)

    monkeypatch.setattr(
        "src.backend.core.ai.workspace_manager.emit_ai_workspace", _capture
    )

    manager = AIWorkspaceManager(root=workspace_root)
    handle = await manager.create_new(tenant="t1", artifact_hint="report")
    assert captured_events == [
        {
            "event": "ai_workspace.create_new",
            "tenant": "t1",
            "session_id": handle.session_id,
            "path": str(handle.path),
            "artifact_hint": "report",
        }
    ]


@pytest.mark.asyncio
async def test_quota_exceeded_blocks_new_workspace(workspace_root: Path) -> None:
    manager = AIWorkspaceManager(root=workspace_root, per_tenant_quota_bytes=10)
    await manager.create_new(tenant="t1")
    manager.add_used_bytes("t1", 100)
    with pytest.raises(WorkspaceQuotaExceededError):
        await manager.create_new(tenant="t1")


@pytest.mark.asyncio
async def test_ttl_expired_handle_blocks_writes(workspace_root: Path) -> None:
    manager = AIWorkspaceManager(root=workspace_root, ttl_seconds=0.001)
    handle = await manager.create_new(tenant="t1")
    time.sleep(0.01)
    with pytest.raises(WorkspaceTTLExpiredError):
        manager.assert_alive(handle)


@pytest.mark.asyncio
async def test_cleanup_expired_removes_old_workspaces(
    workspace_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cleanup_expired удаляет TTL-expired workspaces и эмитит audit-event.

    S108 W3: cleanup_event эмитится через canonical emit_ai_workspace.
    """
    captured_events: list[dict[str, object]] = []

    async def _capture(event: dict[str, object]) -> None:
        captured_events.append(event)

    monkeypatch.setattr(
        "src.backend.core.ai.workspace_manager.emit_ai_workspace", _capture
    )

    manager = AIWorkspaceManager(root=workspace_root, ttl_seconds=0.001)
    h1 = await manager.create_new(tenant="t1")
    (h1.path / "a.txt").write_text("x")
    time.sleep(0.01)
    removed = await manager.cleanup_expired()
    assert removed == 1
    assert not h1.path.exists()
    # Verify cleanup audit-event was emitted
    cleanup_events = [
        e for e in captured_events if e.get("event") == "ai_workspace.cleanup"
    ]
    assert len(cleanup_events) == 1
    assert cleanup_events[0]["tenant"] == "t1"
    assert int(cleanup_events[0]["freed_bytes"]) > 0  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_shutdown_cancels_cleanup_loop(workspace_root: Path) -> None:
    manager = AIWorkspaceManager(root=workspace_root, cleanup_interval_seconds=0.05)
    await manager.start_cleanup_loop()
    await manager.shutdown()
    # Re-shutdown идемпотентен.
    await manager.shutdown()
