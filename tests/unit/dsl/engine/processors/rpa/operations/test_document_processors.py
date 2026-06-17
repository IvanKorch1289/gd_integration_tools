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
        processor = PdfReadProcessor()
        exchange = MagicMock(spec=Exchange)
        exchange.in_message = MagicMock()
        exchange.in_message.body = {"file_path": "test.pdf"}
        exchange.set_property = MagicMock()

        with patch("src.backend.dsl.engine.processors.rpa.documents.PdfReadProcessor._read_pdf", new_callable=AsyncMock) as mock_read:
            mock_read.return_value = "extracted text"
            await processor.process(exchange, MagicMock())

        exchange.set_property.assert_called()


class TestPdfMergeProcessor:
    """Tests for PdfMergeProcessor."""

    @pytest.mark.asyncio
    async def test_process_merges_pdfs(self) -> None:
        processor = PdfMergeProcessor()
        exchange = MagicMock(spec=Exchange)
        exchange.in_message = MagicMock()
        exchange.in_message.body = {"file_paths": ["a.pdf", "b.pdf"]}
        exchange.set_property = MagicMock()

        with patch("src.backend.dsl.engine.processors.rpa.documents.PdfMergeProcessor._merge_pdfs", new_callable=AsyncMock) as mock_merge:
            mock_merge.return_value = "merged.pdf"
            await processor.process(exchange, MagicMock())

        exchange.set_property.assert_called()


class TestWordReadProcessor:
    """Tests for WordReadProcessor."""

    @pytest.mark.asyncio
    async def test_process_extracts_text(self) -> None:
        processor = WordReadProcessor()
        exchange = MagicMock(spec=Exchange)
        exchange.in_message = MagicMock()
        exchange.in_message.body = {"file_path": "test.docx"}
        exchange.set_property = MagicMock()

        with patch("src.backend.dsl.engine.processors.rpa.documents.WordReadProcessor._read_word", new_callable=AsyncMock) as mock_read:
            mock_read.return_value = "extracted text"
            await processor.process(exchange, MagicMock())

        exchange.set_property.assert_called()


class TestWordWriteProcessor:
    """Tests for WordWriteProcessor."""

    @pytest.mark.asyncio
    async def test_process_writes_text(self) -> None:
        processor = WordWriteProcessor()
        exchange = MagicMock(spec=Exchange)
        exchange.in_message = MagicMock()
        exchange.in_message.body = {"content": "hello", "file_path": "out.docx"}
        exchange.set_property = MagicMock()

        with patch("src.backend.dsl.engine.processors.rpa.documents.WordWriteProcessor._write_word", new_callable=AsyncMock) as mock_write:
            mock_write.return_value = "out.docx"
            await processor.process(exchange, MagicMock())

        exchange.set_property.assert_called()


class TestExcelReadProcessor:
    """Tests for ExcelReadProcessor."""

    @pytest.mark.asyncio
    async def test_process_reads_excel(self) -> None:
        processor = ExcelReadProcessor()
        exchange = MagicMock(spec=Exchange)
        exchange.in_message = MagicMock()
        exchange.in_message.body = {"file_path": "test.xlsx"}
        exchange.set_property = MagicMock()

        with patch("src.backend.dsl.engine.processors.rpa.documents.ExcelReadProcessor._read_excel", new_callable=AsyncMock) as mock_read:
            mock_read.return_value = [{"col1": "val1"}]
            await processor.process(exchange, MagicMock())

        exchange.set_property.assert_called()
