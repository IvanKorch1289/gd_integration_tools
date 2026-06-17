"""Unit tests for RPA document processors."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.backend.dsl.engine.processors.rpa.documents import (
    PdfReadProcessor,
    PdfMergeProcessor,
    WordReadProcessor,
    WordWriteProcessor,
    ExcelReadProcessor,
)
from src.backend.dsl.engine.exchange import Exchange


class TestPdfReadProcessor:
    """Tests for PdfReadProcessor."""

    @pytest.mark.asyncio
    async def test_process_extracts_text(self) -> None:
        # S164 W1: mock actual read_pdf utility (не _read_pdf instance method).
        processor = PdfReadProcessor()
        exchange = MagicMock(spec=Exchange)
        exchange.in_message = MagicMock()
        exchange.in_message.body = b"%PDF-1.4 fake"
        exchange.set_property = MagicMock()

        with patch("src.backend.utilities.pdf_reader.read_pdf", return_value="page1 text\n\npage2 text") as mock_read:
            await processor.process(exchange, MagicMock())

        mock_read.assert_called_once()
        exchange.set_property.assert_called()


class TestPdfMergeProcessor:
    """Tests for PdfMergeProcessor."""

    @pytest.mark.asyncio
    async def test_process_merges_pdfs(self) -> None:
        # S164 W1: mock both PdfWriter and PdfReader (pypdf integration).
        processor = PdfMergeProcessor()
        exchange = MagicMock(spec=Exchange)
        exchange.in_message = MagicMock()
        exchange.in_message.body = [b"%PDF-1.4 a", b"%PDF-1.4 b"]
        exchange.set_property = MagicMock()

        with patch("pypdf.PdfWriter") as mock_writer_cls, \
             patch("pypdf.PdfReader") as mock_reader_cls:
            mock_writer = MagicMock()
            mock_writer_cls.return_value = mock_writer
            mock_writer.write.return_value = None
            mock_reader = MagicMock()
            mock_reader.pages = []
            mock_reader_cls.return_value = mock_reader
            await processor.process(exchange, MagicMock())

        exchange.set_property.assert_called()


class TestWordReadProcessor:
    """Tests for WordReadProcessor."""

    @pytest.mark.asyncio
    async def test_process_extracts_text(self) -> None:
        # S164 W1: mock python-docx Document парсер.
        processor = WordReadProcessor()
        exchange = MagicMock(spec=Exchange)
        exchange.in_message = MagicMock()
        exchange.in_message.body = b"fake-docx"
        exchange.set_property = MagicMock()

        with patch("docx.Document") as mock_doc_cls:
            mock_doc = MagicMock()
            mock_doc.paragraphs = [MagicMock(text="para1"), MagicMock(text="para2")]
            mock_doc_cls.return_value = mock_doc
            await processor.process(exchange, MagicMock())

        exchange.set_property.assert_called()


class TestWordWriteProcessor:
    """Tests for WordWriteProcessor."""

    @pytest.mark.asyncio
    async def test_process_writes_text(self) -> None:
        # S164 W1: mock actual python-docx Document для word write.
        processor = WordWriteProcessor()
        exchange = MagicMock(spec=Exchange)
        exchange.in_message = MagicMock()
        exchange.in_message.body = {"content": "hello"}
        exchange.set_property = MagicMock()

        with patch("docx.Document") as mock_doc_cls:
            mock_doc = MagicMock()
            mock_doc_cls.return_value = mock_doc
            await processor.process(exchange, MagicMock())

        exchange.set_property.assert_called()


class TestExcelReadProcessor:
    """Tests for ExcelReadProcessor."""

    @pytest.mark.asyncio
    async def test_process_reads_excel(self) -> None:
        # S164 W1: mock actual openpyxl для excel read.
        processor = ExcelReadProcessor()
        exchange = MagicMock(spec=Exchange)
        exchange.in_message = MagicMock()
        exchange.in_message.body = b"fake-xlsx"
        exchange.set_property = MagicMock()

        with patch("openpyxl.load_workbook") as mock_wb:
            mock_book = MagicMock()
            mock_sheet = MagicMock()
            mock_sheet.iter_rows.return_value = [["col1", "col2"], ["v1", "v2"]]
            mock_book.active = mock_sheet
            mock_wb.return_value = mock_book
            await processor.process(exchange, MagicMock())

        exchange.set_property.assert_called()
