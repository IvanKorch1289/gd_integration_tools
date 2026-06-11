#!/usr/bin/env python3
"""TD-018 part 2: migrate feature_flags.xxx callsites in target dirs."""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Directories to process
DIRS = [
    Path("src/backend/services"),
    Path("src/backend/dsl"),
    Path("src/backend/infrastructure"),
    Path("extensions"),
]

# Do not touch these subdirs
EXCLUDE_DIRS = {
    Path("src/backend/core"),
    Path("src/backend/entrypoints"),
}

# Known non-boolean flags that must NOT be migrated to is_enabled()
NON_BOOLEAN_FLAGS = {
    "embedding_v2_traffic",
    "scheduler_backend",
}

# Regex for a feature_flags attribute access with word boundary
FLAG_RE = re.compile(r"\bfeature_flags\.(\w+)")

# Regex to detect existing import of get_feature_flag_service
HAS_SERVICE_IMPORT_RE = re.compile(
    r"from\s+src\.backend\.core\.feature_flags\s+import\s+.*get_feature_flag_service"
)

# Regex for import line that imports feature_flags
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
    """Returns (modified, number_of_callsites_migrated)."""
    original = path.read_text(encoding="utf-8")
    text = original
    migrated = 0

    # Find all flag names used
    flag_names = set(FLAG_RE.findall(text))
    if not flag_names:
        return False, 0

    # Determine which flags to migrate (boolean ones)
    boolean_flags = flag_names - NON_BOOLEAN_FLAGS
    if not boolean_flags:
        return False, 0

    # Replace each boolean flag access
    def replacer(m: re.Match) -> str:
        flag_name = m.group(1)
        if flag_name in NON_BOOLEAN_FLAGS:
            return m.group(0)  # keep original
        nonlocal migrated
        migrated += 1
        return f'get_feature_flag_service().is_enabled("{flag_name}")'

    text = FLAG_RE.sub(replacer, text)

    if migrated == 0:
        return False, 0

    # Add import for get_feature_flag_service if not present
    if not HAS_SERVICE_IMPORT_RE.search(text):
        lines = text.splitlines(keepends=True)
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.strip().startswith("from __future__") or line.strip().startswith("#!") or line.strip().startswith("# -*-"):
                insert_idx = i + 1
        import_line = "from src.backend.core.feature_flags import get_feature_flag_service\n"
        lines.insert(insert_idx, import_line)
        text = "".join(lines)

    # Remove feature_flags from import lines if feature_flags no longer used
    if "\bfeature_flags." not in text:
        # But simple "feature_flags." in text check is enough for code,
        # though we used word boundary above. Let's just check raw substring.
        pass

    # Re-check whether any `feature_flags.` remains (excluding disabled_feature_flags etc.)
    remaining = FLAG_RE.findall(text)
    remaining_bool = [f for f in remaining if f not in NON_BOOLEAN_FLAGS]
    if not remaining and "feature_flags." not in text:
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
                    pass  # remove entire line
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
    total_callsites = 0
    for f in files:
        mod, calls = process_file(f)
        if mod:
            changed += 1
            total_callsites += calls
            print(f"  Migrated {calls} callsite(s) in {f}")
    print(f"\nDone: {changed} files changed, {total_callsites} callsites migrated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
