class TestOfficeExtractProcessor:
    def test_instantiates(self) -> None:
        from src.backend.dsl.engine.processors.rpa.office_extract import (
            OfficeExtractProcessor,
        )
        proc = OfficeExtractProcessor()
        assert proc is not None

    def test_extract_returns_string_or_none(self) -> None:
        """extract() возвращает string (или None если не .docx/.xlsx)."""
        from src.backend.dsl.engine.processors.rpa.office_extract import (
            OfficeExtractProcessor,
        )
        proc = OfficeExtractProcessor()
        # Mock bytes
        result = proc.extract(b"PK\\x03\\x04random docx content")
        # Может быть None (no python-docx) или string — не должно падать
        assert result is None or isinstance(result, str)

    def _make_minimal_docx(self) -> bytes:
        """Создаёт минимальный валидный .docx zip с word/document.xml."""
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("word/document.xml", "<doc/>")
        return buf.getvalue()

    def _make_minimal_xlsx(self) -> bytes:
        """Создаёт минимальный валидный .xlsx zip с xl/workbook.xml."""
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("xl/workbook.xml", "<workbook/>")
        return buf.getvalue()

    def test_detect_format(self) -> None:
        """detect_format() различает .docx vs .xlsx."""
        from src.backend.dsl.engine.processors.rpa.office_extract import (
            OfficeExtractProcessor,
        )
        proc = OfficeExtractProcessor()
        # .docx = wordprocessingml.document
        assert proc.detect_format(self._make_minimal_docx()) == "docx"
        # .xlsx = spreadsheetml.sheet
        assert proc.detect_format(self._make_minimal_xlsx()) == "xlsx"
        # Unknown
        assert proc.detect_format(b"PK\\x03\\x04random") == "unknown"
        # Not ZIP
        assert proc.detect_format(b"random") == "unknown"
