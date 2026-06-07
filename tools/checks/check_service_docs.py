"""Проверка docstring/description/example у @service_dsl сервисов.

S59 W1 (libraries > custom, v22 п.5): мигрирован с ``argparse`` на
``typer`` + ``rich``.

Назначение:
    CI gate для Sprint 6 K2 wave [s6/k2-service-doc-gate]. Проверяет,
    что каждый класс, помеченный декоратором ``@service_dsl(...)``,
    имеет:
        1. полноценный docstring (не пустой, не TODO);
        2. описание в первой строке (>=20 символов);
        3. секцию ``Example::`` или ``Examples::`` (или
           ``Пример::``/``Примеры::``) в docstring.

    Без этого AsyncAPI/Sphinx-autodoc/Schema Registry UI не получают
    осмысленные описания endpoint'ов, что нарушает Sprint 6 DoD
    «CI docs-gate зелёный».

Использование:
    python tools/checks/check_service_docs.py
    python tools/checks/check_service_docs.py --target src/backend/services
    python tools/checks/check_service_docs.py --strict

feature_flag: service_doc_gate_enabled (default-OFF).

Возвращает exit 0 если все @service_dsl документированы, exit 1 иначе.
"""
from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

import typer
from rich.console import Console

_MIN_DESCRIPTION_LEN = 20
_EXAMPLE_MARKERS = ("Example::", "Examples::", "Пример::", "Примеры::")


def _has_service_dsl_decorator(
    node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    """Возвращает True если у определения есть декоратор @service_dsl.

    Args:
        node: AST-узел класса или функции.

    Returns:
        True при наличии ``service_dsl`` среди декораторов; иначе False.
    """
    for dec in node.decorator_list:
        # Pattern: ``@service_dsl(...)``, ``@service_dsl`` (call or bare name)
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
            if dec.func.id == "service_dsl":
                return True
        if isinstance(dec, ast.Name) and dec.id == "service_dsl":
            return True
    return False


def _iter_documented(node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> Iterable[str]:
    """Yield docstring lines of the AST node if non-empty.

    Args:
        node: AST-узел класса/функции.

    Yields:
        Docstring lines, или ничего если docstring пуст.
    """
    if not (
        node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    ):
        return
    docstring = node.body[0].value.value
    if not docstring.strip():
        return
    yield from docstring.splitlines()


def _check_docstring(node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Проверяет docstring определения; возвращает список issues."""
    issues: list[str] = []
    docstring_lines = list(_iter_documented(node))
    if not docstring_lines:
        return [
            f"{node.name}: отсутствует docstring (требуется для @service_dsl)."
        ]

    first_line = docstring_lines[0].strip()
    if len(first_line) < _MIN_DESCRIPTION_LEN:
        issues.append(
            f"{node.name}: первая строка docstring слишком короткая "
            f"({len(first_line)} < {_MIN_DESCRIPTION_LEN} символов): "
            f"{first_line!r}"
        )
    if "TODO" in first_line:
        issues.append(f"{node.name}: первая строка содержит TODO.")
    if not any(marker in "\n".join(docstring_lines) for marker in _EXAMPLE_MARKERS):
        issues.append(
            f"{node.name}: docstring не содержит секцию "
            f"{' / '.join(_EXAMPLE_MARKERS)} (обязательно для AsyncAPI)."
        )
    return issues


def check_target(target: Path) -> int:
    """Сканирует ``target`` на нарушения docstring @service_dsl.

    Returns:
        Количество нарушений (0 = OK).
    """
    if not target.exists():
        console_err.print(f"[red][ERROR] target '{target}' не существует[/red]")
        return -1

    violations = 0
    checked = 0
    for py_file in target.rglob("*.py"):
        try:
            source = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            if not _has_service_dsl_decorator(node):
                continue
            checked += 1
            for issue in _check_docstring(node):
                console_err.print(f"  [red]-[/red] {issue}")
                violations += 1
    console.print(
        f"\n[bold]Проверено @service_dsl-определений: {checked}; "
        f"нарушений: {violations}[/bold]"
    )
    return violations


app = typer.Typer(
    name="check_service_docs",
    help="Проверка docstring/description/example у @service_dsl сервисов.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
console_err = Console(stderr=True, style="red")


@app.command()
def main(
    target: Path = typer.Option(
        Path("src/backend"),
        "--target",
        help="Путь к коду для анализа",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Strict mode: exit 1 при любом нарушении (default behavior)",
    ),
) -> None:
    """CLI entry point (typer)."""
    violations = check_target(target)
    if violations < 0:
        raise typer.Exit(1)
    raise typer.Exit(0 if violations == 0 else 1)


if __name__ == "__main__":
    app()
