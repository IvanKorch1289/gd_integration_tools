"""Streamlit deprecation gate: use_container_width detection.

S170 W14 (commit 348b761) заменил ``st.dataframe(..., use_container_width=True)``
на ``st.dataframe(..., width="stretch")`` — Streamlit API deprecated
``use_container_width`` с 2025-12-31, эмитит warning на каждом рендере.

Tool предотвращает regression:
- Сканирует ``src/frontend/streamlit_app/`` на наличие ``use_container_width=``
- Если найдено — fail-fast с конкретным файлом:line
- Запуск::

    python tools/check_streamlit_deprecations.py        # human-readable
    python tools/check_streamlit_deprecations.py --ci   # exit 1 на matches

Exit code 0 — нет matches;
Exit code 1 — найден deprecated API.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple

# Path: от корня tools/ поднимаемся до repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_FRONTEND_ROOT = _REPO_ROOT / "src" / "frontend" / "streamlit_app"

# Deprecated kwargs (Streamlit → modern replacement mapping).
# use_container_width=True   → width="stretch"
# use_container_width=False  → width="content"
# Match: kwarg (foo, use_container_width=...), attr (.use_container_width =),
# и dict-style (не покрываем — Streamlit API это не принимает).
DEPRECATED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:^|[\s,(\.=])use_container_width\s*="),
)


class Match(NamedTuple):
    """Результат одного deprecated match."""

    file: Path
    line_no: int
    line: str


def find_deprecated_usage(root: Path) -> list[Match]:
    """Сканирует .py файлы в root на наличие deprecated Streamlit kwargs.

    Args:
        root: директория для сканирования (recursive).

    Returns:
        Список matches с file/line/line content.
    """
    matches: list[Match] = []
    if not root.exists():
        return matches
    for py_file in root.rglob("*.py"):
        # Skip __pycache__ и venv.
        if "__pycache__" in py_file.parts or ".venv" in py_file.parts:
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_no, line in enumerate(content.splitlines(), 1):
            if any(p.search(line) for p in DEPRECATED_PATTERNS):
                matches.append(Match(file=py_file, line_no=line_no, line=line.strip()))
    return matches


def render_human(matches: list[Match]) -> str:
    """Human-readable report."""
    if not matches:
        return "Streamlit deprecations: 0 matches (all modern width='stretch' usage)."

    lines: list[str] = [
        f"Streamlit deprecations: {len(matches)} match(es) found",
        "=" * 60,
    ]
    for m in matches:
        rel = m.file.relative_to(_REPO_ROOT)
        lines.append(f"  {rel}:{m.line_no}: {m.line[:80]}")
    lines.append("=" * 60)
    lines.append("Fix: replace 'use_container_width=True' → width='stretch'")
    lines.append("     replace 'use_container_width=False' → width='content'")
    return "\n".join(lines)


def main() -> int:
    """Точка входа: human-readable или CI mode."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ci",
        action="store_true",
        help="Exit code 1 на matches (for CI gates).",
    )
    args = parser.parse_args()

    matches = find_deprecated_usage(_FRONTEND_ROOT)
    print(render_human(matches))

    if args.ci:
        return 1 if matches else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())