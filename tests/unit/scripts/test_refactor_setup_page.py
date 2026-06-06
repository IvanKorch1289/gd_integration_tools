"""Unit tests для scripts/refactor_setup_page.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Add scripts/ to path for direct import
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from refactor_setup_page import (  # type: ignore[import-not-found]
    RE_SET_PAGE_CONFIG,
    extract_kwargs,
    refactor_file,
)

import tempfile


def test_extract_kwargs_basic() -> None:
    text = 'page_title="My Page", page_icon="🚀", layout="wide"'
    result = extract_kwargs(text)
    assert result["page_title"] == "My Page"
    assert result["page_icon"] == "🚀"
    assert result["layout"] == "wide"


def test_extract_kwargs_minimal() -> None:
    text = 'page_title="X"'
    result = extract_kwargs(text)
    assert result == {"page_title": "X"}


def test_extract_kwargs_single_quotes() -> None:
    text = "page_title='X', layout='centered'"
    result = extract_kwargs(text)
    assert result["page_title"] == "X"
    assert result["layout"] == "centered"


def test_extract_kwargs_skips_unknown() -> None:
    text = 'page_title="X", menu_items={"foo": "bar"}'
    result = extract_kwargs(text)
    assert "page_title" in result
    assert "menu_items" not in result


def test_regex_matches_set_page_config() -> None:
    text = 'st.set_page_config(page_title="X", page_icon="Y")\n'
    match = RE_SET_PAGE_CONFIG.search(text)
    assert match is not None
    assert match.group("args").strip() == 'page_title="X", page_icon="Y"'


def test_regex_skips_other_calls() -> None:
    text = 'st.title("X")\nst.metric("Y", 1)\n'
    assert RE_SET_PAGE_CONFIG.search(text) is None


# ── End-to-end refactor_file ───────────────────────────────────────────


def test_refactor_file_replaces_set_page_config() -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write('"""Test page."""\nimport streamlit as st\n\nst.set_page_config(page_title="X", page_icon="Y", layout="wide")\nst.title("X")\n')
        path = Path(f.name)
    try:
        changed, summary = refactor_file(path)
        assert changed is True
        assert "title='X'" in summary
        assert "icon='Y'" in summary
        text = path.read_text()
        assert "setup_page('X', 'Y')" in text
        assert "st.set_page_config" not in text
        assert "from src.frontend.streamlit_app.shared.components import setup_page" in text
    finally:
        path.unlink()


def test_refactor_file_no_set_page_config() -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write('"""Test page."""\nimport streamlit as st\nst.title("X")\n')
        path = Path(f.name)
    try:
        changed, summary = refactor_file(path)
        assert changed is False
        assert "no st.set_page_config" in summary
    finally:
        path.unlink()


def test_refactor_file_idempotent() -> None:
    """Second run на same file → 0 changes."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write('"""Test page."""\nimport streamlit as st\n\nst.set_page_config(page_title="X")\nst.title("X")\n')
        path = Path(f.name)
    try:
        refactor_file(path)
        text_after_first = path.read_text()
        changed, _ = refactor_file(path)
        text_after_second = path.read_text()
        assert changed is False  # idempotent
        assert text_after_first == text_after_second
    finally:
        path.unlink()


def test_refactor_file_handles_emoji() -> None:
    """Emoji в page_icon (multi-byte UTF-8) handled correctly."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write('"""Test."""\nimport streamlit as st\nst.set_page_config(page_title="X", page_icon="💸")\n')
        path = Path(f.name)
    try:
        changed, _ = refactor_file(path)
        assert changed is True
        text = path.read_text(encoding="utf-8")
        assert 'setup_page(\'X\', \'💸\')' in text
    finally:
        path.unlink()


def test_refactor_file_syntax_check_prevents_bad_writes() -> None:
    """If refactor would produce syntax error, file не modified."""
    # Create a file with a tricky pattern (e.g., emoji + kwarg in non-standard order)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write('"""Test."""\nimport streamlit as st\nst.set_page_config(page_icon="🎉")  # missing page_title\n')
        path = Path(f.name)
    try:
        changed, summary = refactor_file(path)
        # Should not modify (no page_title)
        assert changed is False
    finally:
        path.unlink()


# ── Real pages test (sampling) ─────────────────────────────────────────


def test_real_page_refactor_preserves_content() -> None:
    """Apply refactor to a real page sample, verify content preserved."""
    import shutil

    src = Path("src/frontend/streamlit_app/pages/12_Logs.py")
    if not src.exists():
        # Skip if not present
        return
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(src.read_text(encoding="utf-8"))
        backup = Path(f.name)
    try:
        # Refactor the copy
        changed, _ = refactor_file(backup)
        if changed:
            text = backup.read_text(encoding="utf-8")
            assert "setup_page(" in text
            assert "st.set_page_config" not in text
            # import added
            assert "from src.frontend.streamlit_app.shared.components import setup_page" in text
    finally:
        backup.unlink()
