"""Unit-тесты OCR-процессора — Wave ``[wave:s18/w0-goal-driven-sweep-2-ocr]``."""

# ruff: noqa: S101, S108

from __future__ import annotations

import sys
from typing import Any

import pytest

from src.backend.services.rpa.ocr_processor import (
    NoOpOCRProcessor,
    PytesseractOCRProcessor,
    from_environment,
)


def test_noop_returns_empty_string() -> None:
    """NoOp возвращает пустую строку при любом входе."""
    proc = NoOpOCRProcessor()
    assert proc.is_available is True
    assert proc.recognize("/tmp/screen.png") == ""
    assert proc.recognize("/tmp/screen.png", lang="rus") == ""


def test_pytesseract_unavailable_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При отсутствии pytesseract — empty string без падения."""
    monkeypatch.setitem(sys.modules, "pytesseract", None)
    proc = PytesseractOCRProcessor()
    assert proc.is_available is False
    assert proc.recognize("/tmp/screen.png") == ""


def test_pytesseract_calls_image_to_string(monkeypatch: pytest.MonkeyPatch) -> None:
    """Когда pytesseract присутствует — делегирует image_to_string."""
    import types

    fake = types.ModuleType("pytesseract")
    captured: dict[str, Any] = {}

    def _image_to_string(path: str, lang: str = "eng") -> str:
        captured["path"] = path
        captured["lang"] = lang
        return "Hello, world!"

    fake.image_to_string = _image_to_string  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pytesseract", fake)
    proc = PytesseractOCRProcessor()
    assert proc.is_available is True
    result = proc.recognize("/tmp/img.png", lang="eng+rus")
    assert result == "Hello, world!"
    assert captured == {"path": "/tmp/img.png", "lang": "eng+rus"}


def test_from_environment_returns_noop_when_flag_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При выключенном feature-flag фабрика возвращает NoOp."""
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "rpa_ocr_enabled", False)
    assert isinstance(from_environment(), NoOpOCRProcessor)


def test_from_environment_returns_noop_when_pytesseract_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При включённом flag, но без pytesseract — фабрика возвращает NoOp."""
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "rpa_ocr_enabled", True)
    monkeypatch.setitem(sys.modules, "pytesseract", None)
    result = from_environment()
    assert isinstance(result, NoOpOCRProcessor)
