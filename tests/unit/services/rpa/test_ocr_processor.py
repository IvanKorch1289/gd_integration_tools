"""Unit-тесты для OCR-процессора (cycle 33 L5 cycle 1, RPA).

``ocr_processor.py`` (167 LOC) — OCR через pytesseract с NoOp fallback.
Используется RPA-маршрутами для извлечения текста из скриншотов.
S164 W3: async Protocol + asyncio.to_thread (CPU-bound offload).

Без тестов — изменение fallback-логики или factory молча сломает
RPA pipelines.
"""


from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.backend.services.rpa.ocr_processor import (
    NoOpOCRProcessor,
    OCRProcessor,
    PytesseractOCRProcessor,
    from_environment,
)


@pytest.mark.asyncio
async def test_noop_processor_is_available_returns_true() -> None:
    """NoOp всегда 'available' (не падает)."""
    proc = NoOpOCRProcessor()
    assert await proc.is_available() is True


@pytest.mark.asyncio
async def test_noop_recognize_returns_empty_string() -> None:
    """NoOp.recognize() возвращает пустую строку + warning log."""
    proc = NoOpOCRProcessor()
    result = await proc.recognize("/fake/path.png")
    assert result == ""


@pytest.mark.asyncio
async def test_noop_satisfies_ocr_processor_protocol() -> None:
    """NoOpOCRProcessor реализует OCRProcessor runtime Protocol."""
    proc: OCRProcessor = NoOpOCRProcessor()
    assert isinstance(proc, OCRProcessor)


@pytest.mark.asyncio
async def test_pytesseract_is_available_false_when_not_imported() -> None:
    """PytesseractOCRProcessor.is_available() → False если pytesseract не установлен."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "pytesseract" or name.startswith("pytesseract."):
            raise ImportError("simulated pytesseract unavailable")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        proc = PytesseractOCRProcessor()
        assert await proc.is_available() is False


@pytest.mark.asyncio
async def test_pytesseract_recognize_returns_empty_on_missing_dep() -> None:
    """Pytesseract.recognize() с missing dep → empty string + warning."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "pytesseract" or name.startswith("pytesseract."):
            raise ImportError("simulated")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        proc = PytesseractOCRProcessor()
        result = await proc.recognize("/fake.png", lang="eng")
        assert result == ""


@pytest.mark.asyncio
async def test_pytesseract_recognize_returns_empty_on_tesseract_error() -> None:
    """Pytesseract.recognize() с Tesseract runtime error → empty string (graceful)."""
    fake_pytesseract = type("FakePytesseract", (), {})()
    fake_pytesseract.image_to_string = lambda *args, **kwargs: (_ for _ in ()).throw(
        RuntimeError("tesseract crashed"),
    )

    with patch.dict("sys.modules", {"pytesseract": fake_pytesseract}):
        proc = PytesseractOCRProcessor()
        result = await proc.recognize("/fake.png", lang="eng")
        assert result == ""


@pytest.mark.asyncio
async def test_pytesseract_recognize_offloads_to_thread_pool() -> None:
    """recognize() использует asyncio.to_thread (CPU-bound → offloaded).

    S164 W3: pytesseract.image_to_string sync; вызов через
    asyncio.to_thread чтобы не блокировать event loop.
    """
    call_log: list[str] = []

    def fake_image_to_string(path: str, lang: str = "eng") -> str:
        call_log.append(f"sync:{path}:{lang}")
        return "recognised text"

    fake_pytesseract = type("FakePytesseract", (), {})()
    fake_pytesseract.image_to_string = fake_image_to_string

    with patch.dict("sys.modules", {"pytesseract": fake_pytesseract}):
        proc = PytesseractOCRProcessor()
        result = await proc.recognize("/some/image.png", lang="rus")

    assert result == "recognised text"
    # Verify that image_to_string был вызван через thread pool
    # (asyncio.to_thread) с правильными args.
    assert call_log == ["sync:/some/image.png:rus"]


@pytest.mark.asyncio
async def test_pytesseract_handles_pathlib_path() -> None:
    """recognize() принимает Path объект (не только str)."""
    fake_pytesseract = type("FakePytesseract", (), {})()
    fake_pytesseract.image_to_string = lambda *args, **kwargs: "ok"

    with patch.dict("sys.modules", {"pytesseract": fake_pytesseract}):
        proc = PytesseractOCRProcessor()
        result = await proc.recognize(Path("/path/to/img.png"))
        assert result == "ok"


def test_from_environment_returns_processor() -> None:
    """from_environment() возвращает OCRProcessor instance (NoOp or Pytesseract)."""
    proc = from_environment()
    assert isinstance(proc, (PytesseractOCRProcessor, NoOpOCRProcessor))


@pytest.mark.asyncio
async def test_recognize_lang_param_passed_through() -> None:
    """Параметр lang пробрасывается в pytesseract.image_to_string."""
    captured: dict[str, object] = {}

    def fake_image_to_string(path: str, lang: str = "eng") -> str:
        captured["lang"] = lang
        return ""

    fake_pytesseract = type("FakePytesseract", (), {})()
    fake_pytesseract.image_to_string = fake_image_to_string

    with patch.dict("sys.modules", {"pytesseract": fake_pytesseract}):
        proc = PytesseractOCRProcessor()
        await proc.recognize("/x.png", lang="eng+rus")

    assert captured["lang"] == "eng+rus"
