#!/usr/bin/env python3
"""Cycle-48 (D-AUDIT-3022): silence F401 in __init__.py via explicit re-export aliases.

Для каждого ``from X import Y, Z, W`` в __init__.py файле добавляет
``as Y, as Z, as W`` alias — это explicit re-export pattern, который
ruff F401 признает (silent-imports).

Pattern:
    # Before (ruff F401):
    from src.backend.core.di.providers import ai, auth, cache

    # After (ruff passes):
    from src.backend.core.di.providers import (
        ai as ai,
        auth as auth,
        cache as cache,
    )

Usage:
    python tools/add_f401_reexport_aliases.py [--root src/backend]
"""

from __future__ import annotations

import argparse
import ast
import logging
from pathlib import Path

_logger = logging.getLogger(__name__)


def _has_explicit_alias(line: str) -> bool:
    """True если ``import X as Y`` уже присутствует (idempotent guard)."""
    return " as " in line


def _add_alias_to_line(line: str) -> str | None:
    """Добавить ``as X`` alias к каждому imported name. Return None если уже есть."""
    if _has_explicit_alias(line):
        return None

    stripped = line.rstrip("\n")
    if not stripped.startswith("from ") or " import " not in stripped:
        return None

    # ``from X import Y, Z`` → ``X`` (module path) и ``Y, Z`` (names)
    # После split: prefix_part = "from X" (с indent prefix), after = "Y, Z"
    prefix_part, after = stripped.split(" import ", 1)
    # prefix_part = "from X" (с indent prefix)
    indent = len(prefix_part) - len(prefix_part.lstrip())
    indent_prefix = prefix_part[:indent]
    # Strip ``from `` prefix to get bare module path
    raw_module = prefix_part[len(indent_prefix):]  # "from X"
    if raw_module.startswith("from "):
        module_path = raw_module[5:]  # "X"
    else:
        module_path = raw_module.lstrip()

    # Parse names from ``from X import Y, Z``
    # Handle multi-line parenthesized: ``from X import (Y, Z)``
    if after.strip().startswith("("):
        # Multi-line parenthesized — не обрабатываем (edge case)
        return None

    names = [n.strip() for n in after.split(",") if n.strip()]
    if not names or names == ["*"]:
        return None

    suffix = "\n" if line.endswith("\n") else ""

    # Build new line(s)
    if len(names) == 1:
        return f"{indent_prefix}from {module_path} import {names[0]} as {names[0]}{suffix}"

    # Multi-name → multi-line parenthesized form
    aliases = ",\n    ".join(f"{n} as {n}" for n in names)
    return f"{indent_prefix}from {module_path} import (\n    {aliases},\n){suffix}"


def _process_file(path: Path) -> tuple[int, str]:
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return 0, content
    new_lines: list[str] = []
    changes = 0
    for line in content.splitlines(keepends=True):
        new_line = _add_alias_to_line(line)
        if new_line is not None:
            new_lines.append(new_line)
            changes += 1
        else:
            new_lines.append(line)
    if changes == 0:
        return 0, content
    return changes, "".join(new_lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="add_f401_reexport_aliases",
        description="Silence F401 in __init__.py via explicit aliases (D-AUDIT-3022 cycle-48)",
    )
    parser.add_argument("--root", default="src/backend", help="Root dir to walk")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    root = Path(args.root)
    files = list(root.rglob("__init__.py"))
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
