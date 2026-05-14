"""Проверка docstring/description/example у @service_dsl сервисов.

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

import argparse
import ast
import sys
from collections.abc import Iterable
from pathlib import Path

_MIN_DESCRIPTION_LEN = 20
_EXAMPLE_MARKERS = ("Example::", "Examples::", "Пример::", "Примеры::")


def _has_service_dsl_decorator(node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Возвращает True если у определения есть декоратор @service_dsl.

    Args:
        node: AST-узел класса или функции.

    Returns:
        True при наличии ``service_dsl`` среди декораторов; иначе False.
    """
    for dec in node.decorator_list:
        # @service_dsl  или  @service_dsl(crud=True)
        if isinstance(dec, ast.Name) and dec.id == "service_dsl":
            return True
        if isinstance(dec, ast.Call):
            func = dec.func
            if isinstance(func, ast.Name) and func.id == "service_dsl":
                return True
            if isinstance(func, ast.Attribute) and func.attr == "service_dsl":
                return True
    return False


def _check_docstring(docstring: str | None) -> list[str]:
    """Проверяет качество docstring.

    Args:
        docstring: текст docstring (или None).

    Returns:
        список диагностик; пустой если всё ок.
    """
    issues: list[str] = []
    if not docstring or not docstring.strip():
        issues.append("docstring отсутствует или пустой")
        return issues
    stripped = docstring.strip()
    if stripped.upper().startswith("TODO"):
        issues.append("docstring начинается с TODO — нужно описание")
    first_line = stripped.splitlines()[0].strip()
    if len(first_line) < _MIN_DESCRIPTION_LEN:
        issues.append(
            f"первая строка docstring короче {_MIN_DESCRIPTION_LEN} символов "
            f"(сейчас {len(first_line)})"
        )
    if not any(marker in stripped for marker in _EXAMPLE_MARKERS):
        issues.append(
            "отсутствует секция 'Example::'/'Examples::'/'Пример::'/'Примеры::'"
        )
    return issues


def _iter_service_definitions(
    py_files: Iterable[Path],
) -> Iterable[tuple[Path, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Перебирает все @service_dsl-определения по списку файлов.

    Args:
        py_files: пути к Python-файлам.

    Yields:
        пары (file, node).
    """
    for path in py_files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if _has_service_dsl_decorator(node):
                    yield path, node


def check_target(target: Path) -> int:
    """Запускает проверку для одного target-каталога.

    Args:
        target: путь к каталогу с Python-кодом.

    Returns:
        количество найденных нарушений.
    """
    py_files = list(target.rglob("*.py"))
    violations = 0
    checked = 0
    for path, node in _iter_service_definitions(py_files):
        checked += 1
        docstring = ast.get_docstring(node)
        issues = _check_docstring(docstring)
        if issues:
            violations += 1
            rel = path.relative_to(target.parent) if target.parent in path.parents else path
            name = node.name
            print(f"[FAIL] {rel}::{name}")
            for issue in issues:
                print(f"  - {issue}")
    print(f"\nПроверено @service_dsl-определений: {checked}; нарушений: {violations}")
    return violations


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Проверка docstring @service_dsl")
    parser.add_argument(
        "--target",
        type=Path,
        default=Path("src/backend"),
        help="Путь к коду для анализа",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Strict mode: exit 1 при любом нарушении (default behavior)",
    )
    args = parser.parse_args()

    if not args.target.exists():
        print(f"[ERROR] target '{args.target}' не существует", file=sys.stderr)
        return 1

    violations = check_target(args.target)
    return 0 if violations == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
