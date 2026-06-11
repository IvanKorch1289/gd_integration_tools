#!/usr/bin/env python3
"""Bulk refactor: replace inline st.set_page_config with setup_page().

Uses ast для extract kwargs (title, icon). Then uses regex для actual
text replacement (avoids Python 3.14 ast byte-offset vs char-offset issue).

Pattern: ``st.set_page_config(page_title="X", page_icon="Y", layout=..., ...)``
Replace with: ``setup_page("X", "Y")``
Plus adds import for setup_page.

Usage:
    python tools/refactor_setup_page.py [--dry-run]
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

PAGES_DIR = Path("src/frontend/streamlit_app/pages")

# Regex to match st.set_page_config calls (single line, with optional kwargs)
# Order of kwargs doesn't matter; only page_title and page_icon are extracted.
RE_SET_PAGE_CONFIG = re.compile(
    r'st\.set_page_config\s*\('
    r'(?P<args>[^)]*?)'
    r'\)\s*$',  # End of line (no multi-line support — Streamlit calls are single-line)
    re.MULTILINE,
)


def extract_kwargs(call_text: str) -> dict[str, str]:
    """Extract kwarg values from set_page_config call text."""
    result: dict[str, str] = {}
    # Pattern: kwarg="value" or kwarg='value'
    for m in re.finditer(r'(\w+)\s*=\s*(["\'])((?:(?!\2).)*)\2', call_text):
        key = m.group(1)
        value = m.group(3)
        if key in ("page_title", "page_icon", "layout", "initial_sidebar_state"):
            result[key] = value
    return result


def refactor_file(path: Path) -> tuple[bool, str]:
    """Refactor single file."""
    text = path.read_text(encoding="utf-8")
    if "st.set_page_config" not in text:
        return False, "no st.set_page_config"

    # Find call using regex (char-based, no ast issues)
    matches = list(RE_SET_PAGE_CONFIG.finditer(text))
    if not matches:
        return False, "no regex match"

    new_text = text
    for m in reversed(matches):
        kwargs = extract_kwargs(m.group("args"))
        title = kwargs.get("page_title")
        if title is None:
            return False, "no page_title in call"
        icon = kwargs.get("page_icon", "")

        replacement = f"setup_page({title!r}, {icon!r})"
        new_text = new_text[: m.start()] + replacement + new_text[m.end() :]

    # Add import if not present
    setup_page_import = "from src.frontend.streamlit_app.shared.components import setup_page"
    if "setup_page(" in new_text and setup_page_import not in new_text:
        if "import streamlit as st" in new_text:
            new_text = new_text.replace(
                "import streamlit as st",
                f"import streamlit as st\n\n{setup_page_import}",
                1,
            )

    if new_text == text:
        return False, "no change"

    # Verify syntax before writing
    try:
        ast.parse(new_text)
    except SyntaxError as exc:
        return False, f"syntax error after refactor: {exc}"

    path.write_text(new_text, encoding="utf-8")
    return True, f"title={title!r} icon={icon!r}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    pages = sorted(PAGES_DIR.glob("*.py"))
    print(f"Found {len(pages)} pages")

    changed_count = 0
    skipped_count = 0
    error_count = 0

    for page in pages:
        try:
            changed, summary = refactor_file(page)
            if changed:
                changed_count += 1
                if not args.dry_run:
                    print(f"  ✓ {page.name}: {summary}")
            else:
                skipped_count += 1
        except Exception as exc:
            error_count += 1
            print(f"  ✗ {page.name}: ERROR {exc}")

    print(f"\nResult: {changed_count} changed, {skipped_count} skipped, {error_count} errors")
    if args.dry_run:
        print("(dry-run, no files modified)")
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
