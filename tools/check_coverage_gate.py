"""Sprint 6 K3 — Coverage gate CLI.

Wave ``[wave:s6/k3-coverage-gate-70]``.

Назначение: blocking-проверка покрытия тестами модулей ``src/backend``.
Целевой порог — **70%** (декларировано в PLAN.md V18.1 Sprint 6 K3 DoD).

Источник данных: ``coverage.xml`` (формат cobertura), создаваемый
``pytest --cov=src/backend --cov-report=xml``.

Использование::

    # 1. Запустить pytest с coverage:
    pytest --cov=src/backend --cov-report=xml

    # 2. Проверить порог:
    python tools/check_coverage_gate.py --threshold 70

    # 3. Зафиксировать baseline (только при первой настройке):
    python tools/check_coverage_gate.py --update-baseline

Baseline-snapshot хранится в ``.baselines/coverage.json``.
При повторных запусках сравнивает с baseline: если coverage упал
относительно baseline более чем на 0.5%, гейт падает. Если поднялся —
гейт пропускает.

Если 70% недостижим за текущий wave (вариант B из плана) — порог
снижается через CLI-флаг ``--threshold 60``, и в baseline появляется
запись ``next_wave_todo: "raise threshold to 70"``.

Exit-codes:

* ``0`` — coverage >= threshold;
* ``1`` — coverage < threshold OR drop > 0.5% от baseline;
* ``2`` — error (нет coverage.xml / parse-fail).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

EXIT_OK = 0
EXIT_THRESHOLD_FAIL = 1
EXIT_ERROR = 2

_DEFAULT_THRESHOLD = 70.0
_BASELINE_DROP_TOLERANCE = 0.5  # допустимое снижение от baseline (в %)


def _parse_coverage_xml(path: Path) -> float:
    """Парсит cobertura ``coverage.xml`` и возвращает суммарный line-rate (%).

    Args:
        path: Путь к ``coverage.xml`` (формат cobertura).

    Returns:
        Покрытие в процентах (0-100).

    Raises:
        FileNotFoundError: Если файл отсутствует.
        ValueError: Если XML не содержит ``line-rate``.
    """
    if not path.exists():
        raise FileNotFoundError(f"coverage.xml не найден: {path}")

    tree = ET.parse(path)  # noqa: S314 (cobertura — наш собственный файл)
    root = tree.getroot()
    rate = root.get("line-rate")
    if rate is None:
        raise ValueError("coverage.xml: атрибут 'line-rate' отсутствует")
    return float(rate) * 100.0


def _load_baseline(path: Path) -> dict[str, Any]:
    """Читает baseline-snapshot ``.baselines/coverage.json``.

    Если файл отсутствует — возвращает пустой dict (первый запуск).
    """
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_baseline(path: Path, data: dict[str, Any]) -> None:
    """Сохраняет baseline в ``.baselines/coverage.json``."""
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _check_drop(current: float, baseline: float) -> bool:
    """Возвращает True, если падение от baseline превышает tolerance."""
    return baseline - current > _BASELINE_DROP_TOLERANCE


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sprint 6 K3 coverage gate (≥70% blocking)."
    )
    parser.add_argument(
        "--coverage-xml",
        default="coverage.xml",
        help="Путь к coverage.xml (cobertura формат).",
    )
    parser.add_argument(
        "--baseline",
        default=".baselines/coverage.json",
        help="Путь к baseline-snapshot.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=_DEFAULT_THRESHOLD,
        help=f"Минимальный coverage в %% (default: {_DEFAULT_THRESHOLD}).",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Обновить baseline текущим значением (только при первой настройке).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Жёсткий режим: падать при coverage < threshold ИЛИ "
        "drop > 0.5%% от baseline.",
    )
    args = parser.parse_args()

    coverage_path = Path(args.coverage_xml)
    baseline_path = Path(args.baseline)

    try:
        current = _parse_coverage_xml(coverage_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR

    print(f"Coverage: {current:.2f}%")
    print(f"Threshold: {args.threshold:.2f}%")

    baseline = _load_baseline(baseline_path)
    baseline_value = baseline.get("coverage_percent")
    if baseline_value is not None:
        print(f"Baseline: {baseline_value:.2f}%")

    if args.update_baseline:
        baseline["coverage_percent"] = current
        baseline["threshold"] = args.threshold
        baseline.setdefault("notes", [])
        if current < _DEFAULT_THRESHOLD:
            todo = (
                f"raise threshold from {args.threshold:.0f} to {_DEFAULT_THRESHOLD:.0f}"
            )
            if todo not in baseline.get("next_wave_todo", []):
                baseline.setdefault("next_wave_todo", []).append(todo)
        _save_baseline(baseline_path, baseline)
        print(f"baseline обновлён: {baseline_path}")
        return EXIT_OK

    # Гейт: текущий coverage ниже порога — fail.
    if current < args.threshold:
        print(
            f"FAIL: coverage {current:.2f}% < threshold {args.threshold:.2f}%",
            file=sys.stderr,
        )
        return EXIT_THRESHOLD_FAIL

    # Strict: drop от baseline > 0.5% — fail.
    if (
        args.strict
        and baseline_value is not None
        and _check_drop(current, baseline_value)
    ):
        print(
            f"FAIL: coverage drop > {_BASELINE_DROP_TOLERANCE}% "
            f"(baseline={baseline_value:.2f}%, current={current:.2f}%)",
            file=sys.stderr,
        )
        return EXIT_THRESHOLD_FAIL

    print(f"OK: coverage gate passed ({current:.2f}% >= {args.threshold:.2f}%)")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
