"""ADR-0390 (волна 18, кластер G1) — CsvReadProcessor: кодировка и лимиты.

Дефект (8) [medium]: жёсткий ``encoding="utf-8"`` → cp1251-файл падал с
необработанным ``UnicodeDecodeError`` (проброс из processor'а без понятного
сообщения). Плюс не было лимитов на размер файла и число строк.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.dsl.engine.processors.rpa.operations import csvreadprocessor
from src.backend.dsl.engine.processors.rpa.operations.csvreadprocessor import (
    CsvReadProcessor,
)


def _exchange() -> MagicMock:
    ex = MagicMock()
    ex.in_message = MagicMock()
    ex.in_message.body = {}
    ex.set_property = MagicMock()
    ex.set_error = MagicMock()
    ex.stop = MagicMock()
    return ex


def _processor(**kwargs: Any) -> CsvReadProcessor:
    proc = CsvReadProcessor(**kwargs)
    proc.auth_check = AsyncMock(return_value=True)
    return proc


@pytest.mark.asyncio
async def test_cp1251_file_is_decoded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(8) cp1251-файл читается (кодировка определяется автоматически)."""
    monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path))
    src = tmp_path / "cp1251.csv"
    src.write_bytes("name;city\nИван;Москва\n".encode("cp1251"))

    proc = _processor(src=str(src), delimiter=";")
    ex = _exchange()

    await proc.process(ex, MagicMock())

    ex.fail.assert_not_called()
    rows = ex.in_message.body["rows"]
    assert rows[0]["name"] == "Иван"
    assert rows[0]["city"] == "Москва"


@pytest.mark.asyncio
async def test_utf8_file_still_decoded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сан-санк: utf-8 читается как раньше."""
    monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path))
    src = tmp_path / "utf8.csv"
    src.write_text("name\nАня\n", encoding="utf-8")

    proc = _processor(src=str(src))
    ex = _exchange()

    await proc.process(ex, MagicMock())

    ex.fail.assert_not_called()
    assert ex.in_message.body["rows"][0]["name"] == "Аня"


@pytest.mark.asyncio
async def test_oversized_file_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(8) Файл больше лимита → понятная ошибка, а не OOM."""
    monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path))
    monkeypatch.setattr(csvreadprocessor, "_MAX_CSV_BYTES", 10)
    src = tmp_path / "big.csv"
    src.write_text("a,b\n" + "x" * 100 + "\n")

    proc = _processor(src=str(src))
    ex = _exchange()

    await proc.process(ex, MagicMock())

    ex.fail.assert_called_once()
    assert "exceeds" in ex.fail.call_args[0][0]


@pytest.mark.asyncio
async def test_too_many_rows_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(8) Больше лимита строк → понятная ошибка."""
    monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path))
    monkeypatch.setattr(csvreadprocessor, "_MAX_CSV_ROWS", 2)
    src = tmp_path / "many.csv"
    src.write_text("a\n1\n2\n3\n4\n")

    proc = _processor(src=str(src))
    ex = _exchange()

    await proc.process(ex, MagicMock())

    ex.fail.assert_called_once()
    assert "больше 2 строк" in ex.fail.call_args[0][0]


@pytest.mark.asyncio
async def test_inline_content_still_works() -> None:
    """Сан-санк: inline-контент читается как раньше."""
    proc = _processor(content="a,b\n1,2\n")
    ex = _exchange()

    await proc.process(ex, MagicMock())

    ex.fail.assert_not_called()
    assert ex.in_message.body["rows"][0]["a"] == "1"
