#!/usr/bin/env python3
"""Migrate getattr(feature_flags, 'xxx', ...) callsites."""
from __future__ import annotations

import re
import sys
from pathlib import Path

DIRS = [
    Path("src/backend/services"),
    Path("src/backend/dsl"),
    Path("src/backend/infrastructure"),
    Path("extensions"),
]

EXCLUDE_DIRS = {
    Path("src/backend/core"),
    Path("src/backend/entrypoints"),
}

NON_BOOLEAN_FLAGS = {"embedding_v2_traffic", "scheduler_backend"}

GETATTR_RE = re.compile(
    r'getattr\s*\(\s*feature_flags\s*,\s*["\'](\w+)["\']\s*(?:,\s*[^)]+)?\s*\)'
)

HAS_SERVICE_IMPORT_RE = re.compile(
    r"from\s+src\.backend\.core\.feature_flags\s+import\s+.*get_feature_flag_service"
)

FEATURE_FLAGS_IMPORT_RE = re.compile(
    r"^(?P<indent>\s*)from\s+(?P<module>[\w.]+)\s+import\s+(?P<names>.*)\bfeature_flags\b(?P<trail>.*)$"
)


def collect_files() -> list[Path]:
    files: list[Path] = []
    for d in DIRS:
        if not d.exists():
            continue
        for p in d.rglob("*.py"):
            try:
                rel = p.relative_to(Path("."))
            except ValueError:
                rel = p
            if any(str(rel).startswith(str(ex)) for ex in EXCLUDE_DIRS):
                continue
            files.append(p)
    return files


def process_file(path: Path) -> tuple[bool, int]:
    original = path.read_text(encoding="utf-8")
    text = original
    migrated = 0

    def replacer(m: re.Match) -> str:
        flag_name = m.group(1)
        if flag_name in NON_BOOLEAN_FLAGS:
            return m.group(0)
        nonlocal migrated
        migrated += 1
        return f'get_feature_flag_service().is_enabled("{flag_name}")'

    text = GETATTR_RE.sub(replacer, text)

    if migrated == 0:
        return False, 0

    # Add import if missing
    if not HAS_SERVICE_IMPORT_RE.search(text):
        lines = text.splitlines(keepends=True)
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.strip().startswith("from __future__") or line.strip().startswith("#!") or line.strip().startswith("# -*-"):
                insert_idx = i + 1
        lines.insert(insert_idx, "from src.backend.core.feature_flags import get_feature_flag_service\n")
        text = "".join(lines)

    # Remove unused feature_flags import if no raw feature_flags references remain
    # (excluding disabled_feature_flags etc. by checking for \bfeature_flags\b not preceded by disabled_/enabled_)
    # Simple check: if there is no "feature_flags" substring at all except in comments/strings? Hard.
    # Instead, check if any \bfeature_flags\b remains that is NOT part of disabled_feature_flags/enabled_feature_flags.
    remaining = re.findall(r'\bfeature_flags\b', text)
    # But docstrings/comments may still contain it. We only care about code imports.
    # If there are zero Attribute/getattr usages left, we can try to remove the import.
    # Check for Attribute or getattr or Name usage in a simplistic way:
    has_code_usage = bool(re.search(r'\bfeature_flags\.[a-zA-Z_]', text)) or bool(re.search(r'getattr\s*\(\s*feature_flags', text))
    if not has_code_usage:
        lines = text.splitlines(keepends=True)
        new_lines = []
        for line in lines:
            m = FEATURE_FLAGS_IMPORT_RE.match(line)
            if m:
                indent = m.group("indent")
                module = m.group("module")
                names = m.group("names")
                trail = m.group("trail")
                before = names.rstrip(" ").rstrip(",")
                after = trail.lstrip(" ").lstrip(",")
                parts = [p.strip() for p in (before + "," + after).split(",") if p.strip() and p.strip() != "feature_flags"]
                if parts:
                    new_line = f"{indent}from {module} import {', '.join(parts)}\n"
                    new_lines.append(new_line)
                else:
                    pass
            else:
                new_lines.append(line)
        text = "".join(new_lines)

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True, migrated
    return False, migrated


def main() -> int:
    files = collect_files()
    changed = 0
    total = 0
    for f in files:
        mod, calls = process_file(f)
        if mod:
            changed += 1
            total += calls
            print(f"  Migrated {calls} callsite(s) in {f}")
    print(f"\nDone: {changed} files changed, {total} callsites migrated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
