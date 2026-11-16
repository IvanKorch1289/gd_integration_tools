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
    _sync_mutants_assets,
    _sync_mutants_src,
)


def _run_mutmut(repo_root: Path, env: dict[str, str]) -> int:
    print("[check_mutmut] Running mutmut run...")
    proc = subprocess.run(  # noqa: S603  # dev-tool: фиксированная команда
        # python -m mutmut, а не PATH-бинарник: в venv скрипт не всегда
        # установлен (в CI — uv run, где бинарник есть, локально — нет).
        [sys.executable, "-m", "mutmut", "run"],
        cwd=repo_root,
        env=env,
    )
    return proc.returncode


def _export_cicd_stats(repo_root: Path, env: dict[str, str]) -> Path:
    print("[check_mutmut] Exporting CI/CD stats...")
    proc = subprocess.run(  # noqa: S603  # dev-tool: фиксированная команда
        [sys.executable, "-m", "mutmut", "export-cicd-stats"], cwd=repo_root, env=env
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


_BASELINE_PATH = Path(".baselines/mutation.json")


def _load_baseline(path: Path = _BASELINE_PATH) -> float:
    """Прочитать порог из baseline-файла (рэтчет, ADR-0452).

    Args:
        path: Путь к baseline-файлу.

    Returns:
        Порог в процентах; при отсутствии файла — дефолт 55.

    """
    if not path.exists():
        return 55.0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return float(data.get("mutation_score_percent", 55.0))
    except OSError, ValueError, json.JSONDecodeError:
        return 55.0


def main() -> int:
    parser = argparse.ArgumentParser(description="Mutation testing gate")
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help=(
            "Minimum mutation score threshold (%%); по умолчанию — значение из "
            "baseline (.baselines/mutation.json), т.е. рэтчет «не хуже baseline»"
        ),
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="записать измеренный score в baseline-файл",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["GD_REPO_ROOT"] = str(repo_root)

    _patch_mutmut()
    _sync_mutants_src()
    _sync_mutants_assets()

    exit_code = _run_mutmut(repo_root, env)
    if exit_code != 0:
        print(f"[check_mutmut] mutmut run failed with exit code {exit_code}")
        return exit_code

    stats_path = _export_cicd_stats(repo_root, env)
    score = _parse_score(stats_path)

    threshold = args.threshold if args.threshold is not None else _load_baseline()

    if args.update_baseline:
        _BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _BASELINE_PATH.write_text(
            json.dumps(
                {
                    "mutation_score_percent": round(score, 1),
                    "updated": "2026-11-17",
                    "note": (
                        "ADR-0452: baseline зафиксирован первым рабочим прогоном "
                        "mutmut (раньше гейт был заблокирован ошибками сбора). "
                        "Рост — только с новыми тестами на мутируемые модули."
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"[check_mutmut] baseline обновлён: {score:.1f}% → {_BASELINE_PATH}")
        return 0

    print(f"[check_mutmut] Mutation score: {score:.1f}% (threshold: {threshold:.1f}%)")

    if score >= threshold:
        print(f"[check_mutmut] PASS: score {score:.1f}% >= {threshold:.1f}%")
        return 0
    else:
        print(f"[check_mutmut] FAIL: score {score:.1f}% < {threshold:.1f}%")
        return 1


if __name__ == "__main__":
    sys.exit(main())
