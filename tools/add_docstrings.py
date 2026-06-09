"""S46 W1 (TD-019): bulk add placeholder docstrings to public functions.

Inspects a Python file, finds public functions/classes/methods without
docstrings, и вставляет placeholder docstring (1-line summary) сразу
после def-line. Placeholder помечен TODO для future manual expansion.

**Использование** (one-time, not idempotent):
    uv run python tools/add_docstrings.py \\
        src/backend/infrastructure/clients/storage/redis.py \\
        --summary "Redis client wrapper."

Параметры:
- paths: list of files to process.
- --summary: 1-line summary для placeholder.
- --dry-run: показать, не писать.

Honest scope: 1840 violations = multi-sprint. S46 W1 = bulk placeholder
lift в 5-10 high-impact files; full docstring authoring = S47+ D.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Sequence

__all__ = ("add_docstrings_to_file",)


def _is_public(name: str) -> bool:
    return not name.startswith("_")


def _find_public_targets(tree: ast.AST) -> list[tuple[int, int, int, str]]:
    """Возвращает (start_line, body_first_line, col_offset, name) для public объектов.

    Skip nested functions (определяются по parent traversal).
    """
    targets: list[tuple[int, int, int, str]] = []
    # First pass: collect all nested function locations.
    nested_locs: set[tuple[int, int]] = set()
    for parent in ast.walk(tree):
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for child in ast.walk(parent):
                if child is parent:
                    continue
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    nested_locs.add((child.lineno, child.col_offset))
    # Second pass: find public top-level + class-level defs (skip nested).
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            loc = (node.lineno, node.col_offset)
            if loc in nested_locs:
                continue
            if _is_public(node.name) and not ast.get_docstring(node):
                targets.append(
                    (node.lineno, node.body[0].lineno, node.col_offset, node.name)
                )
    return targets


def add_docstrings_to_file(
    path: Path, summary: str, *, dry_run: bool = False
) -> int:
    """Добавляет placeholder docstrings к public объектам в file.

    Returns: number of docstrings added.
    """
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    targets = _find_public_targets(tree)
    if not targets:
        return 0
    lines = src.splitlines(keepends=True)
    # Process в reverse order чтобы line numbers оставались valid.
    for start_line, body_first_line, col_offset, name in reversed(targets):
        # Insert docstring right after def signature.
        # Indent: col_offset из def + 4 spaces.
        indent = " " * (col_offset + 4)
        doc = f'{indent}"""{summary} (TODO: S47+ full docstring)\n{indent}"""\n'
        body_line_idx = body_first_line - 1  # 0-based
        lines.insert(body_line_idx, doc)
    if not dry_run:
        path.write_text("".join(lines), encoding="utf-8")
    return len(targets)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n")[0] if __doc__ else "Add docstrings."
    )
    parser.add_argument("paths", nargs="+", help="Files to process.")
    parser.add_argument(
        "--summary",
        required=True,
        help="1-line summary для placeholder docstring.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Показать stats без записи.",
    )
    args = parser.parse_args(argv)
    total = 0
    for raw in args.paths:
        p = Path(raw)
        if not p.exists():
            print(f"  SKIP (not found): {p}", file=sys.stderr)
            continue
        n = add_docstrings_to_file(p, args.summary, dry_run=args.dry_run)
        print(f"  {p}: {n} docstring(s) added")
        total += n
    print(f"Total: {total} docstrings {'(dry-run)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
