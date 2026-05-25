"""Unit-тесты PDF reader facade — ``[wave:s18/w0-goal-driven-sweep-5-pdf-facade]``."""

# ruff: noqa: S101

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


def _ensure_module_absent(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """Сделать ``import <name>`` бросать ImportError."""
    monkeypatch.setitem(sys.modules, name, None)


def test_pypdfium2_primary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """pypdfium2 присутствует → используется первым; pypdf не вызывается."""
    pdf_file = tmp_path / "doc.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 fake")

    fake_pdfium = types.ModuleType("pypdfium2")
    calls: list[str] = []

    class _FakeTextPage:
        def get_text_range(self) -> str:
            return "page-one"

        def close(self) -> None:
            calls.append("textpage.close")

    class _FakePage:
        def get_textpage(self) -> _FakeTextPage:
            return _FakeTextPage()

        def close(self) -> None:
            calls.append("page.close")

    class _FakePdfDocument:
        def __init__(self, _path: str) -> None:
            calls.append("open")

        def __iter__(self) -> object:
            return iter([_FakePage(), _FakePage()])

        def close(self) -> None:
            calls.append("doc.close")

    fake_pdfium.PdfDocument = _FakePdfDocument  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pypdfium2", fake_pdfium)

    # Если pypdf будет вызван — это будет ошибкой. Подменяем модуль чтобы упало,
    # но pypdf2 не должен вызываться благодаря короткому замыканию pypdfium2.
    _ensure_module_absent(monkeypatch, "pypdf")

    from src.backend.utilities.pdf_reader import read_pdf

    result = read_pdf(pdf_file)
    assert result == "page-one\n\npage-one"
    # Каждая страница закрылась, doc закрылся.
    assert calls.count("page.close") == 2
    assert calls.count("textpage.close") == 2
    assert calls.count("doc.close") == 1


def test_pypdf_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """pypdfium2 → ImportError, pypdf отрабатывает."""
    pdf_file = tmp_path / "doc.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 fake")

    _ensure_module_absent(monkeypatch, "pypdfium2")

    fake_pypdf = types.ModuleType("pypdf")

    class _FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class _FakePdfReader:
        def __init__(self, _path: str) -> None:
            self.pages = [_FakePage("alpha"), _FakePage("beta")]

    fake_pypdf.PdfReader = _FakePdfReader  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pypdf", fake_pypdf)

    from src.backend.utilities.pdf_reader import read_pdf

    assert read_pdf(pdf_file) == "alpha\n\nbeta"


def test_both_unavailable_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Оба backend'а отсутствуют → PdfReaderUnavailable."""
    pdf_file = tmp_path / "doc.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 fake")

    _ensure_module_absent(monkeypatch, "pypdfium2")
    _ensure_module_absent(monkeypatch, "pypdf")

    from src.backend.utilities.pdf_reader import PdfReaderUnavailable, read_pdf

    with pytest.raises(PdfReaderUnavailable, match="pypdfium2"):
        read_pdf(pdf_file)


def test_file_not_found(tmp_path: Path) -> None:
    """Несуществующий файл → FileNotFoundError."""
    from src.backend.utilities.pdf_reader import read_pdf

    missing = tmp_path / "nope.pdf"
    with pytest.raises(FileNotFoundError, match="не найден"):
        read_pdf(missing)
