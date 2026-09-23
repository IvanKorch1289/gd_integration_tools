"""Auto-generate docs/FEATURE_INVENTORY.md from scan_isolated_modules.py.

Аудит 2026-09-21 (P3: docs drift gate): FEATURE_INVENTORY.md должен быть
auto-generated из runtime scan, не manual. Этот скрипт собирает caller counts
из ``scan_isolated_modules.py`` и пишет structured markdown.

Использование::

    python tools/checks/generate_feature_inventory.py         # regenerate
    python tools/checks/generate_feature_inventory.py --dry-run # print

Exit codes:
    0 — generation successful
    1 — script/config error
"""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = REPO_ROOT / "docs" / "FEATURE_INVENTORY.md"


def _run_scan_isolated() -> list[dict[str, object]]:
    """Run scan_isolated_modules.py --json, parse output."""
    # S607: фиксированная команда, не user input.
    result = subprocess.run(  # noqa: S607
        [sys.executable, "tools/checks/scan_isolated_modules.py", "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode not in (0, 1):
        # 0 = no isolated, 1 = some isolated, both OK
        print(f"scan_isolated_modules.py failed: {result.stderr}", file=sys.stderr)
        return []
    try:
        data = json.loads(result.stdout)
        return data.get("modules", [])
    except json.JSONDecodeError as exc:
        print(f"JSON decode error: {exc}", file=sys.stderr)
        return []


def _classify(callers: int, isolated: bool) -> str:
    """Вернуть рекомендованный статус по caller count."""
    if not isolated:
        return "🟢 WIRED"
    return "🔴 ISOLATED — needs decision"


def _build_table(modules: list[dict[str, object]]) -> str:
    """Build markdown table для всех модулей."""
    lines: list[str] = []
    lines.append("| Module | src callers | tests | Status | Recommendation |")
    lines.append("|---|---:|---:|---|---|")
    for mod in sorted(modules, key=lambda m: (m.get("isolated", False), m["module"])):
        name = mod["module"]
        src = mod.get("src_callers", 0)
        tests = mod.get("test_callers", 0)
        isolated = mod.get("isolated", False)
        status = _classify(src, isolated)
        if isolated:
            rec = "decision needed: wire / experimental / delete"
        elif src <= 2:
            rec = "low usage — consider consolidating"
        else:
            rec = "production module"
        lines.append(f"| `{name}` | {src} | {tests} | {status} | {rec} |")
    return "\n".join(lines)


# Fix for F541 — f-string without placeholders.
def _append_blank_line(lines: list[str]) -> None:
    """Append empty line (avoid F541 — f-string without placeholders)."""
    lines.append("")


def _summary_stats(modules: list[dict[str, object]]) -> dict[str, int]:
    """Return aggregated stats."""
    total = len(modules)
    isolated = sum(1 for m in modules if m.get("isolated", False))
    wired = total - isolated
    total_src_callers = sum(m.get("src_callers", 0) for m in modules)
    total_test_callers = sum(m.get("test_callers", 0) for m in modules)
    return {
        "total": total,
        "isolated": isolated,
        "wired": wired,
        "total_src_callers": total_src_callers,
        "total_test_callers": total_test_callers,
    }


def generate() -> str:
    """Generate FEATURE_INVENTORY.md content."""
    modules = _run_scan_isolated()
    stats = _summary_stats(modules)
    iso = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines: list[str] = []
    lines.append("# FEATURE_INVENTORY — Core module reachability registry")
    lines.append("")
    lines.append(f"> **Generated**: {iso}")
    lines.append("> **Source**: `tools/checks/scan_isolated_modules.py --json`")
    lines.append("> **DO NOT EDIT MANUALLY** — auto-generated from real scan.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Total core/ modules**: {stats['total']}")
    lines.append(f"- **🟢 WIRED** (≥1 production caller): {stats['wired']}")
    lines.append(f"- **🔴 ISOLATED** (zero production callers): {stats['isolated']}")
    lines.append(f"- **Total src caller references**: {stats['total_src_callers']}")
    lines.append(f"- **Total test caller references**: {stats['total_test_callers']}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Methodology")
    lines.append("")
    lines.append(
        "Caller criterion: any non-empty match of `core.<module_name>` "
        "(full dotted path) в .py file вне самого пакета модуля."
    )
    lines.append(
        "Tests included for visibility but do **not** count as production usage."
    )
    lines.append("")
    lines.append("Решение per isolated module:")
    lines.append(
        "- **WIRE**: подключить через composition root / DI, добавить end-to-end test."
    )
    lines.append(
        "- **EXPERIMENTAL**: перенести в extensions/experimental или закрыть feature flag."
    )
    lines.append("- **DELETE**: удалить duplicate или незадействованный код.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## All modules (sorted by isolation)")
    lines.append("")
    lines.append(_build_table(modules))
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Regeneration")
    lines.append("")
    lines.append("```bash")
    lines.append("# Local:")
    lines.append("python tools/checks/generate_feature_inventory.py")
    lines.append("")
    lines.append("# Direct scan:")
    lines.append("python tools/checks/scan_isolated_modules.py")
    lines.append(
        "python tools/checks/scan_isolated_modules.py --strict  # exit 1 if isolated"
    )
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate FEATURE_INVENTORY.md from isolated modules scan"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print to stdout instead of writing file"
    )
    args = parser.parse_args(argv)

    content = generate()

    if args.dry_run:
        print(content)
        return 0

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(content, encoding="utf-8")
    print(f"Written: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
