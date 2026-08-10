#!/usr/bin/env python3
"""Cycle-47 (D-AUDIT-3020): silence F401 for optional-import probes.

Walks src/backend/ и для каждого `import X` внутри ``try: ... except ImportError:``
блока добавляет ``# noqa: F401 — availability probe`` (если ещё нет).

Pattern:
    try:
        import optional_module
    except ImportError:
        ...

→

    try:
        import optional_module  # noqa: F401 — availability probe
    except ImportError:
        ...

Безопасный (idempotent): если ``# noqa: F401`` уже есть, не трогает.

Usage:
    python tools/add_f401_noqa.py [--root src/backend]
"""

from __future__ import annotations

import argparse
import ast
import logging
from pathlib import Path

_logger = logging.getLogger(__name__)

_NOQA_COMMENT = "# noqa: F401 — availability probe"


def _has_noqa_import(line: str, mod_name: str) -> bool:
    """Проверить, есть ли уже ``# noqa: F401`` на строке import ``mod_name``."""
    if "# noqa" not in line:
        return False
    return f"import {mod_name}" in line or f"import {mod_name}\n" in line


def _try_block_has_f401_already(try_block_text: str, mod_name: str) -> bool:
    """Проверить, есть ли ``# noqa: F401`` на любой строке импорта ``mod_name``."""
    return any(_has_noqa_import(line, mod_name) for line in try_block_text.splitlines())


def _process_file(path: Path) -> tuple[int, str]:
    """Обработать один файл. Returns (changes_made, new_content)."""
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return 0, content
    new_lines: list[str] = []
    i = 0
    changes = 0
    in_try_except_import_error = False
    while i < len(content):
        line = content[i]
        if line.startswith("try:"):
            in_try_except_import_error = False
            new_lines.append(line)
            i += 1
            continue
        if in_try_except_import_error:
            if line.startswith("import ") and " " not in line.split("import ", 1)[1].split(" ")[0].split(" as ")[0].split("\n")[0]:
                # multi-line ``from X import (\n    a,\n    b,\n)``
                pass
            import_node = _parse_import_line(line)
            if import_node is not None and _is_probed_import(path, i, content):
                mod_name = import_node
                if not _has_noqa_import(line, mod_name):
                    stripped = line.rstrip("\n")
                    if not stripped.endswith("# noqa: F401"):
                        new_line = stripped.rstrip() + f"  {_NOQA_COMMENT}\n"
                        new_lines.append(new_line)
                        changes += 1
                        i += 1
                        continue
            new_lines.append(line)
            i += 1
            continue
        new_lines.append(line)
        i += 1
    if changes == 0:
        return 0, content
    return changes, "".join(new_lines)


def _parse_import_line(line: str) -> str | None:
    """Parse ``import X`` или ``from X import Y`` → возвращает root module name."""
    stripped = line.strip()
    if stripped.startswith("import "):
        rest = stripped[7:].split(" as ")[0].strip()
        return rest.split(".")[0].split(" ")[0]
    if stripped.startswith("from "):
        rest = stripped[5:].split(" import ")[0].strip()
        return rest.split(".")[0]
    return None


def _is_probed_import(path: Path, line_idx: int, content: str) -> bool:
    """Проверить, что import внутри ``try: ... except ImportError:`` блока.

    Walk forward от ``try:`` до matching ``except ImportError:``.
    Return True если import line находится между ними (по indentation).
    """
    lines = content.splitlines(keepends=True)
    line_indent = len(lines[line_idx]) - len(lines[line_idx].lstrip())
    # Walk backward for ``try:`` at smaller indent than the import.
    try_line_idx = None
    for j in range(line_idx - 1, -1, -1):
        if not lines[j].strip():
            continue
        cur_indent = len(lines[j]) - len(lines[j].lstrip())
        if cur_indent < line_indent and lines[j].lstrip().startswith("try:"):
            try_line_idx = j
            break
        if cur_indent < line_indent and (
            lines[j].lstrip().startswith("def ") or
            lines[j].lstrip().startswith("class ")
        ):
            return False
    if try_line_idx is None:
        return False
    # Walk forward from try_line_idx+1 looking for matching except ImportError.
    try_indent = len(lines[try_line_idx]) - len(lines[try_line_idx].lstrip())
    for k in range(try_line_idx + 1, len(lines)):
        if not lines[k].strip():
            continue
        cur_indent = len(lines[k]) - len(lines[k].lstrip())
        # Block exits when we hit a sibling-level (indent <= try_indent) statement
        # that isn't the matching except.
        if cur_indent == try_indent:
            stripped = lines[k].lstrip()
            if stripped.startswith("except ") and "ImportError" in stripped:
                return True
            # Sibling statement (def/class/etc.) — block exited.
            return False
        if cur_indent < try_indent:
            return False
    return False


def _process_file(path: Path) -> tuple[int, str]:
    """Обработать один файл. Returns (changes_made, new_content)."""
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return 0, content

    # Parse AST для обнаружения __all__ declaration.
    all_names = _parse_all_names(content)

    new_lines = list(content.splitlines(keepends=True))
    changes = 0
    i = 0
    while i < len(new_lines):
        line = new_lines[i]
        import_node = _parse_import_line(line)
        if import_node is None:
            i += 1
            continue

        # Skip if already silenced.
        if "# noqa" in line and "F401" in line:
            i += 1
            continue

        should_silence = False
        reason = ""
        # 1) Optional-import probe (try: import X / except ImportError:)
        if _is_probed_import(path, i, content):
            should_silence = True
            reason = "availability probe"
        # 2) Re-export in __init__.py — module name in __all__
        elif _is_reexport(path, line, all_names, import_node):
            should_silence = True
            reason = "re-export"

        if should_silence:
            stripped = line.rstrip("\n").rstrip()
            comment = f"  # noqa: F401 — {reason}"
            new_line = stripped + comment + "\n"
            new_lines[i] = new_line
            changes += 1
        i += 1
    if changes == 0:
        return 0, content
    return changes, "".join(new_lines)


def _parse_all_names(content: str) -> set[str]:
    """Parse ``__all__`` declaration (если есть) → set of names."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return set()
    all_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                all_names.add(elt.value)
    return all_names


def _is_reexport(
    path: Path,
    line: str,
    all_names: set[str],
    import_root: str,
) -> bool:
    """Проверить, что import — re-export (например в __init__.py для public API).

    Re-export pattern:
        __all__ = ("Foo", "bar", ...)  # names list
        from src.backend.module.submodule import Foo, bar  # re-export

    Условия:
    1) Файл — ``__init__.py``
    2) ``__all__`` declared
    3) Import — это ``from X import Y[, Z, ...]``
    4) X не относится к optional-import probes (это уже обработано выше)
    5) Import — top-level (без вложенности в def/class)
    """
    if path.name != "__init__.py":
        return False
    if not all_names:
        return False
    stripped = line.strip()
    if not stripped.startswith("from ") or " import " not in stripped:
        return False
    # Extract imported names from "from X import Y, Z"
    _, after = stripped.split(" import ", 1)
    after = after.split(" as ")[0]  # ignore ``as``
    names = [n.strip() for n in after.split(",") if n.strip()]
    if not names:
        return False
    # Re-export если хотя бы один imported name есть в __all__
    return any(name in all_names for name in names)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="add_f401_noqa",
        description="Silence F401 for optional-import probes + re-exports (D-AUDIT-3020 cycle-47)",
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
