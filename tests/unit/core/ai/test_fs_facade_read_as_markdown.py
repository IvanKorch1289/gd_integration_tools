"""Тесты AIFsFacade.read_as_markdown (Sprint S5)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.backend.core.ai.fs_facade import AIFsFacade
from src.backend.core.ai.workspace_manager import AIWorkspaceManager


@pytest.fixture
def facade(tmp_path: Path) -> AIFsFacade:
    wm = AIWorkspaceManager(root=tmp_path / "ai_ws")
    return AIFsFacade(workspace_manager=wm, capability_check=None, plugin="test")


class TestReadAsMarkdownLegacy:
    """Plain-text route — markitdown не вызывается, engine='legacy'."""

    async def test_md_file_returns_text(self, facade: AIFsFacade) -> None:
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"# Hello\n\nworld")
            path = Path(f.name)
        try:
            text, meta = await facade.read_as_markdown(path)
            assert text == "# Hello\n\nworld"
            assert meta["engine"] == "legacy"
            assert meta["markdown"] is False
            assert meta["mime"] == "text/markdown"
        finally:
            path.unlink()


class TestCapabilityCheck:
    async def test_capability_check_invoked_for_read_and_parse(
        self, tmp_path: Path
    ) -> None:
        calls: list[tuple[str, str, str | None]] = []

        def _check(plugin: str, capability: str, scope: str | None) -> None:
            calls.append((plugin, capability, scope))

        wm = AIWorkspaceManager(root=tmp_path / "ai_ws")
        facade = AIFsFacade(
            workspace_manager=wm, capability_check=_check, plugin="ai-agent"
        )

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"data")
            path = Path(f.name)
        try:
            await facade.read_as_markdown(path)
        finally:
            path.unlink()

        capabilities = [c[1] for c in calls]
        assert "fs.read" in capabilities
        assert "documents.parse" in capabilities


class TestExplicitMimeOverride:
    async def test_explicit_mime_used(self, facade: AIFsFacade) -> None:
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(b"hello")
            path = Path(f.name)
        try:
            text, meta = await facade.read_as_markdown(path, mime="text/plain")
            assert meta["mime"] == "text/plain"
            assert text == "hello"
        finally:
            path.unlink()
