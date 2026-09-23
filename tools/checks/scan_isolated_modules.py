"""Runtime reachability gate для production modules.

Аудит 2026-09-21: ``isolated modules`` — core/ модули с focused-tests,
но zero production callers. Увеличивают maintenance surface без пользы.

Правило: production module должен иметь caller вне tests/, smoke-tests, и owner.
Этот скрипт сканирует ``src/backend/core/<module>/`` и сообщает caller counts.

Использование::

    python tools/checks/scan_isolated_modules.py                # human-readable
    python tools/checks/scan_isolated_modules.py --json         # machine output
    python tools/checks/scan_isolated_modules.py --module core.idempotency
    python tools/checks/scan_isolated_modules.py --strict       # exit 1 if isolated

Exit codes:
    0 — все модули имеют production caller
    1 — найдены isolated модули (с --strict)
    2 — usage/config error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
TEST_ROOT = REPO_ROOT / "tests"

# Модули которые НЕ нужно проверять (framework-level, не core features).
# extensions/ — отдельный layer, проверяется своим linter.
# entrypoints/ — это и есть consumer of core/.
# infrastructure/, services/, dsl/, workflows/ — НЕ core/, не в этой выборке.
SKIP_DIRS = {
    "__pycache__",
    "extensions",
    "entrypoints",
    "infrastructure",
    "services",
    "dsl",
    "workflows",
    "frontend",
    "tests",
}


def _is_core_module_dir(path: Path) -> bool:
    """True если path — это ``src/backend/core/<name>/`` директория с __init__.py."""
    return (
        path.is_dir()
        and path.parent.name == "core"
        and (path / "__init__.py").exists()
        and path.parent.parent.name == "backend"
        and path.parent.parent.parent.name == "src"
    )


def _find_callers(
    module_name: str, src_root: Path, test_root: Path
) -> dict[str, list[str]]:
    """Return dict of {'src': [files], 'tests': [files]} для callers.

    Caller — любой .py файл вне самого пакета модуля, содержащий
    ``module_name`` как подстроку в тексте.
    """
    module_pkg_dir = src_root / "backend" / "core" / module_name.replace("core.", "")
    src_callers: list[str] = []
    test_callers: list[str] = []

    for py in src_root.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        # Skip self-package files (если callers ищут core.foo.bar в core/foo/...)
        if module_pkg_dir in py.parents or py.parent == module_pkg_dir:
            continue
        try:
            content = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if module_name in content:
            src_callers.append(str(py.relative_to(REPO_ROOT)))

    for py in test_root.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        try:
            content = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if module_name in content:
            test_callers.append(str(py.relative_to(REPO_ROOT)))

    return {"src": src_callers, "tests": test_callers}


def _discover_core_modules(src_root: Path) -> list[str]:
    """Вернуть список имён core модулей (e.g. ``core.idempotency``)."""
    core_root = src_root / "backend" / "core"
    if not core_root.exists():
        return []
    modules: list[str] = []
    for child in sorted(core_root.iterdir()):
        if child.name in SKIP_DIRS or child.name.startswith("_"):
            continue
        if child.is_dir() and (child / "__init__.py").exists():
            modules.append(f"core.{child.name}")
        elif child.is_file() and child.suffix == ".py" and child.stem != "__init__":
            modules.append(f"core.{child.stem}")
    return modules


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan isolated modules (zero production callers)"
    )
    parser.add_argument(
        "--module", help="Проверить конкретный модуль (e.g. ``core.idempotency``)"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 если найдены isolated модули (для CI gate)",
    )
    parser.add_argument(
        "--json", action="store_true", help="JSON output вместо human-readable table"
    )
    args = parser.parse_args(argv)

    if args.module:
        modules = [args.module]
    else:
        modules = _discover_core_modules(SRC_ROOT)

    results: list[dict[str, object]] = []
    for mod in modules:
        callers = _find_callers(mod, SRC_ROOT, TEST_ROOT)
        isolated = len(callers["src"]) == 0
        results.append(
            {
                "module": mod,
                "src_callers": len(callers["src"]),
                "test_callers": len(callers["tests"]),
                "isolated": isolated,
                "src_files": callers["src"][:5],
                "test_files": callers["tests"][:5],
            }
        )

    if args.json:
        print(
            json.dumps(
                {
                    "modules": results,
                    "isolated_count": sum(1 for r in results if r["isolated"]),
                },
                indent=2,
            )
        )
    else:
        print(f"{'Module':<30} | {'src':>4} | {'tests':>6} | status")
        print("-" * 70)
        for r in results:
            status = (
                "🔴 ISOLATED" if r["isolated"] else f"🟢 {r['src_callers']} callers"
            )
            print(
                f"{r['module']:<30} | {r['src_callers']:>4} | "
                f"{r['test_callers']:>6} | {status}"
            )

    if args.strict:
        isolated = [r for r in results if r["isolated"]]
        if isolated:
            print(f"\n❌ {len(isolated)} isolated module(s) found", file=sys.stderr)
            for r in isolated:
                print(f"  - {r['module']}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
