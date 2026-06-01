"""Тесты :class:`AIFsFacade` (V15 R-V15-4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.core.ai.errors import FsForbiddenWriteError
from src.backend.core.ai.fs_facade import AIFsFacade
from src.backend.core.ai.workspace_manager import AIWorkspaceManager


@pytest.fixture()
def workspace_root(tmp_path: Path) -> Path:
    return tmp_path / "ai_workspace"


@pytest.fixture()
async def manager(workspace_root: Path) -> AIWorkspaceManager:
    return AIWorkspaceManager(root=workspace_root)


@pytest.mark.asyncio
async def test_read_invokes_capability_check(
    manager: AIWorkspaceManager, tmp_path: Path
) -> None:
    """capability_check вызывается с (plugin, 'fs.read', path)."""
    seen: list[tuple[str, str, str | None]] = []

    def fake_check(plugin: str, capability: str, scope: str | None) -> None:
        seen.append((plugin, capability, scope))

    fs = AIFsFacade(workspace_manager=manager, capability_check=fake_check)
    target = tmp_path / "data.txt"
    target.write_text("hello")
    fs.read(target)
    assert seen == [("ai-agent", "fs.read", target.as_posix())]


@pytest.mark.asyncio
async def test_read_returns_bytes(
    manager: AIWorkspaceManager, tmp_path: Path
) -> None:
    fs = AIFsFacade(workspace_manager=manager)
    target = tmp_path / "data.txt"
    target.write_text("hello")
    assert fs.read(target) == b"hello"


@pytest.mark.asyncio
async def test_read_directory_raises(
    manager: AIWorkspaceManager, tmp_path: Path
) -> None:
    fs = AIFsFacade(workspace_manager=manager)
    with pytest.raises(IsADirectoryError):
        fs.read(tmp_path)


@pytest.mark.asyncio
async def test_create_new_writes_inside_workspace(
    manager: AIWorkspaceManager,
) -> None:
    fs = AIFsFacade(workspace_manager=manager)
    handle = await manager.create_new(tenant="t1")
    target = fs.create_new(handle, "report.json", b'{"ok":true}')
    assert target.exists()
    assert target.read_bytes() == b'{"ok":true}'
    assert target.is_relative_to(handle.path)


@pytest.mark.asyncio
async def test_create_new_blocks_overwrite(
    manager: AIWorkspaceManager,
) -> None:
    """create_new — non-overwriting, повторная запись → :class:`FsForbiddenWriteError`."""
    fs = AIFsFacade(workspace_manager=manager)
    handle = await manager.create_new(tenant="t1")
    fs.create_new(handle, "report.json", b"v1")
    with pytest.raises(FsForbiddenWriteError) as exc_info:
        fs.create_new(handle, "report.json", b"v2")
    assert "already exists" in exc_info.value.reason


@pytest.mark.asyncio
async def test_create_new_blocks_traversal(
    manager: AIWorkspaceManager,
) -> None:
    """``..``-traversal → :class:`FsForbiddenWriteError`."""
    fs = AIFsFacade(workspace_manager=manager)
    handle = await manager.create_new(tenant="t1")
    with pytest.raises(FsForbiddenWriteError):
        fs.create_new(handle, "../escape.txt", b"x")


@pytest.mark.asyncio
async def test_create_new_blocks_absolute_path(
    manager: AIWorkspaceManager, tmp_path: Path
) -> None:
    """Абсолютный путь → :class:`FsForbiddenWriteError`."""
    fs = AIFsFacade(workspace_manager=manager)
    handle = await manager.create_new(tenant="t1")
    with pytest.raises(FsForbiddenWriteError):
        fs.create_new(handle, str(tmp_path / "out.txt"), b"x")


@pytest.mark.asyncio
async def test_create_new_capability_check_invoked(
    manager: AIWorkspaceManager,
) -> None:
    seen: list[tuple[str, str, str | None]] = []

    def fake_check(plugin: str, capability: str, scope: str | None) -> None:
        seen.append((plugin, capability, scope))

    fs = AIFsFacade(workspace_manager=manager, capability_check=fake_check)
    handle = await manager.create_new(tenant="t1")
    fs.create_new(handle, "report.json", b"{}")
    assert seen == [("ai-agent", "fs.create_new", handle.path.as_posix())]
