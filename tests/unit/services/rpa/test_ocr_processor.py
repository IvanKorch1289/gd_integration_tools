"""Unit tests for src.backend.services.rpa.ocr_processor."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.backend.services.rpa.ocr_processor import (
    NoOpOCRProcessor,
    PytesseractOCRProcessor,
    from_environment,
)


class TestNoOpOCRProcessor:
    def test_available(self) -> None:
        proc = NoOpOCRProcessor()
        assert proc.is_available is True

    def test_recognize(self, caplog: pytest.LogCaptureFixture) -> None:
        proc = NoOpOCRProcessor()
        with caplog.at_level("WARNING"):
            result = proc.recognize("/img.png", lang="eng")
        assert result == ""
        assert "no backend configured" in caplog.text


class TestPytesseractOCRProcessor:
    def test_available_when_installed(self) -> None:
        with patch.dict("sys.modules", {"pytesseract": MagicMock()}):
            proc = PytesseractOCRProcessor()
            assert proc.is_available is True

    def test_not_installed(self) -> None:
        with patch.dict("sys.modules", {"pytesseract": None}):
            proc = PytesseractOCRProcessor()
            assert proc.is_available is False

    def test_recognize_success(self) -> None:
        fake_pt = MagicMock()
        fake_pt.image_to_string.return_value = "hello"
        with patch.dict("sys.modules", {"pytesseract": fake_pt}):
            proc = PytesseractOCRProcessor()
            assert proc.recognize("/img.png") == "hello"
            fake_pt.image_to_string.assert_called_once_with("/img.png", lang="eng")

    def test_recognize_import_error(self, caplog: pytest.LogCaptureFixture) -> None:
        with patch.dict("sys.modules", {"pytesseract": None}):
            proc = PytesseractOCRProcessor()
            with caplog.at_level("WARNING"):
                assert proc.recognize("/img.png") == ""
        assert "pytesseract not installed" in caplog.text

    def test_recognize_runtime_error(self, caplog: pytest.LogCaptureFixture) -> None:
        fake_pt = MagicMock()
        fake_pt.image_to_string.side_effect = RuntimeError("tess fail")
        with patch.dict("sys.modules", {"pytesseract": fake_pt}):
            proc = PytesseractOCRProcessor()
            with caplog.at_level("WARNING"):
                assert proc.recognize("/img.png") == ""
        assert "recognize failed" in caplog.text


class TestFromEnvironment:
    def test_feature_flag_off(self) -> None:
        with patch("src.backend.core.config.features.feature_flags") as ff:
            ff.rpa_ocr_enabled = False
            proc = from_environment()
        assert isinstance(proc, NoOpOCRProcessor)

    def test_feature_flag_on_no_pytesseract(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with patch("src.backend.core.config.features.feature_flags") as ff:
            ff.rpa_ocr_enabled = True
            with patch.dict("sys.modules", {"pytesseract": None}):
                with caplog.at_level("WARNING"):
                    proc = from_environment()
        assert isinstance(proc, NoOpOCRProcessor)
        assert "fallback на NoOp" in caplog.text

    def test_feature_flag_on_ok(self) -> None:
        with patch("src.backend.core.config.features.feature_flags") as ff:
            ff.rpa_ocr_enabled = True
            with patch.dict("sys.modules", {"pytesseract": MagicMock()}):
                proc = from_environment()
        assert isinstance(proc, PytesseractOCRProcessor)

    def test_import_error_early(self) -> None:
        with patch(
            "src.backend.core.config.features.feature_flags", side_effect=ImportError
        ):
            proc = from_environment()
        assert isinstance(proc, NoOpOCRProcessor)
