"""DSL Coverage — проверка покрытия ключевых DSL kind-ов (W11).

Сверяет фактически зарегистрированные процессоры из
``src/dsl/engine/processors/`` с минимально требуемой матрицей kind-ов
из PLAN.md::W11. Выводит компактный отчёт и завершается с exit code 1,
если какой-то обязательный kind отсутствует.

Запуск::

    python tools/dsl_coverage.py [--section <name>]

Секции (по умолчанию — все)::

* ``core``  — обязательные kind-ы W11 PLAN.md
  (``scan_file``, ``audit``, ``auth``, ``notify``,
  ``cedrus_query``, ``get_feedback_examples``);
* ``rpa``   — RPA-процессоры (W28).

Kind-ы могут быть помечены как ``deferred`` — это не считается провалом
покрытия (когда зависимость отнесена к будущему wave).
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSORS_DIR = ROOT / "src" / "dsl" / "engine" / "processors"


@dataclass(slots=True, frozen=True)
class KindSpec:
    """Описание ожидаемого kind-а: имя в DSL → класс-процессор."""

    kind: str
    processor: str
    deferred_reason: str = ""

    @property
    def is_deferred(self) -> bool:
        return bool(self.deferred_reason)


@dataclass(slots=True)
class CoverageReport:
    section: str
    expected: list[KindSpec]
    found_processors: set[str] = field(default_factory=set)

    def matched(self) -> list[KindSpec]:
        return [
            spec
            for spec in self.expected
            if not spec.is_deferred and spec.processor in self.found_processors
        ]

    def missing(self) -> list[KindSpec]:
        return [
            spec
            for spec in self.expected
            if not spec.is_deferred and spec.processor not in self.found_processors
        ]

    def deferred(self) -> list[KindSpec]:
        return [spec for spec in self.expected if spec.is_deferred]

    def total_active(self) -> int:
        return sum(1 for spec in self.expected if not spec.is_deferred)


# ──────────────────── Manifest ────────────────────

# Минимально требуемая матрица из PLAN.md::W11. Расширять при добавлении
# ключевых kind-ов в новых wave.
_W11_CORE: list[KindSpec] = [
    KindSpec("scan_file", "ScanFileProcessor"),
    KindSpec("audit", "AuditProcessor"),
    KindSpec("auth", "AuthValidateProcessor"),
    KindSpec("notify", "NotifyProcessor"),
    KindSpec(
        "cedrus_query",
        "CedrusQueryProcessor",
        deferred_reason=(
            "Cedrus-коннектор не реализован (отнесён к W10). "
            "Kind будет зарегистрирован после появления коннектора."
        ),
    ),
    KindSpec("get_feedback_examples", "GetFeedbackExamplesProcessor"),
]

_SECTIONS: dict[str, list[KindSpec]] = {
    "core": _W11_CORE,
}


# ──────────────────── Discovery ────────────────────


def _iter_processor_class_names(directory: Path) -> set[str]:
    """Возвращает имена всех классов-процессоров в каталоге.

    Учитываются файлы ``*.py`` рекурсивно. Принадлежность к процессорам
    определяется по суффиксу ``Processor`` в имени класса (стабильный
    конвенциональный признак в проекте).
    """
    names: set[str] = set()
    for path in directory.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name.endswith("Processor"):
                names.add(node.name)
    return names


# ──────────────────── Reporting ────────────────────


def _format_section(report: CoverageReport) -> str:
    lines: list[str] = []
    lines.append(f"## section: {report.section}")
    matched = report.matched()
    missing = report.missing()
    deferred = report.deferred()
    total = report.total_active()
    coverage = (len(matched) / total * 100.0) if total else 100.0
    lines.append(
        f"  active kinds: {len(matched)}/{total} ({coverage:.1f}%)"
        + (f"  +{len(deferred)} deferred" if deferred else "")
    )
    if matched:
        for spec in matched:
            lines.append(f"  [ok]       {spec.kind:<28}  → {spec.processor}")
    if missing:
        for spec in missing:
            lines.append(f"  [MISSING]  {spec.kind:<28}  → {spec.processor}")
    if deferred:
        for spec in deferred:
            lines.append(
                f"  [deferred] {spec.kind:<28}  → {spec.processor}"
                f"   ({spec.deferred_reason})"
            )
    return "\n".join(lines)


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--section",
        choices=sorted(_SECTIONS),
        help="Проверить только указанную секцию (по умолчанию — все).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)

    found = _iter_processor_class_names(PROCESSORS_DIR)
    print(f"Discovered {len(found)} processor classes in {PROCESSORS_DIR.relative_to(ROOT)}")
    print()

    sections = (
        [args.section] if args.section else list(_SECTIONS)
    )

    has_missing = False
    for section in sections:
        report = CoverageReport(
            section=section,
            expected=list(_SECTIONS[section]),
            found_processors=found,
        )
        print(_format_section(report))
        print()
        if report.missing():
            has_missing = True

    if has_missing:
        print("FAIL: есть незакрытые активные kind-ы.")
        return 1
    print("OK: все активные kind-ы покрыты.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
