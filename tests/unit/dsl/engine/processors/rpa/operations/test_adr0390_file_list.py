"""ADR-0390 (волна 18, кластер G1) — FileListProcessor: обход allowlist.

Дефект (3) [high]: pattern приходил из тела запроса, валидировался только
**статический префикс** (каталог до первого magic-символа). Паттерн
``/tmp/probe/allow/sub/../../etc/hostname`` проходил проверку (префикс
``/tmp/probe/allow/sub`` — внутри allowlist), а glob матчил файл вне
allowlist.

Фикс: ``..`` в паттерне запрещён + каждый найденный результат проверяется
по allowlist + лимит количества результатов (дефект 9).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.dsl.engine.processors.rpa.operations.filelistprocessor import (
    FileListProcessor,
)


def _exchange(body: Any = None) -> MagicMock:
    ex = MagicMock()
    ex.in_message = MagicMock()
    ex.in_message.body = {} if body is None else body
    ex.set_property = MagicMock()
    ex.set_error = MagicMock()
    ex.stop = MagicMock()
    return ex


def _processor(pattern: str | None = None, **kwargs: Any) -> FileListProcessor:
    proc = FileListProcessor(pattern=pattern, **kwargs)
    proc.auth_check = AsyncMock(return_value=True)
    return proc


@pytest.mark.asyncio
async def test_pattern_with_traversal_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(3) ``..`` в паттерне → отказ (обход allowlist невозможен).

    Проба аудита: pattern с magic-символом **до** traversal
    (``<allow>/*/../../etc/hostname``) проходил статическую проверку
    префикса (префикс = ``<allow>``), а glob матчил файл вне allowlist.
    """
    probe = tmp_path / "probe"
    allowed = probe / "allow"
    (allowed / "sub").mkdir(parents=True)
    outside = probe / "etc"
    outside.mkdir()
    (outside / "hostname").write_text("secret")
    monkeypatch.setenv("DSL_ALLOWED_PATHS", str(allowed))

    proc = _processor()
    ex = _exchange({"pattern": f"{allowed}/*/../../etc/hostname"})

    await proc.process(ex, MagicMock())

    ex.fail.assert_called_once()
    assert "traversal" in ex.fail.call_args[0][0].lower()
    # В тело ничего не записано.
    assert ex.in_message.body.get("files") is None


@pytest.mark.asyncio
async def test_glob_result_outside_allowlist_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(3) Результат glob вне allowlist → отказ (symlink/``..`` в результатах)."""
    allowed = tmp_path / "allow"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    # Симлинк внутри allowlist наружу — раньше проходил (текстовый путь).
    (allowed / "link.txt").symlink_to(outside / "secret.txt")
    monkeypatch.setenv("DSL_ALLOWED_PATHS", str(allowed))

    proc = _processor()
    ex = _exchange({"pattern": str(allowed / "*.txt")})

    await proc.process(ex, MagicMock())

    ex.fail.assert_called_once()
    assert "file_list blocked" in ex.fail.call_args[0][0]


@pytest.mark.asyncio
async def test_files_inside_allowlist_are_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сан-санк: файлы внутри allowlist по-прежнему возвращаются."""
    allowed = tmp_path / "allow"
    allowed.mkdir()
    (allowed / "a.txt").write_text("a")
    (allowed / "b.txt").write_text("b")
    monkeypatch.setenv("DSL_ALLOWED_PATHS", str(allowed))

    proc = _processor()
    ex = _exchange({"pattern": str(allowed / "*.txt")})

    await proc.process(ex, MagicMock())

    ex.fail.assert_not_called()
    files = ex.in_message.body["files"]
    assert len(files) == 2
    assert all(f.endswith(".txt") for f in files)


@pytest.mark.asyncio
async def test_result_count_is_limited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(9) Количество результатов ограничено (понятная ошибка)."""
    from src.backend.dsl.engine.processors.rpa.operations import filelistprocessor

    allowed = tmp_path / "allow"
    allowed.mkdir()
    for i in range(5):
        (allowed / f"f{i}.txt").write_text("x")
    monkeypatch.setenv("DSL_ALLOWED_PATHS", str(allowed))
    monkeypatch.setattr(filelistprocessor, "_MAX_FILE_LIST_RESULTS", 2)

    proc = _processor()
    ex = _exchange({"pattern": str(allowed / "*.txt")})

    await proc.process(ex, MagicMock())

    ex.fail.assert_called_once()
    assert "more than 2 files" in ex.fail.call_args[0][0]
