"""Legacy DSL processors inventory (W2 P1-2 closure, ADR-0341).

Стратегический анализ 2026-09-22 + v4 §10 P1: «Завершение processor
migration. Построить таблицу 28 legacy-файлов: canonical target, importer
count, warning, identity, removal date».

Этот tool сканирует ``src/backend/dsl/processors/`` (legacy compat
surface per v4 §4.2) и генерирует inventory с:
- LOC, importer count (external src/tests/extensions/tools)
- Canonical target (если есть shim/re-export pattern)
- Status classification (REMOVABLE / NEEDS_MIGRATION / SEMANTIC_KEEP / UNKNOWN)
- Removal gate: только 0-importer + migration_window_elapsed → REMOVABLE

Использование::

    python tools/audit_legacy_processors.py            # human-readable table
    python tools/audit_legacy_processors.py --json    # machine-readable
    python tools/audit_legacy_processors.py --strict  # exit 1 если есть NEEDS_MIGRATION

Per v4 §5 «presence != wiring»:
- Наличие файла в legacy tree — не доказательство его нужности.
- Importer count 0 + canonical target + migration window → REMOVABLE.
- Importer count > 0 → NEEDS_MIGRATION.
- SagaLRA семантически различны per v4 §9 → SEMANTIC_KEEP.

Per v4 §3 «Если источники конфликтуют»:
- runtime поведение устанавливается запуском кода/теста.
- расхождение runtime != architecture фиксируется как debt.

ADR-0341: legacy processor inventory tool pattern.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEGACY_DIR = PROJECT_ROOT / "src" / "backend" / "dsl" / "processors"
SCAN_ROOTS = (
    PROJECT_ROOT / "src",
    PROJECT_ROOT / "tests",
    PROJECT_ROOT / "extensions",
    PROJECT_ROOT / "tools",
    PROJECT_ROOT / "routes",
)


@dataclass(frozen=True)
class LegacyProcessorRow:
    """Одна запись inventory для legacy processor file."""

    file: str
    loc: int
    importer_count: int
    canonical_target: str
    status: str  # REMOVABLE / NEEDS_MIGRATION / SEMANTIC_KEEP / SHIMMED
    has_warning: bool
    module_name: str


# ──────────────────── Module-level cache (per-process) ────────────────────

# Read every Python file in scan roots ONCE and cache by content.
# Without cache: 24 legacy files × ~5000 importers = 120k file reads (~90s).
# With cache: 5000 file reads once (~5s), then 24 in-memory scans (~1s).
_FILE_CONTENT_CACHE: dict[str, str] = {}


def _read_cached(path: Path) -> str:
    """Read file content with module-level cache."""
    key = str(path.resolve())
    if key not in _FILE_CONTENT_CACHE:
        try:
            _FILE_CONTENT_CACHE[key] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            _FILE_CONTENT_CACHE[key] = ""
    return _FILE_CONTENT_CACHE[key]


def _collect_all_py_files() -> list[Path]:
    """Собирает все .py файлы в scan roots (без __pycache__ и без legacy dir)."""
    files: list[Path] = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for py_file in root.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue
            try:
                py_file.resolve().relative_to(LEGACY_DIR.resolve())
                continue
            except ValueError:
                pass
            files.append(py_file)
    return files


def _iter_legacy_files() -> list[Path]:
    """Возвращает legacy .py файлы (исключая __init__.py и __pycache__)."""
    if not LEGACY_DIR.exists():
        return []
    return sorted(
        p for p in LEGACY_DIR.rglob("*.py")
        if p.name != "__init__.py" and "__pycache__" not in str(p)
    )


def _count_loc(path: Path) -> int:
    return sum(1 for _ in _read_cached(path).splitlines())


def _detect_canonical_target(path: Path) -> str:
    """Detect canonical re-export pattern (e.g., `from ...engine.processors.X import ...`)."""
    content = _read_cached(path)
    for line in content.splitlines():
        if re.match(r"^from src\.backend\.dsl\.engine\.processors", line):
            return line.split(" import ")[0].replace("from ", "").strip()
    if "__module__" in content and "engine.processors" in content:
        return "(__module__ override → engine.processors)"
    return "(no canonical re-export)"


def _count_importers(path: Path, all_py_files: list[Path]) -> int:
    """Считает файлы вне legacy tree, которые импортируют данный module."""
    module_name = _module_name_from_path(path)
    if not module_name:
        return 0

    mod_esc = re.escape(module_name)
    patterns = [
        re.compile(rf"from {mod_esc}\b"),
        re.compile(rf"from {mod_esc}\.\w+\b"),
        re.compile(rf"import\s+(?:\([^)]*{mod_esc}[^)]*\)|{mod_esc})\b"),
    ]

    path_resolved = path.resolve()
    importers: set[str] = set()
    for py_file in all_py_files:
        if py_file.resolve() == path_resolved:
            continue
        content = _read_cached(py_file)
        if not content:
            continue
        for pat in patterns:
            if pat.search(content):
                importers.add(str(py_file.relative_to(PROJECT_ROOT)))
                break
    return len(importers)


def _module_name_from_path(path: Path) -> str:
    """`src/backend/dsl/processors/event_store/cqrs.py` → `src.backend.dsl.processors.event_store.cqrs`."""
    try:
        rel = path.relative_to(PROJECT_ROOT / "src" / "backend")
    except ValueError:
        return ""
    parts = list(rel.parts[:-1]) + [rel.stem]
    return ".".join(parts)


def _has_deprecation_warning(path: Path) -> bool:
    """Check if file emits DeprecationWarning at import."""
    content = _read_cached(path)
    return "DeprecationWarning" in content or "deprecated" in content.lower()[:500]


def _classify(row: LegacyProcessorRow) -> str:
    """Classify status per v4 §10 P1."""
    if "saga_lra" in row.file:
        return "SEMANTIC_KEEP"
    if row.canonical_target.startswith("src.backend.dsl.engine.processors"):
        return "SHIMMED"
    if row.canonical_target != "(no canonical re-export)":
        return "NEEDS_MIGRATION"
    if row.importer_count == 0:
        return "REMOVABLE"
    return "NEEDS_MIGRATION"


def build_inventory() -> list[LegacyProcessorRow]:
    """Строит полный inventory legacy processor tree.

    Reads every Python file in scan roots once (cached), then for each legacy
    file computes LOC, canonical target, importer count, classification.
    """
    _FILE_CONTENT_CACHE.clear()
    all_py_files = _collect_all_py_files()

    rows: list[LegacyProcessorRow] = []
    for path in _iter_legacy_files():
        loc = _count_loc(path)
        canonical_target = _detect_canonical_target(path)
        importer_count = _count_importers(path, all_py_files)
        has_warning = _has_deprecation_warning(path)
        module_name = _module_name_from_path(path)
        unclassified = LegacyProcessorRow(
            file=str(path.relative_to(PROJECT_ROOT)),
            loc=loc,
            importer_count=importer_count,
            canonical_target=canonical_target,
            status="",
            has_warning=has_warning,
            module_name=module_name,
        )
        rows.append(
            LegacyProcessorRow(
                file=unclassified.file,
                loc=unclassified.loc,
                importer_count=unclassified.importer_count,
                canonical_target=unclassified.canonical_target,
                status=_classify(unclassified),
                has_warning=unclassified.has_warning,
                module_name=unclassified.module_name,
            )
        )
    return rows


def render_table(rows: list[LegacyProcessorRow]) -> str:
    """Human-readable table."""
    if not rows:
        return "No legacy processor files found.\n"

    lines = [
        f"Legacy DSL processors inventory — {len(rows)} files",
        f"Total LOC: {sum(r.loc for r in rows)}",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        f"{'File':<60} {'LOC':>5} {'Imp':>4} {'Warning':>8} {'Status':<20}",
        "-" * 100,
    ]
    for r in rows:
        warning_marker = "✓" if r.has_warning else "✗"
        lines.append(
            f"{r.file:<60} {r.loc:>5} {r.importer_count:>4} {warning_marker:>8} {r.status:<20}"
        )

    # Summary
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    lines.append("")
    lines.append("Summary:")
    for status, count in sorted(by_status.items()):
        lines.append(f"  {status}: {count} files")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Legacy DSL processors inventory (W2 P1-2 / ADR-0341)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable JSON output.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any NEEDS_MIGRATION files (CI gate).",
    )
    args = parser.parse_args(argv)

    rows = build_inventory()

    if args.json:
        payload = {
            "generated_at": datetime.now(UTC).isoformat(),
            "total_files": len(rows),
            "total_loc": sum(r.loc for r in rows),
            "rows": [asdict(r) for r in rows],
            "summary": {
                status: sum(1 for r in rows if r.status == status)
                for status in {r.status for r in rows}
            },
        }
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(render_table(rows) + "\n")

    if args.strict:
        needs_migration = [r for r in rows if r.status == "NEEDS_MIGRATION"]
        if needs_migration:
            sys.stderr.write(
                f"\nNEEDS_MIGRATION: {len(needs_migration)} files with active importers\n"
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
