"""TDD: EncodingDetectProcessor (M25 P3 #8, D277).

Encoding detection по BOM + UTF-8 validation (Ponytail YAGNI: stdlib only).
Pattern (D277): thin wrapper.
"""
# ruff: noqa: S101
from __future__ import annotations

import pytest


class TestEncodingDetectProcessor:
    def test_instantiates(self) -> None:
        from src.backend.dsl.engine.processors.rpa.encoding_detect import (
            EncodingDetectProcessor,
        )
        proc = EncodingDetectProcessor()
        assert proc is not None

    def test_detect_utf8_bom(self) -> None:
        from src.backend.dsl.engine.processors.rpa.encoding_detect import (
            EncodingDetectProcessor,
        )
        proc = EncodingDetectProcessor()
        enc = proc.detect(b"\xef\xbb\xbfHello, world!")
        assert enc == "utf-8-sig"

    def test_detect_utf16_le_bom(self) -> None:
        from src.backend.dsl.engine.processors.rpa.encoding_detect import (
            EncodingDetectProcessor,
        )
        proc = EncodingDetectProcessor()
        enc = proc.detect(b"\xff\xfeH\x00e\x00l\x00l\x00o\x00")
        assert enc == "utf-16-le"

    def test_detect_utf16_be_bom(self) -> None:
        from src.backend.dsl.engine.processors.rpa.encoding_detect import (
            EncodingDetectProcessor,
        )
        proc = EncodingDetectProcessor()
        enc = proc.detect(b"\xfe\xff\x00H\x00e\x00l\x00l\x00o\x00")
        assert enc == "utf-16-be"

    def test_detect_utf8_no_bom(self) -> None:
        from src.backend.dsl.engine.processors.rpa.encoding_detect import (
            EncodingDetectProcessor,
        )
        proc = EncodingDetectProcessor()
        # Валидный UTF-8 без BOM
        enc = proc.detect("Hello, мир!".encode("utf-8"))
        assert enc == "utf-8"

    def test_detect_latin1_fallback(self) -> None:
        from src.backend.dsl.engine.processors.rpa.encoding_detect import (
            EncodingDetectProcessor,
        )
        proc = EncodingDetectProcessor()
        # Байты которые невалидны в UTF-8
        enc = proc.detect(bytes([0xC0, 0xC1, 0xF5, 0xF6]))
        # Должен быть fallback — не обязательно latin-1, может быть windows-1252
        assert enc == "latin-1"

    def test_empty_returns_utf8_default(self) -> None:
        from src.backend.dsl.engine.processors.rpa.encoding_detect import (
            EncodingDetectProcessor,
        )
        proc = EncodingDetectProcessor()
        enc = proc.detect(b"")
        assert enc == "utf-8"  # default для пустого файла
