"""CI-runnable audit: detect new ``stdlib logging`` uses в src/backend (S100 W4).

Background (S93-S100 ratchet):
    22 files были мигрированы с stdlib ``logging`` → ``src.backend.core.logging``
    (facade поверх structlog). 7 файлов legitimately остаются на stdlib
    (type annotation, stdlib Handler class, tenacity DEBUG constant,
    typer basicConfig, etc.) — locked в ``test_legitimate_stdlib_logging.py``.

Что делает этот скрипт:
    1. Scan all ``src/backend/**/*.py`` (excluding ``infrastructure/logging/``,
       который IS the stdlib backend).
    2. Detect ``import logging`` / ``from logging import ...`` patterns.
    3. Cross-check с :class:`LEGITIMATE_STDLIB_FILES` (hardcoded в test).
    4. Exit 0 если OK, exit 1 если есть NEW files (regression).

Использование::
    python tools/audit_stdlib_logging.py          # human-readable report
    python tools/audit_stdlib_logging.py --ci     # CI mode (exit 1 on new)

Используется в pre-push gate (per ``S100 W4 plan``) — блокирует случайный
import stdlib logging в новых файлах.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Must match ``tests/unit/core/test_legitimate_stdlib_logging.py``.
LEGITIMATE_STDLIB_FILES: frozenset[str] = frozenset(
    {
        "src/backend/dsl/engine/context.py",  # logging.Logger type annotation
        "src/backend/infrastructure/clients/external/logger.py",  # logging.Handler base class
        "src/backend/infrastructure/clients/transport/http/request_mixin.py",  # from logging import DEBUG
        "src/backend/infrastructure/clients/transport/http_httpx.py",  # logging.DEBUG tenacity
        "src/backend/infrastructure/execution/dask_backend.py",  # logging.WARNING (silence)
        "src/backend/infrastructure/external_apis/logging_service.py",  # DEPRECATED
        "src/backend/infrastructure/observability/structlog_batching.py",  # intentional fallback
        "src/backend/workflows/worker.py",  # logging.basicConfig typer CLI
    }
)

# Infrastructure/logging/ IS the stdlib backend, skip.
SKIP_DIRS: tuple[str, ...] = (
    "infrastructure/logging",  # the stdlib backend itself
    "__pycache__",
    ".venv",
    "venv",
)

# Patterns that count as "stdlib logging use".
STDLIB_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*import logging\s*$", re.MULTILINE),
    re.compile(r"^\s*from logging import\s+", re.MULTILINE),
)


def _iter_py_files(root: Path) -> list[Path]:
    """Yield all .py under root except __pycache__ and SKIP_DIRS.

    Note: ``infrastructure/logging`` is COMPOSITE dir (two path parts), so we
    use string-prefix matching instead of part-set intersection.
    """
    out: list[Path] = []
    for p in root.rglob("*.py"):
        rel = str(p.relative_to(root))
        if any(f"{d}/" in rel or rel.endswith(f"/{d}") for d in SKIP_DIRS):
            continue
        out.append(p)
    return out


def audit(root: Path = Path(".")) -> list[Path]:
    """Return list of files using stdlib logging AND not in legitimate list."""
    violations: list[Path] = []
    for p in _iter_py_files(root / "src" / "backend"):
        rel = str(p.relative_to(root))
        if rel in LEGITIMATE_STDLIB_FILES:
            continue
        try:
            src = p.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        if any(pat.search(src) for pat in STDLIB_PATTERNS):
            violations.append(p)
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit stdlib logging uses в src/backend (S100 W4)"
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI mode: exit 1 если найдены NEW uses (regression)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Project root (default: current dir)",
    )
    args = parser.parse_args(argv)

    legit = sorted(LEGITIMATE_STDLIB_FILES)
    print(f"Legitimate stdlib logging uses ({len(legit)}):")
    for f in legit:
        print(f"  ✓ {f}")
    print()

    violations = audit(args.root)
    if not violations:
        print("✓ No new stdlib logging uses detected. Migration complete.")
        return 0

    print(f"✗ Found {len(violations)} file(s) with stdlib logging NOT in legitimate list:")
    for p in sorted(violations):
        print(f"  - {p.relative_to(args.root)}")
    print()
    print("Action: либо (a) мигрировать на src.backend.core.logging, "
          "либо (b) добавить в LEGITIMATE_STDLIB_FILES если legitimate use "
          "(+ обновить tests/unit/core/test_legitimate_stdlib_logging.py).")
    return 1 if args.ci else 0


if __name__ == "__main__":
    sys.exit(main())
