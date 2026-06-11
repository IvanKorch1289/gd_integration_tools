"""Sprint 6 K3 — Coverage gate CLI.

Wave ``[wave:s6/k3-coverage-gate-70]`` + ``[wave:s19/k2-w4-coverage-ratchet-75]``.

S59 W1 (libraries > custom, v22 п.5): мигрирован с ``argparse`` на
``typer`` + ``rich``.

Назначение: blocking-проверка покрытия тестами модулей ``src/backend``.
Целевой порог — **75%** (S19 K2 W4 ratchet: 70% → 75% per PLAN.md V22 Sprint 19 DoD).

Источник данных: ``coverage.xml`` (формат cobertura), создаваемый
``pytest --cov=src/backend --cov-report=xml``.

Использование::

    # 1. Запустить pytest с coverage:
    pytest --cov=src/backend --cov-report=xml

    # 2. Проверить порог:
    python tools/check_coverage_gate.py --threshold 75

    # 3. Зафиксировать baseline (только при первой настройке):
    python tools/check_coverage_gate.py --update-baseline

Baseline-snapshot хранится в ``.baselines/coverage.json``.
При повторных запусках сравнивает с baseline: если coverage упал
относительно baseline более чем на 0.5%, гейт падает. Если поднялся —
гейт пропускает.

Если 75% недостижим за текущий wave (вариант B из плана) — порог
снижается через CLI-фlag ``--threshold``, и в baseline появляется
запись ``next_wave_todo: "raise threshold to 75"``.

Exit-codes:
* ``0`` — coverage >= threshold;
* ``1`` — coverage < threshold OR drop > 0.5% от baseline;
* ``2`` — error (нет coverage.xml / parse-fail).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import typer
from rich.console import Console

EXIT_OK = 0
EXIT_THRESHOLD_FAIL = 1
EXIT_ERROR = 2

_DEFAULT_THRESHOLD = 75.0
_BASELINE_DROP_TOLERANCE = 0.5  # допустимое снижение от baseline (в %)

app = typer.Typer(
    name="check_coverage_gate",
    help="Sprint 6 K3 coverage gate (≥75% blocking).",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
console_err = Console(stderr=True, style="red")


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


@app.command()
def main(
    coverage_xml: str = typer.Option(
        "coverage.xml", "--coverage-xml", help="Путь к coverage.xml (cobertura формат)."
    ),
    baseline: str = typer.Option(
        ".baselines/coverage.json", "--baseline", help="Путь к baseline-snapshot."
    ),
    threshold: float = typer.Option(
        _DEFAULT_THRESHOLD,
        "--threshold",
        help=f"Минимальный coverage в %% (default: {_DEFAULT_THRESHOLD}).",
    ),
    update_baseline: bool = typer.Option(
        False,
        "--update-baseline",
        help="Обновить baseline текущим значением (только при первой настройке).",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Жёсткий режим: падать при coverage < threshold ИЛИ "
        "drop > 0.5%% от baseline.",
    ),
) -> None:
    """CLI-entrypoint (typer)."""
    coverage_path = Path(coverage_xml)
    baseline_path = Path(baseline)

    try:
        current = _parse_coverage_xml(coverage_path)
    except (FileNotFoundError, ValueError) as exc:
        console_err.print(f"[red]ERROR: {exc}[/red]")
        raise typer.Exit(EXIT_ERROR) from exc

    console.print(f"Coverage: [bold]{current:.2f}%[/bold]")
    console.print(f"Threshold: [bold]{threshold:.2f}%[/bold]")

    baseline_data = _load_baseline(baseline_path)
    baseline_value = baseline_data.get("coverage_percent")
    if baseline_value is not None:
        console.print(f"Baseline: [bold]{baseline_value:.2f}%[/bold]")

    if update_baseline:
        baseline_data["coverage_percent"] = current
        baseline_data["threshold"] = threshold
        baseline_data.setdefault("notes", [])
        if current < _DEFAULT_THRESHOLD:
            todo = f"raise threshold from {threshold:.0f} to {_DEFAULT_THRESHOLD:.0f}"
            if todo not in baseline_data.get("next_wave_todo", []):
                baseline_data.setdefault("next_wave_todo", []).append(todo)
        _save_baseline(baseline_path, baseline_data)
        console.print(f"[green]baseline обновлён: {baseline_path}[/green]")
        raise typer.Exit(EXIT_OK)

    # Гейт: текущий coverage ниже порога — fail.
    if current < threshold:
        console_err.print(
            f"[bold red]FAIL:[/bold red] coverage {current:.2f}% < threshold {threshold:.2f}%"
        )
        raise typer.Exit(EXIT_THRESHOLD_FAIL)

    # Strict: drop от baseline > 0.5% — fail.
    if strict and baseline_value is not None and _check_drop(current, baseline_value):
        console_err.print(
            f"[bold red]FAIL:[/bold red] coverage drop > {_BASELINE_DROP_TOLERANCE}% "
            f"(baseline={baseline_value:.2f}%, current={current:.2f}%)"
        )
        raise typer.Exit(EXIT_THRESHOLD_FAIL)

    console.print(
        f"[bold green]OK[/bold green]: coverage gate passed "
        f"({current:.2f}% >= {threshold:.2f}%)"
    )
    raise typer.Exit(EXIT_OK)


if __name__ == "__main__":
    app()
