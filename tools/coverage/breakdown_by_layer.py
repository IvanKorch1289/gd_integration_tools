"""Per-layer coverage breakdown — Sprint 16 DoD-10.

Парсит cobertura ``coverage.xml`` (создаваемый ``pytest --cov=src
--cov-report=xml``) и печатает разбивку покрытия по архитектурным слоям:

* ``core`` — :mod:`src.backend.core`
* ``dsl`` — :mod:`src.backend.dsl`
* ``infrastructure`` — :mod:`src.backend.infrastructure`
* ``services`` — :mod:`src.backend.services`
* ``entrypoints`` — :mod:`src.backend.entrypoints`
* ``plugins`` — :mod:`src.backend.plugins`
* ``frontend`` — :mod:`src.frontend`
* ``other`` — всё остальное

Использование::

    pytest --cov=src --cov-report=xml
    python tools/coverage/breakdown_by_layer.py coverage.xml

Exit-codes:

* ``0`` — отчёт сгенерирован успешно.
* ``2`` — нет coverage.xml / parse-fail.

Глобальный порог проверяет :mod:`pyproject.toml::[tool.coverage.report]`
``fail_under``; этот скрипт — диагностика "где провисает", не gate.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

EXIT_OK = 0
EXIT_ERROR = 2

_LAYER_ORDER = (
    "core",
    "dsl",
    "infrastructure",
    "services",
    "entrypoints",
    "plugins",
    "frontend",
    "other",
)


@dataclass
class _LayerStats:
    """Накопитель статистики покрытия по слою."""

    files: int = 0
    lines_total: int = 0
    lines_covered: int = 0

    @property
    def percent(self) -> float:
        if self.lines_total == 0:
            return 0.0
        return 100.0 * self.lines_covered / self.lines_total


def _classify(filename: str) -> str:
    """Возвращает имя слоя для cobertura ``<class filename=...>``."""
    norm = filename.replace("\\", "/")
    if norm.startswith("src/backend/core/"):
        return "core"
    if norm.startswith("src/backend/dsl/"):
        return "dsl"
    if norm.startswith("src/backend/infrastructure/"):
        return "infrastructure"
    if norm.startswith("src/backend/services/"):
        return "services"
    if norm.startswith("src/backend/entrypoints/"):
        return "entrypoints"
    if norm.startswith("src/backend/plugins/"):
        return "plugins"
    if norm.startswith("src/frontend/"):
        return "frontend"
    return "other"


def _parse(path: Path) -> dict[str, _LayerStats]:
    """Парсит cobertura XML и собирает stats по слоям."""
    tree = ET.parse(path)  # noqa: S314  # trusted input: coverage report from our own tool
    root = tree.getroot()
    stats: dict[str, _LayerStats] = {layer: _LayerStats() for layer in _LAYER_ORDER}

    for cls in root.iter("class"):
        filename = cls.get("filename", "")
        if not filename:
            continue
        layer = _classify(filename)
        layer_stats = stats[layer]
        layer_stats.files += 1

        lines = cls.find("lines")
        if lines is None:
            continue
        for line in lines.iter("line"):
            layer_stats.lines_total += 1
            hits = int(line.get("hits", "0"))
            if hits > 0:
                layer_stats.lines_covered += 1

    return stats


def _render(stats: dict[str, _LayerStats]) -> str:
    """Форматирует stats в таблицу для stdout."""
    header = f"{'Слой':<16} {'Файлов':>8} {'Строк':>10} {'Покрыто':>10} {'Процент':>10}"
    separator = "-" * len(header)
    rows = [header, separator]

    total = _LayerStats()
    for layer in _LAYER_ORDER:
        s = stats[layer]
        if s.files == 0:
            continue
        rows.append(
            f"{layer:<16} {s.files:>8} {s.lines_total:>10} "
            f"{s.lines_covered:>10} {s.percent:>9.2f}%"
        )
        total.files += s.files
        total.lines_total += s.lines_total
        total.lines_covered += s.lines_covered

    rows.append(separator)
    rows.append(
        f"{'TOTAL':<16} {total.files:>8} {total.lines_total:>10} "
        f"{total.lines_covered:>10} {total.percent:>9.2f}%"
    )
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "xml_path",
        type=Path,
        nargs="?",
        default=Path("coverage.xml"),
        help="Путь к coverage.xml (default: ./coverage.xml)",
    )
    args = parser.parse_args(argv)

    if not args.xml_path.exists():
        sys.stderr.write(f"ERROR: {args.xml_path} не найден\n")
        sys.stderr.write("Запустите: pytest --cov=src --cov-report=xml\n")
        return EXIT_ERROR

    try:
        stats = _parse(args.xml_path)
    except ET.ParseError as exc:
        sys.stderr.write(f"ERROR: parse fail {args.xml_path}: {exc}\n")
        return EXIT_ERROR

    sys.stdout.write(_render(stats) + "\n")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
