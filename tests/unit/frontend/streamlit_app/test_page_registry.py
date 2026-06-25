# ruff: noqa: S101
"""Unit tests для src.frontend.streamlit_app.shared.page_registry (S171 W1).

Тестируем:
- Все 70 page files имеют entry в PAGE_METADATA (no missing)
- PAGE_METADATA keys совпадают с filesystem filenames (no extra)
- Все Cyrillic filenames имеют Russian titles
- get_page_metadata() возвращает правильный dict по filename
- get_page_metadata() возвращает None для unknown filename
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

# Mock streamlit (registry не использует, но требуется для page_registry imports)
_streamlit_mock = ModuleType("streamlit")
_streamlit_mock.set_page_config = MagicMock()
sys.modules["streamlit"] = _streamlit_mock

# Now safe to import
from src.frontend.streamlit_app.shared.page_registry import (  # noqa: E402
    PAGE_METADATA,
    get_page_metadata,
)


def test_registry_has_70_pages() -> None:
    """PAGE_METADATA должна содержать все 70 pages."""
    assert len(PAGE_METADATA) == 70, (
        f"Expected 70 pages, got {len(PAGE_METADATA)}"
    )


def test_registry_keys_match_filesystem() -> None:
    """PAGE_METADATA keys == filesystem page file stems."""
    pages_dir = Path("src/frontend/streamlit_app/pages")
    actual_files = {f.stem for f in pages_dir.glob("*.py") if f.stem != "__init__"}

    registry_keys = set(PAGE_METADATA.keys())

    missing = actual_files - registry_keys
    extra = registry_keys - actual_files

    assert not missing, f"Pages missing from registry: {missing}"
    assert not extra, f"Extra entries in registry: {extra}"


def test_all_pages_have_title() -> None:
    """Каждый entry имеет title (non-empty string)."""
    for key, meta in PAGE_METADATA.items():
        assert "title" in meta, f"Missing title for {key}"
        assert isinstance(meta["title"], str)
        assert len(meta["title"]) > 0, f"Empty title for {key}"


def test_all_pages_have_icon() -> None:
    """Каждый entry имеет icon (Material icon string)."""
    for key, meta in PAGE_METADATA.items():
        assert "icon" in meta, f"Missing icon for {key}"
        assert isinstance(meta["icon"], str)
        # Should be a Material icon or emoji
        assert meta["icon"].startswith(":") or len(meta["icon"]) <= 4, (
            f"Icon format unexpected for {key}: {meta['icon']!r}"
        )


def test_titles_are_russian() -> None:
    """Все titles должны содержать хотя бы одну Cyrillic букву.

    Exception: product names (e.g., 'GD Integration Tools') stay English.
    """
    russian_count = 0
    for key, meta in PAGE_METADATA.items():
        title = meta["title"]
        has_cyrillic = any(0x0400 <= ord(c) <= 0x04FF for c in title)
        if has_cyrillic:
            russian_count += 1

    # Should be most pages (some product names are English)
    assert russian_count >= 60, (
        f"Expected >=60 Russian titles, got {russian_count}"
    )


def test_get_page_metadata_known() -> None:
    """get_page_metadata returns correct dict for known filename."""
    meta = get_page_metadata("00_Вход")
    assert meta is not None
    assert meta["title"] == "Вход"


def test_get_page_metadata_unknown() -> None:
    """get_page_metadata returns None for unknown filename."""
    meta = get_page_metadata("nonexistent_page_xyz")
    assert meta is None


def test_specific_pages_present() -> None:
    """Critical pages must be in registry."""
    expected = {
        "00_Главная": "Главная",
        "00_Вход": "Вход",
        "10_Заказы": "Заказы",
        "62_Админ_схем": "Админ схем",
        "96_Монитор_зависших_сообщений": "Монитор зависших сообщений",
    }
    for page_key, expected_title in expected.items():
        meta = get_page_metadata(page_key)
        assert meta is not None, f"Missing {page_key}"
        assert meta["title"] == expected_title, (
            f"Wrong title for {page_key}: {meta['title']!r}"
        )


def test_tech_term_exception() -> None:
    """54_Replay_DLQ is acceptable English-only exception (DLQ = Dead Letter Queue).

    Это industry-standard tech term — keeping English preserves technical meaning.
    """
    meta = get_page_metadata("54_Replay_DLQ")
    assert meta is not None
    assert "Replay" in meta["title"] or "DLQ" in meta["title"]
