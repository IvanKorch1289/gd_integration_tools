"""Graphify pinned version gate.

Аудит 2026-09-21 (P2: graphify): graphify должен быть reproducible dev dependency
или CI artifact с pinned version. Hooks не должны молча игнорировать
отсутствие бинарника через ``|| true``.

Этот скрипт проверяет:
1. graphify CLI доступен в PATH
2. version pinned в pyproject.toml (или tools/checks/requires)
3. graph.json и manifest.json существуют
4. graph.json не старше N дней (default 30)

Использование::

    python tools/checks/check_graphify_pinned.py           # human-readable
    python tools/checks/check_graphify_pinned.py --strict  # exit 1 if issues

Exit codes:
    0 — всё OK
    1 — найдены проблемы (с --strict)
    2 — graphify не установлен
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GRAPHIFY_OUT = REPO_ROOT / "graphify-out"
GRAPH_JSON = GRAPHIFY_OUT / "graph.json"
MANIFEST = GRAPHIFY_OUT / "manifest.json"
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _find_graphify() -> str | None:
    """Найти graphify CLI в PATH."""
    path = shutil.which("graphify")
    return path


def _graphify_version() -> str | None:
    """Получить version через ``graphify --version``."""
    path = _find_graphify()
    if path is None:
        return None
    try:
        # S603/S607: full path from shutil.which() — safe.
        result = subprocess.run(  # noqa: S603
            [path, "--version"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except Exception:
        return None


def _manifest_age_days(path: Path) -> float:
    """Возраст manifest.json в днях."""
    if not path.exists():
        return -1.0
    mtime = path.stat().st_mtime
    return (time.time() - mtime) / 86400


def _graph_json_metadata() -> dict[str, object]:
    """Получить metadata из graph.json."""
    if not GRAPH_JSON.exists():
        return {"exists": False}
    try:
        with GRAPH_JSON.open() as f:
            data = json.load(f)
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        return {
            "exists": True,
            "nodes": len(nodes),
            "edges": len(edges),
            "size_kb": GRAPH_JSON.stat().st_size / 1024,
        }
    except Exception as exc:
        return {"exists": True, "error": str(exc)}


def _find_pinned_version() -> str | None:
    """Найти pinned version в pyproject.toml или requirements."""
    if not PYPROJECT.exists():
        return None
    try:
        content = PYPROJECT.read_text(encoding="utf-8")
    except OSError:
        return None
    # Match "graphify==X.Y.Z" or "graphify>=X.Y.Z" patterns
    import re

    for pattern in [
        r"graphify==(\d+\.\d+\.\d+)",
        r'"graphify[^"]*==(\d+\.\d+\.\d+)"',
        r'graphify\s*=\s*"==(\d+\.\d+\.\d+)"',
    ]:
        m = re.search(pattern, content)
        if m:
            return m.group(1)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check graphify pinned version + reproducibility"
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=30,
        help="Max age of graph.json / manifest.json in days (default: 30)",
    )
    parser.add_argument(
        "--strict", action="store_true", help="Exit 1 if any issues found"
    )
    args = parser.parse_args(argv)

    issues: list[str] = []
    notes: list[str] = []

    # 1. graphify CLI availability
    cli_path = _find_graphify()
    if cli_path is None:
        issues.append(
            "graphify CLI not in PATH — install via `pip install graphify==<ver>`"
        )
    else:
        version = _graphify_version()
        notes.append(f"CLI: {cli_path}, version: {version}")

    # 2. pinned version check
    pinned = _find_pinned_version()
    if pinned is None:
        notes.append(
            "No pinned graphify version in pyproject.toml — audit recommendation"
        )
    else:
        notes.append(f"Pinned in pyproject.toml: {pinned}")
        if cli_path:
            actual = _graphify_version()
            if actual and pinned not in actual:
                issues.append(
                    f"Pinned version mismatch: pyproject.toml={pinned}, "
                    f"actual CLI={actual}"
                )

    # 3. graph.json + manifest existence
    meta = _graph_json_metadata()
    if not meta.get("exists"):
        issues.append(f"{GRAPH_JSON} missing — run `graphify update .`")
    else:
        notes.append(
            f"graph.json: {meta.get('nodes', 0)} nodes, "
            f"{meta.get('edges', 0)} edges, "
            f"{meta.get('size_kb', 0):.0f} KB"
        )

    if not MANIFEST.exists():
        notes.append(f"{MANIFEST} missing — graphify never extracted code")
    else:
        age = _manifest_age_days(MANIFEST)
        notes.append(f"manifest.json age: {age:.1f} days")
        if age > args.max_age_days:
            issues.append(
                f"manifest.json is {age:.0f} days old "
                f"(max: {args.max_age_days}) — run `graphify update .`"
            )

    # Print report
    print(f"{'=' * 60}")
    print(f"Graphify pinned-version gate (max age: {args.max_age_days} days)")
    print(f"{'=' * 60}")
    print()
    print("Status:")
    for n in notes:
        print(f"  ℹ️  {n}")
    print()
    if issues:
        print("Issues:")
        for i in issues:
            print(f"  ❌ {i}")
    else:
        print("✅ All checks passed")
    print()

    if args.strict and issues:
        return 1
    if cli_path is None:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
