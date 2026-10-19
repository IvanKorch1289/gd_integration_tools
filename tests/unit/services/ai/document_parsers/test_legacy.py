"""Tests for ``src.backend.services.ai.document_parsers._legacy``.

Last-resort парсеры: pypdf (PDF), python-docx (DOCX), UTF-8 (text).
"""

from __future__ import annotations

from src.backend.services.ai.document_parsers import _legacy as mod
from src.backend.services.ai.document_parsers._legacy import (
    _parse_docx,
    _parse_pdf,
    _parse_text,
)


class TestParseTextUtf8:
    """_parse_text — UTF-8 happy path."""

    def test_simple_ascii(self) -> None:
        text, warnings = _parse_text(b"hello world")
        assert text == "hello world"
        assert warnings == []

    def test_empty_bytes(self) -> None:
        text, warnings = _parse_text(b"")
        assert text == ""
        assert warnings == []

    def test_unicode(self) -> None:
        text, warnings = _parse_text("Привет мир".encode("utf-8"))
        assert text == "Привет мир"
        assert warnings == []

    def test_multiline(self) -> None:
        text, warnings = _parse_text(b"line1\nline2\nline3")
        assert text == "line1\nline2\nline3"
        assert warnings == []


class TestParseTextNonUtf8:
    """_parse_text — non-UTF8 fallback с replacement."""

    def test_latin1_bytes_replaced(self) -> None:
        # Байты в latin-1 (0xff = ÿ в latin-1, невалидный в UTF-8)
        content = b"\xff\xfe\xfd"
        text, warnings = _parse_text(content)
        # Replacement chars (\ufffd)
        assert "\ufffd" in text
        assert "non-utf8 bytes replaced" in warnings

    def test_returns_valid_string(self) -> None:
        # Даже для невалидного UTF-8 результат — str
        text, _ = _parse_text(b"\xff")
        assert isinstance(text, str)


class TestParseDocxContract:
    """_parse_docx — конверт из bytes → (text, warnings)."""

    def test_returns_tuple(self) -> None:
        # Минимальный DOCX — сгенерируем через python-docx
        import io

        from docx import Document

        doc = Document()
        doc.add_paragraph("Hello from DOCX")
        doc.add_paragraph("Second paragraph")

        buf = io.BytesIO()
        doc.save(buf)
        text, warnings = _parse_docx(buf.getvalue())

        assert isinstance(text, str)
        assert isinstance(warnings, list)
        assert "Hello from DOCX" in text
        assert "Second paragraph" in text

    def test_empty_docx_returns_empty_text(self) -> None:
        import io

        from docx import Document

        doc = Document()
        buf = io.BytesIO()
        doc.save(buf)

        text, warnings = _parse_docx(buf.getvalue())
        assert text == ""
        assert warnings == []

    def test_docx_with_table_cells(self) -> None:
        import io

        from docx import Document

        doc = Document()
        doc.add_paragraph("Header paragraph")
        table = doc.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "Cell A1"
        table.cell(0, 1).text = "Cell B1"
        table.cell(1, 0).text = "Cell A2"

        buf = io.BytesIO()
        doc.save(buf)

        text, warnings = _parse_docx(buf.getvalue())
        assert "Header paragraph" in text
        assert "Cell A1" in text
        assert "Cell B1" in text
        assert "Cell A2" in text
        assert warnings == []

    def test_docx_empty_paragraph_skipped(self) -> None:
        import io

        from docx import Document

        doc = Document()
        doc.add_paragraph("")  # empty
        doc.add_paragraph("Real text")
        doc.add_paragraph("   ")  # whitespace-only

        buf = io.BytesIO()
        doc.save(buf)

        text, _ = _parse_docx(buf.getvalue())
        # Только "Real text"
        assert "Real text" in text
        # Пустые полы не должны попасть в результат
        assert text.strip() == "Real text"


class TestParsePdfContract:
    """_parse_pdf — конверт из bytes → (text, warnings)."""

    def test_returns_tuple(self) -> None:
        # Минимальный PDF — попробуем сгенерировать через pypdf
        # Если не получится — пропустим с xfail
        try:
            from pypdf import PdfWriter

            writer = PdfWriter()
            writer.add_blank_page(width=72, height=72)
            import io

            buf = io.BytesIO()
            writer.write(buf)
            content = buf.getvalue()
        except Exception:
            content = b"%PDF-1.4\n%fake\n"

        text, warnings = _parse_pdf(content)
        assert isinstance(text, str)
        assert isinstance(warnings, list)

    def test_page_extraction_error_collected_as_warning(self, monkeypatch) -> None:
        """Если page.extract_text() бросает — warning собирается, не падает."""
        from unittest.mock import MagicMock

        # Создаём mock-reader с одной страницей, чей extract_text бросает
        mock_page = MagicMock()

        def boom():
            raise RuntimeError("simulated extraction failure")

        mock_page.extract_text = boom

        mock_reader = MagicMock()
        mock_reader.pages = iter([mock_page])

        # Patch pypdf.PdfReader внутри _legacy (late import: from pypdf import PdfReader)
        import pypdf

        monkeypatch.setattr(pypdf, "PdfReader", lambda _: mock_reader)

        text, warnings = _parse_pdf(b"%PDF-fake-bytes")
        # Warning должен содержать индекс страницы (0) и сообщение
        assert len(warnings) == 1
        assert "page 0" in warnings[0]
        assert "simulated extraction failure" in warnings[0]
        # Текст не упал
        assert text == ""


class TestAllExports:
    """__all__ экспорты."""

    def test_exports_three_parsers(self) -> None:
        assert "_parse_pdf" in mod.__all__
        assert "_parse_docx" in mod.__all__
        assert "_parse_text" in mod.__all__
        assert len(mod.__all__) == 3

    def test_functions_callable(self) -> None:
        assert callable(_parse_pdf)
        assert callable(_parse_docx)
        assert callable(_parse_text)


class TestParseTextWarningsAlwaysList:
    """warnings всегда list, даже если пустой."""

    def test_warnings_is_list_type(self) -> None:
        _, warnings = _parse_text(b"hello")
        assert isinstance(warnings, list)

    def test_warnings_empty_on_valid(self) -> None:
        _, warnings = _parse_text(b"valid utf-8")
        assert warnings == []