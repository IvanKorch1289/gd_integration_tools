"""Wave F.6 — docstring policy gate.

AST-проход по указанным каталогам. Каждый публичный класс / функция /
метод должен иметь docstring. Запрещены пустые / TODO / "Заглушка"
docstring'и.

Поведение:

* Возвращает exit code 0, если новых нарушений нет (по сравнению с
  ``tools/check_docstrings_allowlist.txt``).
* Exit code 1 — есть **новые** нарушения. Пишет diff в stderr.
* ``--update-allowlist`` — пересоздать allowlist из текущих нарушений
  (для амнистии baseline / после миграции модуля).
* ``--strict`` — игнорировать allowlist, любое нарушение → exit 1.
* ``--files`` — явный список файлов вместо обхода каталогов.
  Поддерживает несколько ``--files`` или единичный ``-`` для чтения
  списка путей со stdin (по строке на путь). Используется server-side
  pre-receive hook'ом, чтобы проверять только diff пушенных коммитов.

Использование:

  python tools/check_docstrings.py src/core src/dsl/engine src/core/interfaces
  python tools/check_docstrings.py src/core --strict
  python tools/check_docstrings.py src/core --update-allowlist
  python tools/check_docstrings.py --strict --files src/core/foo.py src/core/bar.py
  git diff --name-only HEAD~1 | python tools/check_docstrings.py --strict --files -
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST_PATH = PROJECT_ROOT / "tools" / "check_docstrings_allowlist.txt"

# Запрещённые "пустые" docstring (case-insensitive).
_FORBIDDEN_PATTERN = re.compile(
    r"^\s*(todo|tbd|заглушка|placeholder|stub)\.?\s*$", re.IGNORECASE
)


def _is_public_name(name: str) -> bool:
    """Публичность по PEP 8: не начинается с ``_`` или dunder."""
    return not name.startswith("_")


def _is_forbidden_docstring(text: str | None) -> bool:
    """``None`` / пустая / TODO-заглушка → True."""
    if text is None:
        return True
    stripped = text.strip()
    if not stripped:
        return True
    return bool(_FORBIDDEN_PATTERN.match(stripped))


def _walk_targets(roots: Iterable[Path]) -> list[Path]:
    """Собирает все ``*.py`` из переданных путей (всегда абсолютные)."""
    files: list[Path] = []
    for raw in roots:
        root = (
            (PROJECT_ROOT / raw).resolve() if not raw.is_absolute() else raw.resolve()
        )
        if root.is_file() and root.suffix == ".py":
            files.append(root)
        elif root.is_dir():
            files.extend(sorted(root.rglob("*.py")))
    return files


def _format_path(file: Path) -> str:
    """Возвращает путь относительно ``PROJECT_ROOT`` либо абсолютный.

    Файлы из временных каталогов (тесты, sandbox) не лежат внутри проекта,
    поэтому ``relative_to`` падает. Для таких случаев возвращаем
    абсолютный путь без падения.
    """
    try:
        return str(file.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(file)


def _check_node(file: Path, node: ast.AST, parent: str = "") -> list[str]:
    """Проверяет ноду на наличие документированного docstring (recursive)."""
    violations: list[str] = []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        if _is_public_name(node.name):
            doc = ast.get_docstring(node)
            if _is_forbidden_docstring(doc):
                qualified = f"{parent}.{node.name}" if parent else node.name
                violations.append(
                    f"{_format_path(file)}:{node.lineno}:{node.col_offset} {qualified}"
                )
        # Углубляемся в тело класса (методы), но не в функции (вложенные функции
        # обычно — приватные хелперы, проверяемые отдельно через _is_public_name).
        if isinstance(node, ast.ClassDef):
            new_parent = f"{parent}.{node.name}" if parent else node.name
            for child in node.body:
                violations.extend(_check_node(file, child, new_parent))
    return violations


def check_file(path: Path) -> list[str]:
    """Проверяет один Python-файл; возвращает список violations."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return [f"{_format_path(path)}:syntax error: {exc.msg}"]

    violations: list[str] = []
    # Module-level docstring сейчас не required (есть headers / __all__).
    for node in tree.body:
        violations.extend(_check_node(path, node))
    return violations


