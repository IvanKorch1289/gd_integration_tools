#!/usr/bin/env python3
"""Cache facade uniqueness CI guard (ADR-0352 Stage 1, cycle 163).

ADR-0352 documents the merge plan for two ``UnifiedCacheFacade`` classes
in core/ and services/. Until Stage 2-4 are implemented, we need a CI
guard to:

1. **Whitelist**: only two files may define ``class UnifiedCacheFacade``:
   - ``src/backend/core/cache/facade.py`` (ABC, will become re-export alias
     at Stage 2)
   - ``src/backend/services/cache/facade.py`` (concrete, will become
     canonical at Stage 2)

2. **Re-export contract**: both files must continue to expose
   ``UnifiedCacheFacade`` in their ``__all__`` (re-export pattern).

3. **Singletons**: only one module-level instance of ``cache_settings``
   (``src.backend.core.config.services.cache``).

Использование::

    python tools/checks/check_cache_facade_uniqueness.py            # human-readable
    python tools/checks/check_cache_facade_uniqueness.py --strict    # exit 1 on violation
    python tools/checks/check_cache_facade_uniqueness.py --json      # machine-readable
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src" / "backend"

# Files that may define ``class UnifiedCacheFacade``.
# At Stage 2: core/cache/facade.py becomes a re-export (still allowed to mention
# the name, but not to define ``class UnifiedCacheFacade``).
ALLOWED_DEFINITION_FILES: frozenset[str] = frozenset(
    {
        "src/backend/core/cache/facade.py",
        "src/backend/services/cache/facade.py",
    }
)

# Modules that may re-export ``UnifiedCacheFacade`` via __all__.
# core/cache/__init__.py + services/cache/__init__.py.
ALLOWED_REEXPORT_MODULES: frozenset[str] = frozenset(
    {
        "src.backend.core.cache",
        "src.backend.core.cache.facade",
        "src.backend.services.cache",
        "src.backend.services.cache.facade",
    }
)

# Allowed location for cache_settings singleton.
ALLOWED_SETTINGS_INSTANCES: frozenset[tuple[str, str]] = frozenset(
    {
        # (file, attribute_name) — only ONE module-level cache_settings
        ("src/backend/core/config/services/cache.py", "cache_settings"),
    }
)


@dataclass(frozen=True, slots=True)
class Violation:
    """A single violation found by the check."""

    kind: str
    file: str
    line: int
    message: str
    snippet: str = ""

    def to_dict(self) -> dict[str, object]:
        """Convert to JSON-friendly dict."""
        return {
            "kind": self.kind,
            "file": self.file,
            "line": self.line,
            "message": self.message,
            "snippet": self.snippet,
        }


@dataclass(slots=True)
class Report:
    """Aggregate report."""

    violations: list[Violation] = field(default_factory=list)
    files_scanned: int = 0
    classes_seen: int = 0

    def add(self, v: Violation) -> None:
        self.violations.append(v)

    def is_clean(self) -> bool:
        return not self.violations


def _iter_python_files(root: Path) -> Iterable[Path]:
    """Yield all Python files under ``root``, skipping caches."""
    for py in root.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        # Skip migrations / vendor / .venv — they're either generated or
        # external.
        parts = py.parts
        if any(
            skip in parts
            for skip in (".venv", "var", "mutants", "__pycache__")
        ):
            continue
        yield py


def _check_definition_uniqueness(
    py: Path, report: Report
) -> None:
    """Ensure ``class UnifiedCacheFacade`` only appears in whitelisted files."""
    try:
        tree = ast.parse(py.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return

    try:
        rel = str(py.relative_to(PROJECT_ROOT))
    except ValueError:
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "UnifiedCacheFacade":
            report.classes_seen += 1
            if rel not in ALLOWED_DEFINITION_FILES:
                snippet = ast.unparse(node).split("\n")[0][:120]
                report.add(
                    Violation(
                        kind="unauthorized_definition",
                        file=rel,
                        line=node.lineno,
                        message=(
                            f"class UnifiedCacheFacade defined in non-whitelisted "
                            f"file '{rel}'. Only allowed in: "
                            f"{sorted(ALLOWED_DEFINITION_FILES)}. See ADR-0352."
                        ),
                        snippet=snippet,
                    )
                )


def _check_reexport_contract(
    py: Path, report: Report
) -> None:
    """Ensure __init__.py of cache packages mentions UnifiedCacheFacade."""
    try:
        tree = ast.parse(py.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return

    try:
        rel = py.relative_to(PROJECT_ROOT)
    except ValueError:
        return

    # Only check __init__.py of cache packages.
    rel_str = str(rel)
    if not rel_str.endswith("__init__.py"):
        return

    # Reconstruct the src.backend.* module path from the rel path.
    # e.g. src/backend/core/cache/__init__.py → src.backend.core.cache
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    if not parts or parts[0] != "src" or parts[1] != "backend":
        return
    module = ".".join(parts)
    # Strip ".py" suffix if present.
    if module.endswith(".py"):
        module = module[:-3]

    if module not in ALLOWED_REEXPORT_MODULES:
        return

    all_names = _extract_all_names(tree)
    if "UnifiedCacheFacade" not in all_names:
        report.add(
            Violation(
                kind="missing_reexport",
                file=rel_str,
                line=0,
                message=(
                    f"Module '{module}' must re-export 'UnifiedCacheFacade' "
                    f"in __all__. This is the canonical public entry point "
                    f"(CLAUDE.md R1 single canonical API)."
                ),
            )
        )


def _extract_all_names(tree: ast.Module) -> set[str]:
    """Return the union of all string literals in any __all__ assignment."""
    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Name)
                and target.id == "__all__"
                and isinstance(node.value, (ast.List, ast.Tuple))
            ):
                for elt in node.value.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        names.add(elt.value)
    return names


def _check_settings_singleton(
    py: Path, report: Report
) -> None:
    """Ensure ``cache_settings = CacheSettings()`` only in canonical location."""
    try:
        tree = ast.parse(py.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return

    try:
        rel = str(py.relative_to(PROJECT_ROOT))
    except ValueError:
        return

    # Only check top-level (module-level) assignments, not nested ones.
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Name)
                and target.id == "cache_settings"
            ):
                key = (rel, "cache_settings")
                if key not in ALLOWED_SETTINGS_INSTANCES:
                    report.add(
                        Violation(
                            kind="unauthorized_settings_singleton",
                            file=rel,
                            line=node.lineno,
                            message=(
                                f"Module-level cache_settings singleton "
                                f"in non-canonical location '{rel}'. "
                                f"Only allowed: "
                                f"{sorted(k[0] for k in ALLOWED_SETTINGS_INSTANCES)}."
                            ),
                        )
                    )


def main(argv: list[str] | None = None) -> int:
    """Run the check and return exit code."""
    parser = argparse.ArgumentParser(
        description="Cache facade uniqueness guard (ADR-0352 Stage 1)"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 if any violation is found.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON instead of human-readable text.",
    )
    args = parser.parse_args(argv)

    report = Report()
    files = list(_iter_python_files(SRC_ROOT))
    for py in files:
        report.files_scanned += 1
        _check_definition_uniqueness(py, report)
        _check_reexport_contract(py, report)
        _check_settings_singleton(py, report)

    if args.json:
        print(
            json.dumps(
                {
                    "files_scanned": report.files_scanned,
                    "classes_seen": report.classes_seen,
                    "violations": [v.to_dict() for v in report.violations],
                    "clean": report.is_clean(),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(f"Scanned {report.files_scanned} Python files")
        print(f"Saw {report.classes_seen} 'class UnifiedCacheFacade' definitions")
        if report.is_clean():
            print("✅ CLEAN — no violations")
        else:
            print(f"❌ {len(report.violations)} violation(s):")
            for v in report.violations:
                print(
                    f"  [{v.kind}] {v.file}:{v.line} — {v.message}"
                )
                if v.snippet:
                    print(f"      | {v.snippet}")

    if args.strict and not report.is_clean():
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())