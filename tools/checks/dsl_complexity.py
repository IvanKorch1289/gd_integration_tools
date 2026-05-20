"""DSL complexity budget gate (S10 K3 W2, DSL-1.3).

Анализирует DSL YAML routes и валидирует, что:

* cyclomatic complexity ≤ ``MAX_CYCLOMATIC`` (default 50);
* maximum nesting depth ≤ ``MAX_NESTING`` (default 5);
* steps count ≤ ``MAX_STEPS`` (default 50).

Cyclomatic complexity считается как 1 + число decision points:
``choice/when``, ``try_catch``, ``parallel``, ``saga``, ``policy.*`` —
каждое разветвление увеличивает счётчик на 1.

Запуск:

.. code-block:: bash

    python tools/checks/dsl_complexity.py routes/
    python tools/checks/dsl_complexity.py routes/my_route/main.dsl.yaml --json
    python tools/checks/dsl_complexity.py routes/ --max-cyclomatic 30 --strict
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

__all__ = (
    "MAX_CYCLOMATIC",
    "MAX_NESTING",
    "MAX_STEPS",
    "ComplexityReport",
    "analyze_yaml",
    "main",
)

MAX_CYCLOMATIC = 50
MAX_NESTING = 5
MAX_STEPS = 50

# Шаги/процессоры, открывающие новый branch/scope.
_BRANCHING_KEYS = frozenset(
    {"choice", "when", "try_catch", "parallel", "saga", "loop", "for_each"}
)
# Шаги, открывающие новый уровень вложенности (nesting).
_NESTING_KEYS = frozenset(
    {
        "choice",
        "when",
        "otherwise",
        "try_catch",
        "try",
        "catch",
        "parallel",
        "saga",
        "loop",
        "for_each",
        "branches",
    }
)


@dataclass(slots=True)
class ComplexityReport:
    """Метрики complexity на один файл."""

    path: str
    cyclomatic: int
    nesting: int
    steps: int
    violations: list[str]

    @property
    def ok(self) -> bool:
        return not self.violations


def _count_steps(node: Any) -> int:
    """Считает общее число `steps`/`processors`-элементов."""
    if isinstance(node, dict):
        total = 0
        for key in ("steps", "processors"):
            value = node.get(key)
            if isinstance(value, list):
                total += len(value)
                for item in value:
                    total += _count_steps(item)
        # дополнительно сосчитаем nested в branches/when/etc
        for key, value in node.items():
            if key in _NESTING_KEYS and isinstance(value, (list, dict)):
                total += _count_steps(value)
        return total
    if isinstance(node, list):
        return sum(_count_steps(item) for item in node)
    return 0


def _count_cyclomatic(node: Any) -> int:
    """Считает decision points (branching keys)."""
    score = 0
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _BRANCHING_KEYS:
                # Each branching construct adds at least 1
                score += 1
                # Multi-branch (when[]) добавляет за каждый дополнительный case
                if key == "when" and isinstance(value, list):
                    score += max(0, len(value) - 1)
                if key == "choice" and isinstance(value, dict):
                    cases = value.get("when") or []
                    if isinstance(cases, list):
                        score += max(0, len(cases) - 1)
            score += _count_cyclomatic(value)
    elif isinstance(node, list):
        for item in node:
            score += _count_cyclomatic(item)
    return score


def _max_nesting(node: Any, depth: int = 0) -> int:
    """Считает max nesting depth."""
    if isinstance(node, dict):
        best = depth
        for key, value in node.items():
            new_depth = depth + 1 if key in _NESTING_KEYS else depth
            best = max(best, _max_nesting(value, new_depth))
        return best
    if isinstance(node, list):
        return max((_max_nesting(item, depth) for item in node), default=depth)
    return depth


def analyze_yaml(
    yaml_text: str,
    path: str = "<string>",
    *,
    max_cyclomatic: int = MAX_CYCLOMATIC,
    max_nesting: int = MAX_NESTING,
    max_steps: int = MAX_STEPS,
) -> ComplexityReport:
    """Парсит YAML и считает complexity-метрики."""
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        return ComplexityReport(
            path=path,
            cyclomatic=0,
            nesting=0,
            steps=0,
            violations=[f"yaml-syntax: {exc}"],
        )

    cyclomatic = 1 + _count_cyclomatic(data)
    nesting = _max_nesting(data)
    steps = _count_steps(data)

    violations: list[str] = []
    if cyclomatic > max_cyclomatic:
        violations.append(f"cyclomatic={cyclomatic} > {max_cyclomatic}")
    if nesting > max_nesting:
        violations.append(f"nesting={nesting} > {max_nesting}")
    if steps > max_steps:
        violations.append(f"steps={steps} > {max_steps}")

    return ComplexityReport(
        path=path,
        cyclomatic=cyclomatic,
        nesting=nesting,
        steps=steps,
        violations=violations,
    )


def _iter_yaml_files(paths: list[Path]):
    for p in paths:
        if p.is_dir():
            yield from sorted(list(p.rglob("*.yaml")) + list(p.rglob("*.yml")))
        elif p.is_file() and p.suffix in {".yaml", ".yml"}:
            yield p


def main(argv: list[str] | None = None) -> int:
    """CLI entry-point."""
    parser = argparse.ArgumentParser(description="DSL complexity gate (S10 K3 W2)")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument(
        "--max-cyclomatic", type=int, default=MAX_CYCLOMATIC,
    )
    parser.add_argument("--max-nesting", type=int, default=MAX_NESTING)
    parser.add_argument("--max-steps", type=int, default=MAX_STEPS)
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit code 1 если есть violations",
    )
    args = parser.parse_args(argv)

    reports: list[ComplexityReport] = []
    for yaml_file in _iter_yaml_files(args.paths):
        report = analyze_yaml(
            yaml_file.read_text(encoding="utf-8"),
            path=str(yaml_file),
            max_cyclomatic=args.max_cyclomatic,
            max_nesting=args.max_nesting,
            max_steps=args.max_steps,
        )
        reports.append(report)

    bad = [r for r in reports if not r.ok]

    if args.json:
        print(
            json.dumps(
                {
                    "total": len(reports),
                    "violations": len(bad),
                    "reports": [asdict(r) for r in reports],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        for r in reports:
            mark = "OK" if r.ok else "FAIL"
            print(
                f"[{mark}] {r.path}: cyclomatic={r.cyclomatic} "
                f"nesting={r.nesting} steps={r.steps}"
            )
            for v in r.violations:
                print(f"  - {v}")
        print(
            f"\nTotal: {len(reports)} files, {len(bad)} violations"
        )

    if args.strict and bad:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
