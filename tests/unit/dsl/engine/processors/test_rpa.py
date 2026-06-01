"""Тесты RPA процессоров (Wave 6)."""

# ruff: noqa: S101

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.rpa import (
    ArchiveProcessor,
    PdfReadProcessor,
)


@pytest.mark.asyncio
async def test_archive_processor_creates_valid_zip() -> None:
    """ArchiveProcessor создаёт валидный ZIP из списка файлов."""
    proc = ArchiveProcessor(mode="create", format="zip")
    exchange = Exchange()
    exchange.in_message.body = [
        {"name": "a.txt", "data": b"hello"},
        {"name": "b.txt", "data": b"world"},
    ]

    await proc.process(exchange, None)  # type: ignore[arg-type]

    zip_bytes = exchange.out_message.body
    assert isinstance(zip_bytes, bytes)
    # Проверяем, что это валидный ZIP
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    assert zf.namelist() == ["a.txt", "b.txt"]
    assert zf.read("a.txt") == b"hello"


@pytest.mark.asyncio
async def test_pdf_read_processor_with_bytes() -> None:
    """PdfReadProcessor читает PDF из bytes."""
    proc = PdfReadProcessor()
    exchange = Exchange()
    # Простейший PDF в bytes (заголовок PDF)
    # Для теста используем настоящий PDF из fixtures, если есть.
    # Иначе — mock через pypdf.
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    exchange.in_message.body = buf.getvalue()

    await proc.process(exchange, None)  # type: ignore[arg-type]

    result = exchange.out_message.body
    assert result["page_count"] == 1
    assert isinstance(result["text"], str)
