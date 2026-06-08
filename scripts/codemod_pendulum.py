#!/usr/bin/env python3
"""Codemod: stdlib datetime → pendulum (S61 W3 full migration).

Strategy: pendulum.DateTime IS datetime.datetime (subclass), поэтому
``from pendulum import DateTime as datetime`` — drop-in replacement.
Все существующие вызовы ``datetime.now()`` / ``datetime.now(UTC)`` /
``datetime.fromisoformat()`` / ``datetime.fromtimestamp()`` продолжают
работать unchanged (методы экземпляра наследуются).

ВАЖНО: ``pendulum.datetime`` — это FACTORY FUNCTION, не класс.
Поэтому НЕЛЬЗЯ просто ``from pendulum import datetime`` — сломает
весь код. Правильный drop-in — ``from pendulum import DateTime as datetime``.

Замены:
- ``from datetime import X, datetime, Y`` →
  ``from datetime import X, Y``
  + ``from pendulum import DateTime as datetime``
- ``datetime.utcnow()`` → ``datetime.now(UTC)`` (deprecation fix)

ИСКЛЮЧЕНО из миграции (оставлены на stdlib):
- ``tests/`` (тесты должны тестировать поведение, не зависеть от pendulum)
- ``conftest.py``, ``__init__.py`` (структурные файлы)
- ``src/backend/infrastructure/scheduler/cron_validator.py`` (уже pendulum)
- ``src/backend/core/util/datetime_utils.py`` (shim, нужен dual-import)
- ``from datetime import timedelta`` alone (timedelta в pendulum — другой)
- ``from datetime import date`` alone (date в pendulum — другой)
- ``from datetime import timezone`` alone (timezone UTC эквивалент)

Запуск:
    python scripts/codemod_pendulum.py [--dry-run] [--verbose]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src" / "backend"

# Skip patterns (path substrings)
SKIP_PATH_SUBSTRINGS = (
    "/tests/",  # test files use stdlib
    "/__pycache__/",
    "/.venv/",
    "datetime_utils.py",  # shim, needs dual-import
    "cron_validator.py",  # already pendulum
)

# Names from datetime that should NEVER be replaced (timedelta has different
# semantics in pendulum; date is also class but used in some legacy code)
NEVER_REPLACE = frozenset({"timedelta", "date", "time", "timezone", "tzinfo"})

# Match `from datetime import X, Y, Z`
RE_FROM_DATETIME = re.compile(
    r"^(\s*)from\s+datetime\s+import\s+(\([^)]+\)|[^\n#]+)",
    re.MULTILINE,
)


def split_imports(import_part: str) -> tuple[list[str], bool]:
    """Split parenthesised/commasep import list into (stdlib, has-datetime).

    Returns:
        (keep_in_stdlib, has_datetime) — keep list + flag whether datetime present.
    """
    s = import_part.strip()
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]
    names = [n.strip() for n in s.split(",") if n.strip()]
    keep: list[str] = []
    has_datetime = False
    for name in names:
        if name in NEVER_REPLACE:
            keep.append(name)
        elif name == "datetime":
            has_datetime = True
        else:
            keep.append(name)
    return keep, has_datetime


def transform_file(path: Path, dry_run: bool, verbose: bool) -> tuple[bool, int]:
    """Transform one file. Returns (changed, num_imports_migrated)."""
    try:
        original = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return False, 0

    new_lines: list[str] = []
    last_idx = 0
    changed = False
    migrated = 0

    matches = list(RE_FROM_DATETIME.finditer(original))
    if not matches:
        return False, 0

    for m in matches:
        indent = m.group(1)
        import_part = m.group(2)
        keep, has_datetime = split_imports(import_part)

        if not has_datetime:
            continue

        # Build replacement: split stdlib + pendulum
        if keep:
            stdlib_line = f"{indent}from datetime import {', '.join(sorted(keep))}"
            pendulum_line = f"{indent}from pendulum import DateTime as datetime"
            replacement = stdlib_line + "\n" + pendulum_line
        else:
            replacement = f"{indent}from pendulum import DateTime as datetime"

        new_lines.append(original[last_idx:m.start()])
        new_lines.append(replacement)
        last_idx = m.end()
        changed = True
        migrated += 1

    if not changed:
        return False, 0

    new_lines.append(original[last_idx:])
    new_text = "".join(new_lines)

    # Also fix datetime.utcnow() calls
    new_text = new_text.replace("datetime.utcnow()", "datetime.now(UTC)")

    if not dry_run:
        path.write_text(new_text, encoding="utf-8")
        if verbose:
            print(f"  CHANGED {path.relative_to(REPO_ROOT)}: {migrated} import(s)")
    else:
        if verbose:
            print(f"  DRY-RUN {path.relative_to(REPO_ROOT)}: {migrated} import(s)")

    return True, migrated


def should_skip(path: Path) -> bool:
    s = str(path)
    return any(sub in s for sub in SKIP_PATH_SUBSTRINGS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Pendulum codemod")
    parser.add_argument("--dry-run", action="store_true", help="don't write")
    parser.add_argument("--verbose", action="store_true", help="show changed files")
    args = parser.parse_args()

    files = list(SRC_DIR.rglob("*.py"))
    skipped = 0
    changed_count = 0
    total_imports = 0

    for path in files:
        if should_skip(path):
            skipped += 1
            continue
        changed, n = transform_file(path, args.dry_run, args.verbose)
        if changed:
            changed_count += 1
            total_imports += n

    print(
        f"{'[DRY-RUN] ' if args.dry_run else ''}"
        f"Changed {changed_count} files ({total_imports} imports), "
        f"skipped {skipped}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

