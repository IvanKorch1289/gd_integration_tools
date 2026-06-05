#!/usr/bin/env python3
"""AST-checker cross-layer imports для extensions/ (V15 GAP capability-gate).

Проверяет статически (через ``ast``), что Python-файлы в extensions НЕ
импортируют напрямую ``src.backend.infrastructure.*`` или
``src.backend.services.*`` — только ``src.backend.core.*`` (включая
``core.interfaces`` и ``core.security.capabilities``).

Контекст (V15 GAP):

* бизнес-логика живёт в ``extensions/<name>/``;
* core — это контракты (Protocol/Interface) + capability-gate;
* infrastructure/services — реализации, к которым extensions должны
  обращаться ТОЛЬКО через capability-checked фасады (R3.10d / ADR-001);
* прямой импорт ``infrastructure/*`` / ``services/*`` из extensions —
  архитектурное нарушение, ловимое этим скриптом.

Поведение::

    python tools/check_layer_imports.py [<directory>]

* ``<directory>`` — корень для обхода ``.py`` файлов (default: ``extensions/``);
* ``--config PATH`` — путь к TOML с override'ом whitelist/blacklist;
* ``if TYPE_CHECKING:`` блоки игнорируются (type-only imports);
* exit code 0 = clean, 1 = есть нарушения, 2 = ошибка запуска.

Override через ``.check_layer_imports.toml`` (опционально)::

    [forbidden]
    prefixes = ["src.backend.infrastructure.", "src.backend.services."]
    [whitelisted]
    prefixes = ["src.backend.core."]

Используется в CI / pre-commit / локально как ``make lint:layer-imports``.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterable
from pathlib import Path

# Дефолтные префиксы (V15 GAP, R3.10d). Override через --config / TOML.
DEFAULT_FORBIDDEN: tuple[str, ...] = (
    "src.backend.infrastructure.",
    "src.backend.services.",
)
DEFAULT_WHITELIST: tuple[str, ...] = ("src.backend.core.",)

# Имя файла с override'ом (если --config не указан ищем его рядом со скриптом).
DEFAULT_CONFIG_NAME = ".check_layer_imports.toml"


def _parse_toml(path: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Читает TOML override. Возвращает (forbidden, whitelist).

    Без зависимости от tomllib/3rd-party: минимальный hand-rolled парсер
    секций ``[forbidden]`` / ``[whitelisted]`` с ключом ``prefixes = [...]``.
    Возвращает исходные DEFAULT_* при ошибке / отсутствии файла.
    """
    if not path.exists():
        return DEFAULT_FORBIDDEN, DEFAULT_WHITELIST
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_FORBIDDEN, DEFAULT_WHITELIST

    forbidden: list[str] = []
    whitelist: list[str] = []
    section: str | None = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        if "=" not in line or section not in {"forbidden", "whitelisted"}:
            continue
        key, value = (p.strip() for p in line.split("=", 1))
        if key != "prefixes":
            continue
        # Принимаем только list-литерал: ["a", "b"]
        if not (value.startswith("[") and value.endswith("]")):
            continue
        items = [p.strip().strip("\"'") for p in value[1:-1].split(",") if p.strip()]
        if section == "forbidden":
            forbidden.extend(items)
        else:
            whitelist.extend(items)
    return tuple(forbidden) or DEFAULT_FORBIDDEN, tuple(whitelist) or DEFAULT_WHITELIST


def _is_in_type_checking(tree: ast.AST, lineno: int) -> bool:
    """True если ``lineno`` находится внутри top-level ``if TYPE_CHECKING:``.

    Поддерживает обе формы:
    * ``if TYPE_CHECKING:`` (после ``from typing import TYPE_CHECKING``);
    * ``if typing.TYPE_CHECKING:`` (полный dotted path).
    """
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if not isinstance(node, ast.If):
            continue
        if not _test_is_type_checking(node.test):
            continue
        end_lineno = node.end_lineno or node.lineno
        if node.lineno <= lineno <= end_lineno:
            return True
    return False


def _test_is_type_checking(test: ast.expr) -> bool:
    """Распознаёт ``TYPE_CHECKING`` в формах Name и Attribute."""
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    if (
        isinstance(test, ast.Attribute)
        and isinstance(test.value, ast.Name)
        and test.value.id == "typing"
        and test.attr == "TYPE_CHECKING"
    ):
        return True
    return False


def _iter_imports(tree: ast.AST) -> Iterable[tuple[str, int]]:
    """Yield (module, lineno) для каждого import / from-import."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                yield node.module, node.lineno


def _scan_file(
    path: Path, forbidden: tuple[str, ...], whitelist: tuple[str, ...]
) -> list[tuple[int, str, str]]:
    """Возвращает список нарушений: (lineno, module, reason)."""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except OSError, SyntaxError:
        return []

    violations: list[tuple[int, str, str]] = []
    for module, lineno in _iter_imports(tree):
        if _is_in_type_checking(tree, lineno):
            continue
        if module.startswith(whitelist):
            continue
        for prefix in forbidden:
            if module.startswith(prefix):
                violations.append((lineno, module, prefix))
                break
    return violations


def _walk_py_files(root: Path) -> Iterable[Path]:
    """Рекурсивно собирает ``.py`` файлы, пропуская ``__pycache__``."""
    for py in root.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        yield py


def main(argv: list[str] | None = None) -> int:
    """CLI entry-point. Возвращает exit code (0/1/2)."""
    parser = argparse.ArgumentParser(
        prog="check_layer_imports",
        description=(
            "AST-checker cross-layer imports в extensions/. "
            "Запрещает прямой импорт src.backend.infrastructure.* и "
            "src.backend.services.* (default)."
        ),
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default="extensions",
        help="корень для обхода .py (default: extensions/)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=f"путь к .toml override (default: ищем {DEFAULT_CONFIG_NAME})",
    )
    args = parser.parse_args(argv)

    root = Path(args.directory)
    if not root.exists():
        print(f"ERROR: directory '{root}' не найден", file=sys.stderr)
        return 2
    if not root.is_dir():
        print(f"ERROR: '{root}' не директория", file=sys.stderr)
        return 2

    config_path = args.config or (Path.cwd() / DEFAULT_CONFIG_NAME)
    forbidden, whitelist = _parse_toml(config_path)

    all_violations: list[tuple[Path, int, str, str]] = []
    files_checked = 0
    for py in _walk_py_files(root):
        files_checked += 1
        for lineno, module, prefix in _scan_file(py, forbidden, whitelist):
            all_violations.append((py, lineno, module, prefix))

    if not all_violations:
        print(f"OK: {files_checked} files clean (forbidden={list(forbidden)})")
        return 0

    print(f"ERROR: {len(all_violations)} forbidden import(s):", file=sys.stderr)
    for py, lineno, module, prefix in sorted(
        all_violations, key=lambda v: (str(v[0]), v[1])
    ):
        rel = py.relative_to(root) if py.is_relative_to(root) else py
        print(
            f"  {rel}:{lineno}: forbidden import {module} (matches '{prefix}')",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
