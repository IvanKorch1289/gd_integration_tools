"""Тесты MIME-sniff'инга для расширений Sprint S5."""

from __future__ import annotations

import pytest

from src.backend.services.ai.document_parsers import sniff_mime


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        (
            "a.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
        ("a.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("a.html", "text/html"),
        ("a.htm", "text/html"),
        ("a.csv", "text/csv"),
        ("a.json", "application/json"),
        ("a.md", "text/markdown"),
        ("a.markdown", "text/markdown"),
        ("a.txt", "text/plain"),
        (
            "a.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        ("a.pdf", "application/pdf"),
    ],
)
def test_sniffer_recognizes_extension(filename: str, expected: str) -> None:
    assert sniff_mime(filename, None) == expected


def test_sniffer_prefers_declared_over_extension() -> None:
    # Если declared не octet-stream — возвращаем как есть.
    assert sniff_mime("a.pptx", "application/json") == "application/json"


def test_sniffer_overrides_octet_stream_by_extension() -> None:
    assert (
        sniff_mime("a.pptx", "application/octet-stream")
        == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )


def test_sniffer_fallback_when_no_extension() -> None:
    assert sniff_mime("noext", None) == "application/octet-stream"
    assert sniff_mime(None, None) == "application/octet-stream"
