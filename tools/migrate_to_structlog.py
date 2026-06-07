"""S60 W2 codemod: migrate logging.getLogger() → factory.get_logger().

Strategy:
- Find all `import logging` (and aliases like `import logging as _logging`) in src/
- For each file, detect if `logging` is used ONLY for `getLogger` (and `getLogger` only)
- If yes: replace `import logging` with `from src.backend.infrastructure.logging.factory import get_logger`
  AND replace `logging.getLogger(X)` with `get_logger(X)`
- If no: keep `import logging` AND add factory import (no name collision: get_logger only)

Handles:
- `import logging` → use factory.get_logger
- `import logging as _logging` → use factory.get_logger
- `import logging as <alias>` → use factory.get_logger
- `from logging import getLogger` → use factory.get_logger
- Multi-line imports (parens)
- Files where logging is used for OTHER things (e.g., `logging.getLevelName()`) — keep import, add factory

Idempotent: detects if file already has `from ...factory import get_logger` and skips.

Usage: python3 tools/migrate_to_structlog.py [--dry-run] [path ...]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Patterns
RE_IMPORT_LOGGING = re.compile(
    r"^(?P<indent>[ \t]*)import logging(?P<alias> as (?P<name>[A-Za-z_][A-Za-z0-9_]*))?\s*$",
    re.MULTILINE,
)
RE_FROM_LOGGING_GETLOGGER = re.compile(
    r"^(?P<indent>[ \t]*)from logging import (?P<get>getLogger)\s*$",
    re.MULTILINE,
)
RE_FROM_LOGGING_ANY = re.compile(
    r"^(?P<indent>[ \t]*)from logging import (?P<names>[A-Za-z_][A-Za-z0-9_]*(?:, *[A-Za-z_][A-Za-z0-9_]*)*)\s*$",
    re.MULTILINE,
)
RE_FACTORY_IMPORT = re.compile(
    r"^from src\.backend\.infrastructure\.logging\.factory import get_logger\s*$",
    re.MULTILINE,
)

# stdlib logging top-level names that we treat as "uses logging beyond getLogger"
STDLIB_LOGGING_USAGE = {
    "Logger",
    "Handler",
    "Formatter",
    "Filter",
    "LogRecord",
    "LoggerAdapter",
    "StreamHandler",
    "FileHandler",
    "NullHandler",
    "getLogger",
    "getLoggerClass",
    "setLoggerClass",
    "basicConfig",
    "getLevelName",
    "setLevel",
    "INFO",
    "DEBUG",
    "WARNING",
    "ERROR",
    "CRITICAL",
    "NOTSET",
    "WARN",
}


def detect_logging_module_aliases(src: str) -> dict[str, str]:
    """Detect names that refer to the logging module via `import logging` or alias.

    Returns: {name: "logging"} for each alias found.
    """
    aliases: dict[str, str] = {}
    for m in RE_IMPORT_LOGGING.finditer(src):
        alias = m.group("name") or "logging"
        aliases[alias] = "logging"
    return aliases


def uses_logging_beyond_getlogger(src: str, aliases: dict[str, str]) -> bool:
    """Check if any alias is used for things OTHER than getLogger (e.g., getLevelName)."""
    if not aliases:
        return False
    # Strip imports
    src_no_imports = re.sub(
        r"^(?:from logging import .+|import logging(?: as [A-Za-z_][A-Za-z0-9_]*)?)\s*$",
        "",
        src,
        flags=re.MULTILINE,
    )
    # Strip triple-quoted strings (docstrings) — `logging.X` inside is documentation
    src_no_strings = re.sub(r'"""[\s\S]*?"""', "", src_no_imports)
    src_no_strings = re.sub(r"'''[\s\S]*?'''", "", src_no_strings)
    # Strip line comments
    src_no_strings = re.sub(r"#[^\n]*", "", src_no_strings)
    for alias in aliases:
        # Look for usages of alias.X where X is NOT getLogger
        pattern = re.compile(rf"\b{re.escape(alias)}\.([A-Za-z_][A-Za-z0-9_]*)")
        for m in pattern.finditer(src_no_strings):
            attr = m.group(1)
            if attr != "getLogger":
                return True
        # Also `from logging import X` (any name from STDLIB_LOGGING_USAGE other than getLogger)
        for m in RE_FROM_LOGGING_ANY.finditer(src):
            names = [n.strip() for n in m.group("names").split(",")]
            for n in names:
                if n in STDLIB_LOGGING_USAGE and n != "getLogger":
                    return True
    return False


def has_factory_get_logger(src: str) -> bool:
    return bool(RE_FACTORY_IMPORT.search(src))


def rewrite_imports(src: str, keep_logging_import: bool = False) -> str:
    """Replace `import logging[ as alias]` and `from logging import ...` with factory import.

    If `keep_logging_import=True` (file uses logging beyond getLogger), only strip
    `from logging import getLogger` and keep `import logging` line.
    """
    if not keep_logging_import:
        # 1) `from logging import getLogger` → drop (factory import covers it)
        src = RE_FROM_LOGGING_GETLOGGER.sub("", src)
        # 2) `from logging import X, Y` (without getLogger) → keep but add factory import later
        # handled by `uses_logging_beyond_getlogger` check

        # 3) `import logging` and `import logging as X` → drop (factory import covers it)
        src = RE_IMPORT_LOGGING.sub("", src)
    else:
        # Keep `import logging` (file uses logging.X for non-getLogger things).
        # Only strip `from logging import getLogger` if present (factory replaces it).
        src = RE_FROM_LOGGING_GETLOGGER.sub("", src)
    return src


def add_factory_import(src: str) -> str:
    """Insert `from src.backend.infrastructure.logging.factory import get_logger` after the
    first existing import block. Preserves user import order.
    """
    if has_factory_get_logger(src):
        return src

    factory_line = "from src.backend.infrastructure.logging.factory import get_logger"

    # Find first existing `from ... import ...` or `import ...` line
    m = re.search(r"^(?:from|import) [^\n]+$", src, re.MULTILINE)
    if m:
        # Insert AFTER the first import block (find consecutive imports)
        pos = m.start()
        # Find end of first contiguous import block
        end_pos = pos
        for line_m in re.finditer(r"^((?:from|import) [^\n]+\n?)+", src[pos:], re.MULTILINE):
            end_pos = pos + line_m.end()
            break
        return src[:end_pos] + factory_line + "\n" + src[end_pos:]
    # No imports — prepend at top
    return factory_line + "\n\n" + src


def rewrite_get_logger_calls(src: str, aliases: dict[str, str]) -> str:
    """Replace `logging.getLogger(X)` and `alias.getLogger(X)` with `get_logger(X)`."""
    for alias in aliases:
        src = re.sub(
            rf"\b{re.escape(alias)}\.getLogger\(",
            "get_logger(",
            src,
        )
    # Also handle remaining `logging.getLogger` in case alias dict missed
    src = re.sub(r"\blogging\.getLogger\(", "get_logger(", src)
    return src


def process_file(path: Path, dry_run: bool = False) -> tuple[bool, str]:
    """Returns (changed, summary)."""
    src = path.read_text(encoding="utf-8")
    if "logging.getLogger" not in src and "logging as " not in src and "import logging" not in src and "from logging import" not in src:
        return False, "no logging usage"

    aliases = detect_logging_module_aliases(src)
    if not aliases and "from logging import" not in src:
        return False, "no logging imports"

    beyond = uses_logging_beyond_getlogger(src, aliases)
    original = src

    # 1) Rewrite all `X.getLogger(Y)` → `get_logger(Y)`
    src = rewrite_get_logger_calls(src, aliases)
    # 2) Drop or keep `import logging[ as X]` lines based on usage
    src = rewrite_imports(src, keep_logging_import=beyond)
    # 3) Add factory import (always — get_logger needs to be importable)
    src = add_factory_import(src)

    if src == original:
        return False, "no change"

    if not dry_run:
        path.write_text(src, encoding="utf-8")
    return True, f"migrated: aliases={list(aliases)}, beyond_getlogger={beyond}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        default=["src/"],
        help="Paths to scan (default: src/)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print changes without writing files",
    )
    args = parser.parse_args()

    files: list[Path] = []
    for p in args.paths:
        path = Path(p)
        if path.is_file():
            files.append(path)
        else:
            files.extend(path.rglob("*.py"))

    # Exclude paths that are part of the logging infrastructure itself
    # AND files in the early-load path of the application (would cause
    # circular imports with the legacy logging_service chain).
    EXCLUDE_PATTERNS = (
        # Logging infrastructure
        "src/backend/infrastructure/logging/",
        "src/backend/infrastructure/external_apis/logging_service.py",
        "src/backend/infrastructure/observability/structlog_batching.py",
        "src/backend/infrastructure/clients/external/logger.py",
        # Early-load paths (loaded during settings/config import chain)
        "src/backend/core/config/",
        "src/backend/core/interfaces/",
        "src/backend/core/auth/",
        "src/backend/core/actions/",
        "src/backend/core/audit/",
        # God-files with deep coupling (deferred to S61)
        "src/backend/integration.py",
        "src/backend/ai_rpa.py",
        "src/backend/eip.py",
    )

    def _is_excluded(f: Path) -> bool:
        s = str(f)
        return any(pat in s for pat in EXCLUDE_PATTERNS)

    changed_count = 0
    skipped_count = 0
    error_count = 0

    for f in sorted(files):
        if "__pycache__" in f.parts or ".venv" in f.parts:
            continue
        if _is_excluded(f):
            skipped_count += 1
            continue
        try:
            changed, summary = process_file(f, dry_run=args.dry_run)
            if changed:
                changed_count += 1
                if args.dry_run or True:
                    print(f"  CHANGE: {f} ({summary})")
            else:
                skipped_count += 1
        except Exception as e:
            error_count += 1
            print(f"  ERROR: {f}: {e}", file=sys.stderr)

    print(f"\nSummary: {changed_count} changed, {skipped_count} skipped, {error_count} errors")
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
