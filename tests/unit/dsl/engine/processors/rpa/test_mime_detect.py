"""TDD: MimeDetectProcessor (M25 P3 #7, D276).

MIME-type detection по magic bytes (Ponytail YAGNI: stdlib only).
Pattern (D276): thin wrapper.
"""
# ruff: noqa: S101
from __future__ import annotations

import pytest


class TestMimeDetectProcessor:
    def test_instantiates(self) -> None:
        from src.backend.dsl.engine.processors.rpa.mime_detect import (
            MimeDetectProcessor,
        )
        proc = MimeDetectProcessor()
        assert proc is not None

    def test_detect_pdf(self) -> None:
        from src.backend.dsl.engine.processors.rpa.mime_detect import (
            MimeDetectProcessor,
        )
        proc = MimeDetectProcessor()
        mime = proc.detect(b"%PDF-1.4\n...")
        assert mime == "application/pdf"

    def test_detect_png(self) -> None:
        from src.backend.dsl.engine.processors.rpa.mime_detect import (
            MimeDetectProcessor,
        )
        proc = MimeDetectProcessor()
        mime = proc.detect(b"\x89PNG\r\n\x1a\n...")
        assert mime == "image/png"

    def test_detect_jpeg(self) -> None:
        from src.backend.dsl.engine.processors.rpa.mime_detect import (
            MimeDetectProcessor,
        )
        proc = MimeDetectProcessor()
        mime = proc.detect(b"\xff\xd8\xff\xe0...")
        assert mime == "image/jpeg"

    def test_detect_zip(self) -> None:
        from src.backend.dsl.engine.processors.rpa.mime_detect import (
            MimeDetectProcessor,
        )
        proc = MimeDetectProcessor()
        # ZIP magic bytes (PK\x03\x04)
        mime = proc.detect(b"PK\x03\x04\x14\x00\x00\x00\x08\x00")
        assert mime == "application/zip"

    def test_unknown_returns_octet_stream(self) -> None:
        from src.backend.dsl.engine.processors.rpa.mime_detect import (
            MimeDetectProcessor,
        )
        proc = MimeDetectProcessor()
        mime = proc.detect(b"random data not matching any magic")
        assert mime == "application/octet-stream"
