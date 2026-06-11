#!/usr/bin/env python3
"""Gate-скрипт для проверки mutation score (mutmut) в CI.

Запускает mutmut baseline через wrapper, экспортирует CI/CD stats
и сверяет score с порогом (default 55%%).

Использование::

    uv run python tools/checks/check_mutmut.py [--threshold 55]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Импортируем helper'ы из wrapper'а
sys.path.insert(0, str(Path(__file__).parent))
from run_mutmut import (  # type: ignore[import-not-found]  # noqa: E402  # dev-tool: sys.path hack
    _patch_mutmut,
    _sync_mutants_src,
)


def _run_mutmut(repo_root: Path, env: dict[str, str]) -> int:
    print("[check_mutmut] Running mutmut run...")
    proc = subprocess.run(  # noqa: S603  # dev-tool: фиксированная команда
        ["mutmut", "run"],  # noqa: S607  # dev-tool: mutmut — PATH binary
        cwd=repo_root,
        env=env,
    )
    return proc.returncode


def _export_cicd_stats(repo_root: Path, env: dict[str, str]) -> Path:
    print("[check_mutmut] Exporting CI/CD stats...")
    proc = subprocess.run(  # noqa: S603  # dev-tool: фиксированная команда
        ["mutmut", "export-cicd-stats"],  # noqa: S607  # dev-tool: mutmut — PATH binary
        cwd=repo_root,
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError("mutmut export-cicd-stats failed")
    stats_path = repo_root / "mutants" / "mutmut-cicd-stats.json"
    if not stats_path.exists():
        raise RuntimeError(f"CI/CD stats file not found: {stats_path}")
    return stats_path


def _parse_score(stats_path: Path) -> float:
    data = json.loads(stats_path.read_text())
    total = data.get("total", 0)
    killed = data.get("killed", 0)
    if total == 0:
        return 0.0
    return (killed / total) * 100.0


def main() -> int:
    parser = argparse.ArgumentParser(description="Mutation testing gate")
    parser.add_argument(
        "--threshold",
        type=float,
        default=55.0,
        help="Minimum mutation score threshold (%%) (default: 55)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["GD_REPO_ROOT"] = str(repo_root)

    _patch_mutmut()
    _sync_mutants_src()

    exit_code = _run_mutmut(repo_root, env)
    if exit_code != 0:
        print(f"[check_mutmut] mutmut run failed with exit code {exit_code}")
        return exit_code

    stats_path = _export_cicd_stats(repo_root, env)
    score = _parse_score(stats_path)

    print(f"[check_mutmut] Mutation score: {score:.1f}% (threshold: {args.threshold}%)")

    if score >= args.threshold:
        print(f"[check_mutmut] PASS: score {score:.1f}% >= {args.threshold}%")
        return 0
    else:
        print(f"[check_mutmut] FAIL: score {score:.1f}% < {args.threshold}%")
        return 1


if __name__ == "__main__":
    sys.exit(main())
