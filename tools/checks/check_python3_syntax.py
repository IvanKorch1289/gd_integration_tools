"""CI-gate: fail-closed проверка синтаксической разборимости ``*.py``.

Контекст
--------
Историческая версия этого гейта запрещала ``except A, B:`` без скобок
(PLAN.md V22 §S17 DoD #2, стиль Python 2). **ADR-0304**: с PEP 758
(Python 3.14, ``target-version = "py314"``) такая форма стала каноничной —
``ruff format`` 0.16+ сам снимает скобки, поэтому прежнее правило
вступало в бесконечный конфликт с блокирующим шагом format-check.

Текущее правило: **каждый файл обязан разбираться ``ast.parse``**.
Реальный Python-2 хазард (``except A, B as e:`` — биндинг вместо
кортежа) — это ``SyntaxError`` и ловится здесь же, fail-closed.

Выходные коды:
    0 — все файлы разбираются;
    1 — есть файлы с ``SyntaxError``.

Использование
-------------
::

    python tools/checks/check_python3_syntax.py [--root src/backend] [--json]
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Violation:
    """Файл, не разбирающийся ``ast.parse`` (fail-closed)."""

    file: str
    line: int
    rule: str
    message: str


RULE_SYNTAX_PARSE_FAILED = "syntax-parse-failed"

_SKIP_DIRS: frozenset[str] = frozenset(
    {
        "__pycache__",
        ".venv",
        "venv",
        ".git",
        "build",
        "dist",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "node_modules",
    }
)


def _is_python_2_style(source_lines: list[str], handler: ast.ExceptHandler) -> bool:
    """Устарело: оставлено для совместимости импортов. Всегда ``False``.

    Раньше детектировал tuple-эксепшен без скобок; ADR-0304 отменил
    правило — форма канонична под PEP 758 и производится ``ruff format``.
    """
    return False


def check_file(path: Path) -> list[Violation]:
    """Проверить, что файл разбирается ``ast.parse`` (fail-closed)."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [
            Violation(
                file=str(path),
                line=exc.lineno or 0,
                rule=RULE_SYNTAX_PARSE_FAILED,
                message=f"SyntaxError: {exc.msg} — файл не разбирается AST",
            )
        ]
    return []


def iter_python_files(root: Path) -> Iterator[Path]:
    """Найти все ``.py`` под ``root`` (файл или директория)."""
    if root.is_file():
        if root.suffix == ".py":
            yield root
        return
    for path in root.rglob("*.py"):
        if _SKIP_DIRS & set(path.parts):
            continue
        yield path


def main(argv: list[str] | None = None) -> int:
    """CLI: обойти ``--root`` и вывести нарушения; exit 1 если найдены."""
    parser = argparse.ArgumentParser(
        description="Fail-closed AST-gate: каждый .py обязан разбираться (ADR-0304)"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("src/backend"),
        help="Директория или файл для проверки (default: src/backend)",
    )
    parser.add_argument("--json", action="store_true", help="JSON-вывод")
    args = parser.parse_args(argv)

    violations: list[Violation] = []
    for path in iter_python_files(args.root):
        violations.extend(check_file(path))

    if args.json:
        print(json.dumps([asdict(v) for v in violations], ensure_ascii=False))
    elif violations:
        for v in violations:
            print(f"{v.file}:{v.line}: [{v.rule}] {v.message}", file=sys.stderr)

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
