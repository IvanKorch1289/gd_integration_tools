"""Per-layer coverage diagnostic (Sprint 4, audit 2026-08-19).

Reports per-layer coverage % для каждого layer (core, infrastructure,
services, dsl, entrypoints, extensions). Diagnostic only — no gate
enforcement yet (deferred to Sprint 5+ при наличии baseline).

Usage:
    .venv/bin/python tools/coverage/per_layer_diagnostic.py [--fail-under-layer K1=75 K2=80 ...]

Output: Markdown table со столбцами Layer | Files | Lines | % Coverage
+ exit-code 0 если все layers >= goal (или --fail-under-layer не задан).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LAYERS = (
    "core",
    "infrastructure",
    "services",
    "dsl",
    "entrypoints",
    "frontend",
    "extensions",
)


def _parse_coverage() -> dict[str, tuple[int, int, float]]:
    """Парсит ``coverage report`` output (Stmts | Miss | Cover).

    Note: ``coverage report`` может exit != 0 (below ``fail_under``).
    Мы ловим и парсим stdout всё равно.
    """
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "coverage", "report", "--skip-empty"],
        capture_output=True, text=True, cwd=REPO_ROOT, check=False,
    )
    if result.returncode not in (0, 2):
        # 0 = pass, 2 = below fail_under (мы просто парсим данные).
        raise RuntimeError(
            f"coverage report failed: rc={result.returncode} "
            f"stderr={result.stderr[:500]}",
        )
    per_layer: dict[str, tuple[int, int, float]] = {}
    for layer in LAYERS:
        per_layer[layer] = (0, 0, 0.0)

    for line in result.stdout.splitlines():
        # Format: src/backend/<layer>/...   Stmts  Miss  Branch  BrPart  Cover%
        m = re.match(
            r"src/backend/(" + "|".join(LAYERS) + r")/(.+?)\s+"
            r"(\d+)\s+(\d+)\s+\d+\s+\d+\s+(\d+(?:\.\d+)?)%",
            line,
        )
        if not m:
            continue
        layer = m.group(1)
        stmts = int(m.group(3))
        miss = int(m.group(4))
        cover = float(m.group(5))
        stmts_cur, miss_cur, _ = per_layer[layer]
        per_layer[layer] = (stmts_cur + stmts, miss_cur + miss, cover)
    return per_layer


def _format_pct(pct: float) -> str:
    return f"{pct:.1f}%" if pct > 0 else "—"


def _render_table(per_layer: dict[str, tuple[int, int, float]]) -> str:
    lines = [
        "# Per-Layer Coverage Diagnostic",
        "",
        "| Layer | Files | Lines | Miss | Coverage |",
        "|-------|------:|------:|-----:|---------:|",
    ]
    for layer in LAYERS:
        stmts, miss, cover = per_layer[layer]
        lines.append(
            f"| `{layer}` | — | {stmts} | {miss} | {_format_pct(cover)} |",
        )
    return "\n".join(lines)


def _parse_goals(args_goals: list[str]) -> dict[str, int]:
    """Parse ``--fail-under-layer K1=75 K2=80`` → {K1: 75, K2: 80}."""
    out: dict[str, int] = {}
    for spec in args_goals:
        key, _, val = spec.partition("=")
        if not val.isdigit():
            continue
        out[key.upper()] = int(val)
    return out


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fail-under-layer",
        action="append",
        default=[],
        help="Layer-specific goal (repeatable): K1=75 K2=80 ...",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    per_layer = _parse_coverage()
    print(_render_table(per_layer))

    goals = _parse_goals(args.fail_under_layer)
    if not goals:
        return 0

    # Поскольку у нас только 6 layer'ов (K1..K6), маппим K1..K6 → LAYERS.
    failures: list[str] = []
    for i, layer in enumerate(LAYERS, start=1):
        key = f"K{i}"
        if key not in goals:
            continue
        goal = goals[key]
        _, _, cover = per_layer[layer]
        if cover < goal:
            failures.append(f"  - {layer}: {cover:.1f}% < goal {goal}%")

    if failures:
        print(f"\n❌ Per-layer gate FAILED ({len(failures)} layers below goal):")
        for line in failures:
            print(line)
        return 1

    print(f"\n✅ Per-layer gate PASSED ({len(goals)} goals met)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
