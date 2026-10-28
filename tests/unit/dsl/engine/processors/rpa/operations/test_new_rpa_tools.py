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
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestFileDeleteProcessor:
    @pytest.mark.asyncio
    async def test_deletes_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Cycle 33 DS2: FileDeleteProcessor enforces path-traversal guard via
        # _path_safety.validate_path; pytest's tmp_path is NOT in the default
        # allowlist → разрешаем его через DSL_ALLOWED_PATHS.
        # Cycle 172 (C5): было — запись в общий /tmp/dsl (гонки при -n auto,
        # мусор на машине); стало — изолированный tmp_path.
        from src.backend.dsl.engine.processors.rpa.operations.filedeleteprocessor import (
            FileDeleteProcessor,
        )

        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path))
        target = tmp_path / "delete_me.txt"
        target.write_text("data")
        p = FileDeleteProcessor(path=str(target))
        p.auth_check = AsyncMock(return_value=True)
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        await p.process(ex, MagicMock())
        assert not target.exists()
        assert ex.in_message.body.get("deleted") is True

    @pytest.mark.asyncio
    async def test_non_dict_body_does_not_raise_attribute_error(self) -> None:
        """ADR-0367: body не-dict → понятная ошибка, а не ``AttributeError``.

        Раньше: ``exchange.in_message.body.get("path")`` падал с
        ``AttributeError: 'str' object has no attribute 'get'``.
        """
        from src.backend.dsl.engine.processors.rpa.operations.filedeleteprocessor import (
            FileDeleteProcessor,
        )

        p = FileDeleteProcessor()
        p.auth_check = AsyncMock(return_value=True)
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = "not-a-dict"
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()

        with pytest.raises(ValueError, match="path"):
            await p.process(ex, MagicMock())

    @pytest.mark.asyncio
    async def test_dict_body_path_is_used(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Путь из тела запроса (dict) — рабочий сценарий."""
        from src.backend.dsl.engine.processors.rpa.operations.filedeleteprocessor import (
            FileDeleteProcessor,
        )

        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path))
        target = tmp_path / "delete_me.txt"
        target.write_text("data")

        p = FileDeleteProcessor()
        p.auth_check = AsyncMock(return_value=True)
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {"path": str(target)}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()

        await p.process(ex, MagicMock())

        assert not target.exists()
        assert ex.in_message.body.get("deleted") is True


class TestFileListProcessor:
    @pytest.mark.asyncio
    async def test_lists_files_with_pattern(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.backend.dsl.engine.processors.rpa.operations.filelistprocessor import (
            FileListProcessor,
        )

        # Wave 13 Q7 (B): RPA-процессоры проверяют путь по allowlist
        # (DSL_ALLOWED_PATHS) — tmp_path pytest вне дефолтного allowlist.
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path))

        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        (tmp_path / "c.log").write_text("c")
        p = FileListProcessor(pattern=str(tmp_path / "*.txt"), to="body.files")
        p.auth_check = AsyncMock(return_value=True)
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
    async def test_watch_returns_empty_when_timeout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Если ничего не изменилось за timeout → возвращает []."""
        from src.backend.dsl.engine.processors.rpa.operations.filewatchprocessor import (
            FileWatchProcessor,
        )

        # Wave 13 Q7 (B): наблюдаемая директория проверяется по allowlist.
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path))

        p = FileWatchProcessor(directory=str(tmp_path), pattern="*.txt", timeout=0.1)
        p.auth_check = AsyncMock(return_value=True)
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        # Mock Observer so we don't actually start threads
        with patch("watchdog.observers.Observer"):
            await p.process(ex, MagicMock())
        # Even with timeout, returns changes list (empty)
        assert "changes" in ex.in_message.body


class TestTerminalExecProcessor:
    @pytest.mark.asyncio
    async def test_exec_runs_command(self) -> None:
        from src.backend.dsl.engine.processors.rpa.system import TerminalExecProcessor

        p = TerminalExecProcessor(command="echo hello", timeout=2.0, to="body.output")
        p.auth_check = AsyncMock(return_value=True)
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
        from src.backend.dsl.engine.processors.rpa.system import TerminalExecProcessor

        p = TerminalExecProcessor(command="sleep 10", timeout=0.1)
        p.auth_check = AsyncMock(return_value=True)
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        with pytest.raises(asyncio.TimeoutError):
            await p.process(ex, MagicMock())
