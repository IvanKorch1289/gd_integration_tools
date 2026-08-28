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


def _parse_thresholds_file(path: Path) -> dict[str, int]:
    """Парсит ``.baselines/coverage_thresholds.txt`` → dict.

    Формат файла (per ADR-0285 §1.2): одна строка на layer — ``layer: N``,
    где N — минимальный coverage в процентах (0-100).
    Строки с ``#`` (комментарии) и пустые строки игнорируются.

    Args:
        path: Путь к thresholds-файлу.

    Returns:
        Dict {layer_name: threshold_percent}. Если файл не существует —
        возвращает пустой dict.
    """
    if not path.exists():
        return {}
    thresholds: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        thresholds[k.strip()] = int(v.strip())
    return thresholds


def _compute_layer_coverage(coverage_xml: Path, layer: str) -> float:
    """Вычисляет coverage для конкретного layer из coverage.xml.

    Суммирует \`line-rate\` атрибуты для всех \`<class>\` элементов,
    чей \`filename\` начинается с \`src/backend/<layer>/\`.

    Args:
        coverage_xml: Путь к coverage.xml (cobertura формат).
        layer: Имя layer (e.g., \"core\", \"infrastructure\", \"dsl\").

    Returns:
        Покрытие layer в процентах (0-100). Если нет данных — 0.0.
    """
    if not coverage_xml.exists():
        return 0.0
    tree = ET.parse(coverage_xml)  # noqa: S314 (наш собственный coverage.xml)
    root = tree.getroot()
    total_lines = 0
    covered_lines = 0
    prefix = f"src/backend/{layer}/"
    for cls in root.iter("class"):
        filename = cls.get("filename", "")
        if not filename.startswith(prefix):
            continue
        for line in cls.iter("line"):
            hits = int(line.get("hits", "0"))
            total_lines += 1
            if hits > 0:
                covered_lines += 1
    if total_lines == 0:
        return 0.0
    return (covered_lines / total_lines) * 100.0


def check_per_layer_thresholds(
    coverage_xml: Path,
    thresholds_file: Path,
) -> int:
    """Проверяет coverage каждого layer против threshold из файла.

    Per ADR-0285 §1.3 (Sprint 40 W1 implementation). Per-layer breakdown
    выводится через rich console. NOT wired to CI (ADR-0285 §2: gradual rollout).

    Args:
        coverage_xml: Путь к coverage.xml (cobertura формат).
        thresholds_file: Путь к ``.baselines/coverage_thresholds.txt``
            (формат: ``layer: N``).

    Returns:
        EXIT_OK (0) если все layers meet threshold, EXIT_THRESHOLD_FAIL (1)
        если хотя бы один layer ниже.
    """
    thresholds = _parse_thresholds_file(thresholds_file)
    if not thresholds:
        console_err.print(f"[red]ERROR: thresholds file not found: {thresholds_file}[/red]")
        return EXIT_ERROR

    console.print(f"Per-layer coverage (ADR-0285 §1.3):")
    failures: list[str] = []
    for layer, threshold in sorted(thresholds.items()):
        current = _compute_layer_coverage(coverage_xml, layer)
        if current >= threshold:
            console.print(f"  [green]✓[/green] {layer}: {current:.1f}% (threshold: {threshold}%)")
        else:
            gap = threshold - current
            console.print(
                f"  [red]✗[/red] {layer}: {current:.1f}% "
                f"(threshold: {threshold}%, below by {gap:.1f}%)"
            )
            failures.append(layer)
    if failures:
        console_err.print(
            f"[bold red]FAIL:[/bold red] {len(failures)} layer(s) below threshold: "
            f"{', '.join(failures)}"
        )
        return EXIT_THRESHOLD_FAIL
    console.print("[bold green]OK[/bold green]: all layers meet threshold")
    return EXIT_OK


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


@app.command("per-layer")
def per_layer(
    coverage_xml: str = typer.Option(
        "coverage.xml", "--coverage-xml", help="Путь к coverage.xml (cobertura формат)."
    ),
    thresholds: str = typer.Option(
        ".baselines/coverage_thresholds.txt",
        "--thresholds",
        help="Путь к thresholds-файлу (ADR-0285 §1.2).",
    ),
) -> None:
    """Per-layer coverage threshold check (ADR-0285 §1.3).

    NOT wired to CI (ADR-0285 §2: gradual rollout). Используйте локально:
    `python tools/check_coverage_gate.py per-layer`.
    """
    rc = check_per_layer_thresholds(Path(coverage_xml), Path(thresholds))
    raise typer.Exit(rc)


if __name__ == "__main__":
    app()
