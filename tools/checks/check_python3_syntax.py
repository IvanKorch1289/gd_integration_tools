"""CI-gate: запрет ``except A, B:`` без скобок (стиль Python 2).

Контекст
--------
Python 3 интерпретирует ``except A, B:`` как ``except (A, B):`` — это **не**
``SyntaxError``, но синтаксис идентичен Python-2-форме ``except A, B`` (где
``B`` был биндингом). Двойственность маскирует ошибки code-review:
читатель не отличает Python-2 «catch + bind» от Python-3 «catch tuple».
PLAN.md V22 §S17 DoD #2 требует, чтобы такой стиль не встречался
в репозитории. Codemod ``tools/codemods/fix_except_clause.py`` исправляет
существующие случаи, а данный AST-gate предотвращает регрессии.

Алгоритм
--------
Обходит ``.py``-файлы под ``--root``, парсит каждый через ``ast.parse``
и ищет ``ast.ExceptHandler`` с типом ``ast.Tuple``, у которого
``col_offset`` указывает на токен после ``except`` (т.е. скобок нет).
Поскольку ``ast`` не сохраняет факт «были ли скобки», используется
сверка исходной строки: если первый non-space символ после
``except`` — это ``(``, то скобки есть; иначе нарушение.

Использование
-------------
::

    python tools/checks/check_python3_syntax.py [--root src/backend] [--json]

Выходные коды:
    0 — нарушений не найдено;
    1 — есть строки в стиле ``except A, B:`` без скобок.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

RULE_EXCEPT_TUPLE_NO_PAREN = "except-tuple-no-paren"


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

# После ``except`` (с возможными whitespace и backslash-переносами)
# первый non-space символ должен быть ``(``. Любой другой → нарушение,
# если AST-тип — ``Tuple``.
_EXCEPT_PAREN_RE = re.compile(r"except\s*\(")


@dataclass(frozen=True, slots=True)
class Violation:
    """Одно нарушение стиля ``except A, B:``.

    Атрибуты:
        file: путь к файлу (как строка для JSON-сериализации);
        line: 1-based номер строки с ``except``;
        rule: идентификатор правила;
        message: человекочитаемое описание + ссылка на codemod.
    """

    file: str
    line: int
    rule: str
    message: str


def _is_python_2_style(source_lines: list[str], handler: ast.ExceptHandler) -> bool:
    """Проверить, есть ли скобки вокруг tuple-эксепшена.

    Возвращает ``True``, если ``handler.type`` — это tuple **без**
    круглых скобок. Используется regex по исходной строке вместо
    проверки AST (``ast`` не различает обёрнутый и не-обёрнутый tuple).
    """
    if not isinstance(handler.type, ast.Tuple):
        return False
    lineno = handler.lineno
    if lineno < 1 or lineno > len(source_lines):
        return False
    line = source_lines[lineno - 1]
    return _EXCEPT_PAREN_RE.search(line) is None


def check_file(path: Path) -> list[Violation]:
    """Распарсить файл и вернуть найденные нарушения."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    source_lines = source.splitlines()
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if _is_python_2_style(source_lines, node):
            violations.append(
                Violation(
                    file=str(path),
                    line=node.lineno,
                    rule=RULE_EXCEPT_TUPLE_NO_PAREN,
                    message=(
                        "except A, B: без скобок (Python-2 стиль); "
                        "оберните в кортеж: except (A, B):. Авто-фикс: "
                        "python -m tools.codemods.fix_except_clause <path>"
                    ),
                )
            )
    return violations


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
        description="AST-gate: запрет except A, B: без скобок (PLAN V22 §S17 DoD #2)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("src/backend"),
        help="Директория или файл для проверки (default: src/backend)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Вывод в JSON вместо человекочитаемого формата",
    )
    args = parser.parse_args(argv)

    all_violations: list[Violation] = []
    for path in iter_python_files(args.root):
        all_violations.extend(check_file(path))

    if args.json:
        payload = [asdict(v) for v in all_violations]
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        for v in all_violations:
            print(f"{v.file}:{v.line}: [{v.rule}] {v.message}")
        if all_violations:
            print(
                f"\n{len(all_violations)} violation(s) found.",
                file=sys.stderr,
            )
        else:
            print("OK: no Python-2 style except clauses.")

    return 1 if all_violations else 0


if __name__ == "__main__":
    sys.exit(main())
