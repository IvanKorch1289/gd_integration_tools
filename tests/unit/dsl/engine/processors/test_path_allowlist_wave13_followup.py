"""Wave 13 Q7 follow-on — закрытие path-allowlist gap'ов из ADR-0358 §6.

Два файловых процессора обходили allowlist каталогов:

* ``FileMoveProcessor`` (RPA) — локальные пути источника и цели;
* ``RenderTemplateFileProcessor`` — путь к файлу-шаблону.

Capability ограничивает *факт вызова* процессора, allowlist — *путь*.
Тесты проверяют, что путь вне allowlist отклоняется ДО обращения к ФС:
файл не перемещается, шаблон не читается.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.rpa.operations.filemoveprocessor import (
    FileMoveProcessor,
)
from src.backend.dsl.engine.processors.template_engine import (
    RenderTemplateFileProcessor,
)


def _exchange(body: Any = None) -> Exchange[Any]:
    """Настоящий Exchange — чтобы проверять status/error, а не mock-вызовы."""
    return Exchange(in_message=Message(body={} if body is None else body, headers={}))


def _allow(proc: Any) -> None:
    """Bypass capability-gate: тестируем path-барьер, а не capability."""
    proc.auth_check = AsyncMock(return_value=True)


class TestFileMovePathAllowlist:
    """FileMoveProcessor — путь источника и путь цели."""

    @pytest.mark.asyncio
    async def test_src_outside_allowlist_is_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(allowed))
        secret = tmp_path / "secret.txt"
        secret.write_text("TOP SECRET")

        proc = FileMoveProcessor(
            src=str(secret), dst=str(allowed / "moved.txt"), mode="move"
        )
        _allow(proc)
        ex = _exchange()

        await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        assert "outside allowed" in (ex.error or "")
        # Файл не перемещён и не скопирован.
        assert secret.read_text() == "TOP SECRET"
        assert not (allowed / "moved.txt").exists()
        assert "file_operation" not in ex.properties

    @pytest.mark.asyncio
    async def test_dst_outside_allowlist_is_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Цель вне allowlist — запись за пределы разрешённого каталога."""
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        src = allowed / "a.txt"
        src.write_text("data")
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(allowed))
        escaped = tmp_path / "escaped.txt"

        proc = FileMoveProcessor(src=str(src), dst=str(escaped), mode="move")
        _allow(proc)
        ex = _exchange()

        await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        assert "outside allowed" in (ex.error or "")
        assert src.read_text() == "data"
        assert not escaped.exists()
        assert "file_operation" not in ex.properties

    @pytest.mark.asyncio
    async def test_paths_inside_allowlist_are_moved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Позитивный кейс: оба пути внутри allowlist — файл перемещается."""
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        src = allowed / "a.txt"
        src.write_text("data")
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(allowed))

        proc = FileMoveProcessor(src=str(src), dst=str(allowed / "b.txt"), mode="move")
        _allow(proc)
        ex = _exchange()

        await proc.process(ex, MagicMock())

        assert ex.status != ExchangeStatus.failed
        assert ex.error is None
        assert (allowed / "b.txt").read_text() == "data"
        assert not src.exists()


class TestRenderTemplateFilePathAllowlist:
    """RenderTemplateFileProcessor — путь к файлу-шаблону."""

    @pytest.mark.asyncio
    async def test_template_outside_allowlist_is_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(allowed))
        outside = tmp_path / "tpl.j2"
        outside.write_text("Hello {{ name }}!")

        proc = RenderTemplateFileProcessor(path=str(outside))
        ex = _exchange({"name": "Alice"})

        with patch("jinja2.Environment.get_template") as mock_get_template:
            await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        assert "outside allowed" in (ex.error or "")
        # Шаблон не прочитан.
        mock_get_template.assert_not_called()
        assert "rendered" not in ex.properties

    @pytest.mark.asyncio
    async def test_template_inside_allowlist_is_rendered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Позитивный кейс: шаблон внутри allowlist — рендерится."""
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        (allowed / "tpl.j2").write_text("Hello {{ name }}!")
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(allowed))
        monkeypatch.chdir(allowed)

        proc = RenderTemplateFileProcessor(path="tpl.j2")
        ex = _exchange({"name": "Alice"})

        await proc.process(ex, MagicMock())

        assert ex.status != ExchangeStatus.failed
        assert ex.error is None
        assert ex.properties["rendered"] == "Hello Alice!"
