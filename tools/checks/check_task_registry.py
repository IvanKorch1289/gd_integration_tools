"""CI-gate ``check_task_registry``: запрет orphan ``asyncio.create_task`` (R-V15-11).

V22 §5 правило ``orphan-create-task``: все фоновые задачи обязаны идти через
:class:`TaskRegistry.create_task` для graceful-shutdown, leak-prevention и
``contextvars`` propagation. Это правило уже встроено в общий
``check_grep_violations.py``; данный инструмент — узкий wrapper с тремя
дополнениями:

* также ловит ``loop.create_task(...)`` и ``asyncio.ensure_future(...)``
  (не только ``asyncio.create_task``);
* выводит сводку по файлам (top-N), удобную для PR-review;
* поддерживает ``--strict`` (exit 1 при первом нарушении) и
  ``--json`` для машинного потребления.

Использование
-------------
::

    python tools/checks/check_task_registry.py [--root src/backend] [--strict] [--json]

Выходные коды
~~~~~~~~~~~~~

* 0 — нарушений нет;
* 1 — найден хотя бы один orphan callsite.

Идеи допустимых исключений
~~~~~~~~~~~~~~~~~~~~~~~~~~

* Тесты (``tests/``) — не сканируются (там нужны прямые ``create_task``).
* Selftest-блоки в ``if __name__ == "__main__":`` — игнорируются.
* Строки с ``# noqa: orphan-create-task`` — пропускаются (для редких
  низкоуровневых ASGI-точек).
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import Counter as _Counter
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

RULE_ORPHAN_TASK = "orphan-create-task"
NOQA_TOKEN = f"# noqa: {RULE_ORPHAN_TASK}"

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
        "tests",
    }
)

# Атрибут-цепочки, считающиеся orphan-создателями task'и.
# Имя цепочки нормализуется через ``_attr_chain``.
_ORPHAN_CALLS: frozenset[str] = frozenset(
    {
        "asyncio.create_task",
        "asyncio.ensure_future",
        "loop.create_task",
        "loop.ensure_future",
    }
)


@dataclass(frozen=True, slots=True)
class Violation:
    """Одно orphan-task нарушение.

    Атрибуты:
        file: путь к исходному файлу (строка для JSON).
        line: 1-based номер строки с вызовом.
        rule: ``orphan-create-task``.
        call: фактически найденная цепочка (``asyncio.create_task`` и т.д.).
        message: рекомендация миграции.
    """

    file: str
    line: int
    rule: str
    call: str
    message: str


def _attr_chain(node: ast.AST) -> str | None:
    """Свернуть ``Attribute``-цепочку в строку ``a.b.c``.

    Возвращает ``None``, если выражение не сводится к chain имён.
    """
    parts: list[str] = []
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def _is_noqa(source_lines: list[str], lineno: int) -> bool:
    """Проверить inline-noqa маркер для этой строки."""
    if 0 < lineno <= len(source_lines):
        return NOQA_TOKEN in source_lines[lineno - 1]
    return False


def _selftest_ranges(tree: ast.AST) -> list[tuple[int, int]]:
    """Собрать диапазоны строк ``if __name__ == "__main__":`` и ``_selftest``."""
    ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in {"_selftest", "selftest", "_self_test"}:
                ranges.append((node.lineno, node.end_lineno or node.lineno))
        elif isinstance(node, ast.If):
            test = node.test
            if (
                isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name)
                and test.left.id == "__name__"
                and len(test.ops) == 1
                and isinstance(test.ops[0], ast.Eq)
                and isinstance(test.comparators[0], ast.Constant)
                and test.comparators[0].value == "__main__"
            ):
                ranges.append((node.lineno, node.end_lineno or node.lineno))
    return ranges


def _is_in_ranges(lineno: int, ranges: list[tuple[int, int]]) -> bool:
    """Попадает ли строка в один из selftest-диапазонов."""
    return any(start <= lineno <= end for start, end in ranges)


def check_file(path: Path) -> list[Violation]:
    """Найти orphan ``create_task``/``ensure_future`` callsites в файле."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    source_lines = source.splitlines()
    ranges = _selftest_ranges(tree)
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        chain = _attr_chain(node.func)
        if chain not in _ORPHAN_CALLS:
            continue
        if _is_in_ranges(node.lineno, ranges):
            continue
        if _is_noqa(source_lines, node.lineno):
            continue
        violations.append(
            Violation(
                file=str(path),
                line=node.lineno,
                rule=RULE_ORPHAN_TASK,
                call=chain,
                message=(
                    f"{chain}(...) вне TaskRegistry — мигрируйте на "
                    "get_task_registry().create_task(coro, name=...) "
                    "(R-V15-11). Для редких ASGI-точек: "
                    f"# noqa: {RULE_ORPHAN_TASK}"
                ),
            )
        )
    return violations


def iter_python_files(root: Path) -> Iterator[Path]:
    """Найти все ``.py`` файлы под ``root``, пропуская служебные директории."""
    if root.is_file():
        if root.suffix == ".py":
            yield root
        return
    for path in root.rglob("*.py"):
        if _SKIP_DIRS & set(path.parts):
            continue
        yield path


def main(argv: list[str] | None = None) -> int:
    """CLI: обойти ``--root`` и вывести нарушения; exit 1 при наличии."""
    parser = argparse.ArgumentParser(
        description=(
            "CI-gate: запрет orphan asyncio.create_task / ensure_future "
            "(R-V15-11)"
        ),
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
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 после первого найденного нарушения (для pre-push hook)",
    )
    args = parser.parse_args(argv)

    all_violations: list[Violation] = []
    for path in iter_python_files(args.root):
        violations = check_file(path)
        if args.strict and violations:
            all_violations.extend(violations)
            break
        all_violations.extend(violations)

    if args.json:
        print(
            json.dumps(
                [asdict(v) for v in all_violations], indent=2, ensure_ascii=False
            )
        )
    else:
        for v in all_violations:
            print(f"{v.file}:{v.line}: [{v.rule}] {v.message}")
        if all_violations:
            top = _Counter(v.file for v in all_violations).most_common(5)
            print("\nTop файлов с orphan-tasks:", file=sys.stderr)
            for file_path, count in top:
                print(f"  {count:3d}  {file_path}", file=sys.stderr)
            print(
                f"\n{len(all_violations)} orphan-create-task violation(s) found.",
                file=sys.stderr,
            )
        else:
            print("OK: no orphan asyncio.create_task / ensure_future calls.")

    return 1 if all_violations else 0


if __name__ == "__main__":
    sys.exit(main())
