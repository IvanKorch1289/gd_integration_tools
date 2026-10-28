"""Wave 13 Q7 (A) — ядерные FS-процессоры под path-allowlist.

``FileWatchProcessor`` (core, ``dsl/engine/processors/file_watch.py``) и
``DirectoryScanProcessor`` (deprecated-shim, ``dsl/engine/processors/
fs_directory_scan.py``) сканируют файловую систему. Раньше allowlist
(``validate_path``) применялся только к FileRead/FileWrite/FileDelete —
ядровные сканеры ФСallowlist обходили.

Тесты проверяют, что каталог вне allowlist приводит к ``exchange.fail``
и ФС НЕ сканируется, а каталог внутри allowlist сканируется штатно.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.file_watch import FileWatchProcessor
from src.backend.dsl.engine.processors.fs_directory_scan import DirectoryScanProcessor
from src.backend.dsl.engine.processors.rpa.operations.filtereddirectoryscanprocessor import (
    FilteredDirectoryScanProcessor,
)


def _exchange(body: Any = None) -> Exchange[Any]:
    """Настоящий Exchange — чтобы проверять status/error, а не mock-вызовы."""
    return Exchange(in_message=Message(body=body, headers={}))


@pytest.fixture(autouse=True)
def _bypass_capability_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """DirectoryScanProcessor делегирует RPA-процессору с capability-gate."""
    monkeypatch.setattr(
        FilteredDirectoryScanProcessor, "auth_check", AsyncMock(return_value=True)
    )


class TestFileWatchPathAllowlist:
    """FileWatchProcessor (core) — сканируемая директория."""

    @pytest.mark.asyncio
    async def test_directory_outside_allowlist_is_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path / "allowed"))
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("secret")

        proc = FileWatchProcessor(directory=str(outside), pattern="*.txt")
        ex = _exchange()

        await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        assert "outside allowed" in (ex.error or "")
        assert not ex.properties.get("matched_files")

    @pytest.mark.asyncio
    async def test_directory_inside_allowlist_is_scanned(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        (allowed / "a.txt").write_text("a")
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(allowed))

        proc = FileWatchProcessor(directory=str(allowed), pattern="*.txt")
        ex = _exchange()

        await proc.process(ex, MagicMock())

        assert ex.status != ExchangeStatus.failed
        assert ex.error is None
        assert [f["name"] for f in ex.properties["matched_files"]] == ["a.txt"]

    @pytest.mark.asyncio
    async def test_watch_directory_property_outside_allowlist_is_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Каталог из exchange-property — тоже недоверенный ввод."""
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path / "allowed"))
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("secret")

        proc = FileWatchProcessor(directory=str(tmp_path / "allowed"), pattern="*.txt")
        ex = _exchange()
        ex.set_property("watch_directory", str(outside))

        await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        assert "outside allowed" in (ex.error or "")
        assert not ex.properties.get("matched_files")

    @pytest.mark.asyncio
    async def test_directories_tuple_outside_allowlist_is_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Multi-directory (S176 #4) — каждый каталог проверяется."""
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path / "allowed"))
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("secret")

        proc = FileWatchProcessor(directories=(str(outside),), pattern="*.txt")
        ex = _exchange()

        await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        assert "outside allowed" in (ex.error or "")
        assert not ex.properties.get("matched_files")


class TestDirectoryScanPathAllowlist:
    """DirectoryScanProcessor (deprecated shim) — сканируемый путь."""

    @pytest.mark.asyncio
    async def test_path_outside_allowlist_is_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path / "allowed"))
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("secret")

        proc = DirectoryScanProcessor(path=str(outside), pattern="*.txt")
        ex = _exchange()

        await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        assert "outside allowed" in (ex.error or "")
        assert not ex.properties.get("directory_scan_result")

    @pytest.mark.asyncio
    async def test_nonexistent_path_outside_allowlist_is_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Проверка allowlist идёт ДО проверки существования каталога."""
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path / "allowed"))
        outside = tmp_path / "outside"

        proc = DirectoryScanProcessor(path=str(outside), pattern="*.txt")
        ex = _exchange()

        await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        assert "outside allowed" in (ex.error or "")
        assert "not a directory" not in (ex.error or "")

    @pytest.mark.asyncio
    async def test_path_from_request_body_outside_allowlist_is_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Путь из тела запроса — недоверенный ввод."""
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path / "allowed"))
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("secret")

        proc = DirectoryScanProcessor(path="", pattern="*.txt")
        ex = _exchange({"path": str(outside)})

        await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        assert "outside allowed" in (ex.error or "")
        assert not ex.properties.get("directory_scan_result")

    @pytest.mark.asyncio
    async def test_path_inside_allowlist_is_scanned(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        (allowed / "a.txt").write_text("a")
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(allowed))

        proc = DirectoryScanProcessor(path=str(allowed), pattern="*.txt")
        ex = _exchange()

        await proc.process(ex, MagicMock())

        assert ex.status != ExchangeStatus.failed
        assert ex.error is None
        result = ex.properties.get("directory_scan_result")
        assert isinstance(result, list)
        assert [entry["name"] for entry in result] == ["a.txt"]
