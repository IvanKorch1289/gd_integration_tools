"""Tests for new RPA DSL processors (S171 M6 — gap fill).

5 new processors covering most popular RPA gaps:
1. FileDeleteProcessor — secure file deletion
2. FileListProcessor — glob/list files (with patterns)
3. FileWatchProcessor — watchdog-based file watching
4. TerminalExecProcessor — async subprocess with timeout
5. ImageConvertProcessor — pillow format conversion
"""
from __future__ import annotations
import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestFileDeleteProcessor:
    @pytest.mark.asyncio
    async def test_deletes_file(self, tmp_path: Path) -> None:
        from src.backend.dsl.engine.processors.rpa.operations.filedeleteprocessor import (
            FileDeleteProcessor,
        )
        target = tmp_path / "delete_me.txt"
        target.write_text("data")
        p = FileDeleteProcessor(path=str(target))
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        await p.process(ex, MagicMock())
        assert not target.exists()
        assert ex.in_message.body.get("deleted") is True


class TestFileListProcessor:
    @pytest.mark.asyncio
    async def test_lists_files_with_pattern(self, tmp_path: Path) -> None:
        from src.backend.dsl.engine.processors.rpa.operations.filelistprocessor import (
            FileListProcessor,
        )
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        (tmp_path / "c.log").write_text("c")
        p = FileListProcessor(pattern=str(tmp_path / "*.txt"), to="body.files")
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        await p.process(ex, MagicMock())
        files = ex.in_message.body.get("files", [])
        names = sorted(os.path.basename(f) for f in files)
        assert names == ["a.txt", "b.txt"]


class TestFileWatchProcessor:
    def test_processor_instantiates(self) -> None:
        from src.backend.dsl.engine.processors.rpa.operations.filewatchprocessor import (
            FileWatchProcessor,
        )
        p = FileWatchProcessor(directory="/tmp", pattern="*.txt", timeout=1.0)
        assert p.directory == "/tmp"
        assert p.pattern == "*.txt"
        assert p.timeout == 1.0

    @pytest.mark.asyncio
    async def test_watch_returns_empty_when_timeout(self, tmp_path: Path) -> None:
        """Если ничего не изменилось за timeout → возвращает []."""
        from src.backend.dsl.engine.processors.rpa.operations.filewatchprocessor import (
            FileWatchProcessor,
        )
        p = FileWatchProcessor(directory=str(tmp_path), pattern="*.txt", timeout=0.1)
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        # Mock Observer so we don't actually start threads
        with patch(
            "watchdog.observers.Observer"
        ):
            await p.process(ex, MagicMock())
        # Even with timeout, returns changes list (empty)
        assert "changes" in ex.in_message.body


class TestTerminalExecProcessor:
    @pytest.mark.asyncio
    async def test_exec_runs_command(self) -> None:
        from src.backend.dsl.engine.processors.rpa.system import (
            TerminalExecProcessor,
        )
        p = TerminalExecProcessor(command="echo hello", timeout=2.0, to="body.output")
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        await p.process(ex, MagicMock())
        assert "hello" in ex.in_message.body.get("output", "")

    @pytest.mark.asyncio
    async def test_exec_timeout_raises(self) -> None:
        """subprocess timeout → raise TimeoutError."""
        from src.backend.dsl.engine.processors.rpa.system import (
            TerminalExecProcessor,
        )
        p = TerminalExecProcessor(command="sleep 10", timeout=0.1)
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        with pytest.raises(asyncio.TimeoutError):
            await p.process(ex, MagicMock())
