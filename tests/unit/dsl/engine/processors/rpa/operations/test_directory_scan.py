"""Tests for DirectoryScanProcessor (S171 M7)."""
from __future__ import annotations
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestDirectoryScanProcessor:
    def test_instantiates(self) -> None:
        from src.backend.dsl.engine.processors.rpa.operations.directoryscanprocessor import (
            DirectoryScanProcessor,
        )
        p = DirectoryScanProcessor(directory="/tmp", pattern="*.txt")
        assert p.directory == "/tmp"
        assert p.pattern == "*.txt"

    @pytest.mark.asyncio
    async def test_scans_recursive(self, tmp_path: Path) -> None:
        from src.backend.dsl.engine.processors.rpa.operations.directoryscanprocessor import (
            DirectoryScanProcessor,
        )
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.txt").write_text("b")
        p = DirectoryScanProcessor(
            directory=str(tmp_path), pattern="**/*.txt", to="body.files"
        )
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        await p.process(ex, MagicMock())
        files = ex.in_message.body.get("files", [])
        names = sorted(Path(f).name for f in files)
        assert names == ["a.txt", "b.txt"]

    @pytest.mark.asyncio
    async def test_filter_by_size(self, tmp_path: Path) -> None:
        from src.backend.dsl.engine.processors.rpa.operations.directoryscanprocessor import (
            DirectoryScanProcessor,
        )
        (tmp_path / "small.txt").write_text("hi")
        (tmp_path / "big.txt").write_text("x" * 1000)
        p = DirectoryScanProcessor(
            directory=str(tmp_path), pattern="*.txt", min_size=100, to="body.files"
        )
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        await p.process(ex, MagicMock())
        files = ex.in_message.body.get("files", [])
        assert len(files) == 1
        assert "big.txt" in files[0]
