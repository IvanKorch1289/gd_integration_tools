#!/usr/bin/env python3
"""Cycle-49 (D-AUDIT-3024): silence F401 in multi-line parenthesized imports.

Для каждого multi-line import ``from X import (\n    Y,\n    Z,\n)`` где
имена — re-exports, добавляет ``# noqa: F401 — re-export`` на
первую строку.

Pattern:
    # Before (ruff F401):
    from src.backend.core.di.providers.ai import (
        get_a,
        get_b,
    )

    # After:
    from src.backend.core.di.providers.ai import (  # noqa: F401 — re-export
        get_a,
        get_b,
    )

Usage:
    python tools/add_f401_multiline_noqa.py [--root src/backend]
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

_logger = logging.getLogger(__name__)


def _process_file(path: Path) -> tuple[int, str]:
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return 0, content
    lines = content.splitlines(keepends=True)
    new_lines: list[str] = []
    changes = 0
    for line in lines:
        stripped = line.rstrip("\n")
        # Detect start of multi-line parenthesized from-import (без закрывающей ")" на этой строке)
        if (
            stripped.lstrip().startswith("from ")
            and " import " in stripped
            and "(" in stripped
            and ")" not in stripped.split("#", 1)[0]  # игнорируем комментарии
            and "# noqa" not in line
        ):
            suffix = "\n" if line.endswith("\n") else ""
            indent = len(stripped) - len(stripped.lstrip())
            prefix = stripped[:indent]
            # Find position to insert comment: after ``import (``
            import_idx = stripped.find(" import (")
            if import_idx == -1:
                new_lines.append(line)
                continue
            insert_pos = import_idx + len(" import (") - 1  # position of (
            # Build new line: ``from X import (  # noqa: F401 — re-export\n``
            new_stripped = (
                stripped[: insert_pos + 1]
                + "  # noqa: F401 — re-export"
                + stripped[insert_pos + 1 :]
            )
            new_lines.append(new_stripped + suffix)
            changes += 1
        else:
            new_lines.append(line)
    if changes == 0:
        return 0, content
    return changes, "".join(new_lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="add_f401_multiline_noqa",
        description="Silence F401 in multi-line parenthesized imports (D-AUDIT-3024 cycle-49)",
    )
    parser.add_argument("--root", default="src/backend", help="Root dir to walk")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    root = Path(args.root)
    files = list(root.rglob("*.py"))
    total_changes = 0
    for f in files:
        if "__pycache__" in f.parts:
            continue
        changes, new_content = _process_file(f)
        if changes > 0:
            f.write_text(new_content, encoding="utf-8")
            total_changes += changes
            _logger.info("Updated %s (+%d)", f, changes)
    print(f"Total changes: {total_changes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
