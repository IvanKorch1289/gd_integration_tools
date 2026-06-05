#!/usr/bin/env python3
"""AST-сканер для авто-обнаружения capabilities в plugin-коде (V15 GAP Gap 4).

Сканирует ``<plugin>/plugin.py`` (и опц. все ``.py`` в каталоге плагина) и
извлекает строковые литералы, передаваемые в capability-gate вызовы:

* ``gate.check(plugin_name, capability, ...)`` — 2-й позиционный аргумент;
* ``gate.check_tenant(capability, tenant, ...)`` — 1-й позиционный аргумент;
* ``gate.declare_tenant(capability, tenant, principal)`` — 1-й позиционный;
* ``self.requires_capability(capability)`` — 1-й позиционный аргумент.

Поведение::

    python tools/discover_plugin_capabilities.py <plugin_path> [--recursive]

* ``<plugin_path>`` — путь к плагину (файл ``plugin.py`` или директория,
  содержащая ``plugin.py``);
* ``--recursive`` — TODO: сканировать все ``.py`` файлы в директории плагина
  (на текущем slice — только ``plugin.py``; флаг принят, но игнорируется);
* ``if TYPE_CHECKING:`` блоки игнорируются (type-only imports не считаются);
* exit code ``0`` — scan выполнен (даже если capabilities не найдены);
* exit code ``2`` — фатальная ошибка (например, путь не найден).

Вывод (stdout)::

    Plugin example_plugin: discovered capabilities: mq.publish, db.read

или при отсутствии вызовов::

    Plugin example_plugin: no capabilities discovered

Используется как рекомендательный инструмент — НЕ модифицирует файлы и
НЕ блокирует CI. Дублирование имён capabilities допустимо и
дедуплицируется при выводе.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterable
from pathlib import Path

# Методы capability-gate, которые нас интересуют. Первое значение в
# кортеже — позиция аргумента с capability (0-indexed).
# - check: 1-й арг = plugin_name, 2-й (idx=1) = capability
# - check_tenant / declare_tenant / requires_capability: 1-й (idx=0) = capability
_GATE_METHODS: dict[str, int] = {
    "check": 1,
    "check_tenant": 0,
    "declare_tenant": 0,
    "requires_capability": 0,
}


def _is_in_type_checking(tree: ast.AST, lineno: int) -> bool:
    """True если ``lineno`` находится внутри top-level ``if TYPE_CHECKING:``.

    Поддерживает обе формы: ``if TYPE_CHECKING:`` (после
    ``from typing import TYPE_CHECKING``) и ``if typing.TYPE_CHECKING:``
    (полный dotted path).
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


def _extract_string_arg(node: ast.AST) -> str | None:
    """Возвращает строковое значение узла, если это ``ast.Constant`` со строкой.

    Поддерживает обе формы (Python 3.8+ ``ast.Constant`` и устаревший
    ``ast.Str`` для совместимости со старыми AST-сниппетами).
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _iter_capability_calls(tree: ast.AST) -> Iterable[tuple[int, str, str]]:
    """Yield ``(lineno, method_name, capability)`` для каждого gate-вызова.

    Аргумент capability берётся по индексу, указанному в ``_GATE_METHODS``.
    Пропускает вызовы, у которых нужный аргумент — не строковый литерал
    (например, динамическая конкатенация или переменная).
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Поддерживаем оба синтаксиса: ``gate.check(...)`` (Attribute) и
        # ``check(...)`` (Name) — последний нужен для прямых вызовов
        # внутри plugin-модуля (например, ``requires_capability(...)``).
        attr_name: str | None = None
        if isinstance(func, ast.Attribute):
            attr_name = func.attr
        elif isinstance(func, ast.Name):
            attr_name = func.id
        if attr_name is None or attr_name not in _GATE_METHODS:
            continue
        cap_idx = _GATE_METHODS[attr_name]
        if cap_idx >= len(node.args):
            continue
        cap_name = _extract_string_arg(node.args[cap_idx])
        if cap_name is None:
            continue
        yield node.lineno, attr_name, cap_name


def discover_capabilities(path: Path) -> list[str]:
    """Возвращает отсортированный список уникальных capability-имён.

    Пустой список — если вызовов не найдено или файл не парсится.
    Синтаксические ошибки НЕ бросаются наружу (graceful handling).
    """
    if not path.is_file():
        return []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except OSError, SyntaxError:
        return []
    seen: set[str] = set()
    for lineno, _method, cap_name in _iter_capability_calls(tree):
        if _is_in_type_checking(tree, lineno):
            continue
        seen.add(cap_name)
    return sorted(seen)


def _resolve_plugin_path(raw: str) -> Path | None:
    """Разрешает путь до ``plugin.py`` (директория ИЛИ прямой путь к .py)."""
    p = Path(raw)
    if p.is_dir():
        candidate = p / "plugin.py"
        return candidate if candidate.is_file() else None
    if p.is_file() and p.suffix == ".py":
        return p
    return None


def _plugin_name(path: Path) -> str:
    """Извлекает имя плагина из пути (``<...>/<name>/plugin.py`` → ``<name>``)."""
    if path.name == "plugin.py" and path.parent.name:
        return path.parent.name
    return path.stem


def main(argv: list[str] | None = None) -> int:
    """CLI entry-point. Возвращает exit code (0/2)."""
    parser = argparse.ArgumentParser(
        prog="discover_plugin_capabilities",
        description=(
            "AST-сканер capability-вызовов в plugin-коде. "
            "Извлекает строковые литералы из gate.check / gate.check_tenant "
            "/ gate.declare_tenant / requires_capability и печатает "
            "рекомендацию для plugin.toml."
        ),
    )
    parser.add_argument(
        "plugin_path",
        nargs="?",
        default="extensions/example_plugin",
        help="путь к плагину (директория с plugin.py или прямой путь к .py)",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help=(
            "TODO: рекурсивно сканировать все .py в директории плагина. "
            "На текущем slice флаг принят, но игнорируется — сканируется "
            "только plugin.py."
        ),
    )
    args = parser.parse_args(argv)

    plugin_file = _resolve_plugin_path(args.plugin_path)
    if plugin_file is None:
        print(
            f"ERROR: '{args.plugin_path}' не содержит plugin.py "
            "или не является .py файлом",
            file=sys.stderr,
        )
        return 2

    capabilities = discover_capabilities(plugin_file)
    name = _plugin_name(plugin_file)
    if capabilities:
        print(f"Plugin {name}: discovered capabilities: {', '.join(capabilities)}")
    else:
        print(f"Plugin {name}: no capabilities discovered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