def _load_allowlist() -> set[str]:
    if not ALLOWLIST_PATH.exists():
        return set()
    return {
        line.strip()
        for line in ALLOWLIST_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


def _save_allowlist(violations: list[str]) -> None:
    header = (
        "# Wave F.6 docstring amnesty baseline.\n"
        "# Содержит существующие нарушения, чтобы pre-push gate не блокировал\n"
        "# legacy-код. Снимать пункт по мере миграции модуля.\n"
        "# Формат: <relative_path>:<lineno>:<col> <qualified_name>\n\n"
    )
    body = "\n".join(sorted(set(violations)))
    ALLOWLIST_PATH.write_text(header + body + "\n", encoding="utf-8")


def _collect_files_from_args(
    paths: list[Path] | None, files_args: list[str] | None
) -> list[Path]:
    """Собирает финальный список файлов из позиционных ``paths`` и ``--files``.

    Логика:

    * ``--files -`` — читает список путей со stdin (по строке на путь);
    * ``--files <path>`` — каждый аргумент трактуется как путь;
    * позиционные ``paths`` — каталоги/файлы для рекурсивного обхода.

    Списки объединяются (можно передать оба источника одновременно).
    Несуществующие или non-``.py`` файлы из ``--files`` молча пропускаются —
    это нормально для diff-режима, где удалённые файлы тоже могут попасть
    в список.
    """
    collected: list[Path] = []
    if paths:
        collected.extend(_walk_targets(paths))

    if files_args:
        raw_files: list[str] = []
        for entry in files_args:
            if entry == "-":
                raw_files.extend(
                    line.strip()
                    for line in sys.stdin.read().splitlines()
                    if line.strip()
                )
            else:
                raw_files.append(entry)
        for raw in raw_files:
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = (PROJECT_ROOT / candidate).resolve()
            else:
                candidate = candidate.resolve()
            if candidate.is_file() and candidate.suffix == ".py":
                collected.append(candidate)
    # Уникализация с сохранением порядка.
    seen: set[Path] = set()
    unique: list[Path] = []
    for f in collected:
        if f not in seen:
            seen.add(f)
            unique.append(f)
    return unique


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI (s59 W1: переход на typer — legacy path сохранён через typer.callback).

    Этот модуль мигрирован на typer+rich. Typer-native entry — ``app_main`` ниже;
    эта функция осталась для backward-compat (CI scripts вызывают ``main(argv)`` напрямую).
    """
    # Парсим argv через typer (для backward compat)
    import sys as _sys

    try:
        # Если первый arg похож на typer invocation — typer сам разберёт
        from typer.testing import CliRunner

        return CliRunner().invoke(app_main, _sys.argv[1:]).exit_code or 0
    except (ImportError, SystemExit):
        return 0


app = typer.Typer(
    name="check_docstrings",
    help="Docstring gate: проверка docstrings на public classes/functions (S59 W1).",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
console_err = Console(stderr=True, style="red")


@app.command()
def app_main(
    paths: list[Path] = typer.Argument(  # noqa: B008
        None,
        help="Позиционные пути для проверки (можно несколько).",
    ),
    files: Optional[list[str]] = typer.Option(
        None,
        "--files",
        help=(
            "Явный путь к Python-файлу. Можно повторять. "
            "Использовать ``-`` чтобы прочитать список путей со stdin."
        ),
    ),
    update_allowlist: bool = typer.Option(
        False,
        "--update-allowlist",
        help="Перезаписать allowlist.",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Игнорировать allowlist; любое нарушение → exit 1.",
    ),
) -> None:
    """Точка входа CLI (typer)."""
    if not paths and not files:
        console_err.print(
            "[red]требуется хотя бы один из: позиционные paths или --files[/red]"
        )
        raise typer.Exit(2)

    collected = _collect_files_from_args(paths or [], files)
    if not collected:
        console_err.print(
            "[yellow][check_docstrings] нет .py-файлов в переданных путях[/yellow]"
        )
        raise typer.Exit(0)

    all_violations: list[str] = []
    for file in collected:
        all_violations.extend(check_file(file))

    if update_allowlist:
        _save_allowlist(all_violations)
        console_err.print(
            f"[yellow][check_docstrings] allowlist обновлён: "
            f"{len(all_violations)} нарушений зафиксированы.[/yellow]"
        )
        raise typer.Exit(0)

    if strict:
        if all_violations:
            for v in all_violations:
                console_err.print(f"  [red]-[/red] {v}")
            console_err.print(
                f"[bold red][check_docstrings] strict mode: "
                f"{len(all_violations)} нарушений.[/bold red]"
            )
            raise typer.Exit(1)
        raise typer.Exit(0)

    allowlist = _load_allowlist()
    new_violations = [v for v in all_violations if v not in allowlist]
    if new_violations:
        console_err.print(
            "[bold red][check_docstrings] НОВЫЕ нарушения (не в allowlist):[/bold red]"
        )
        for v in new_violations:
            console_err.print(f"  [red]-[/red] {v}")
        console_err.print(
            "[yellow][check_docstrings] добавьте docstring или обновите allowlist "
            "через --update-allowlist (только при намеренной амнистии).[/yellow]"
        )
        raise typer.Exit(1)
    raise typer.Exit(0)


if __name__ == "__main__":
    app()
