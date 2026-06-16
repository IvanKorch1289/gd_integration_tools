"""S70 W1: tests для services/dsl/builder_service.py dsl imports.

TD-S65-W4 sample refactor — закрепляет стиль consolidated top-level dsl
imports + ``Pipeline`` в TYPE_CHECKING (services ↔ dsl reverse-dep cleanup).

Проверяют:
1. ``test_top_level_dsl_imports`` — ``route_registry`` + ``YAMLStore`` в
   top-level first-party блоке;
2. ``test_type_checking_imports`` — ``Pipeline`` в TYPE_CHECKING (т.к.
   ``from __future__ import annotations`` → hint = string);
3. ``test_no_lazy_imports`` — zero ``from src.backend.dsl`` imports внутри
   функций/методов;
4. ``test_no_duplicate_imports`` — ровно 2 top-level + 1 TYPE_CHECKING
   dsl-импорта (никаких дубликатов).
"""

from __future__ import annotations

import ast
from pathlib import Path

_TARGET_FILE = "src/backend/services/dsl/builder_service.py"
_TOP_LEVEL_DSL_IMPORTS: tuple[str, ...] = (
    "from src.backend.dsl.commands.registry import route_registry",
    "from src.backend.dsl.yaml_store import YAMLStore",
)
_TYPECHECKING_DSL_IMPORT: str = "from src.backend.dsl.engine.pipeline import Pipeline"


def _parse_builder_service() -> ast.Module:
    return ast.parse(Path(_TARGET_FILE).read_text())


def _top_level_import_froms(tree: ast.Module) -> list[ast.ImportFrom]:
    """Список ``ImportFrom`` узлов, которые находятся прямо в ``Module``.

    TYPE_CHECKING-блок тоже входит (т.к. ``if`` сам — child of Module, а
    импорт внутри — child of ``If``); мы различаем их ниже явно.
    """
    result: list[ast.ImportFrom] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            result.append(node)
        elif isinstance(node, ast.If) and (
            isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
        ):
            for child in node.body:
                if isinstance(child, ast.ImportFrom):
                    result.append(child)
    return result


def test_top_level_dsl_imports() -> None:
    """``route_registry`` + ``YAMLStore`` — оба в top-level first-party блоке.

    До S70 W1: было вразброс (включая TYPE_CHECKING-секцию), но
    top-level-блок уже был. Тест закрепляет структуру.
    """
    source = Path(_TARGET_FILE).read_text()
    top_section = "\n".join(source.split("\n")[:30])

    for expected in _TOP_LEVEL_DSL_IMPORTS:
        assert expected in top_section, (
            f"Ожидался top-level dsl import {expected!r}, "
            f"не найден в первых 30 строках. Текущий top-section:\n"
            f"{top_section}"
        )

    # Sanity: ``route_registry`` и ``YAMLStore`` НЕ внутри ``if TYPE_CHECKING``.
    tree = _parse_builder_service()
    for node in tree.body:
        if isinstance(node, ast.If) and (
            isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
        ):
            for child in node.body:
                if isinstance(child, ast.ImportFrom) and child.module:
                    if "src.backend.dsl" in child.module:
                        names = {alias.name for alias in child.names}
                        assert "route_registry" not in names, (
                            "route_registry должен быть в top-level, не в TYPE_CHECKING"
                        )
                        assert "YAMLStore" not in names, (
                            "YAMLStore должен быть в top-level, не в TYPE_CHECKING"
                        )


def test_type_checking_imports() -> None:
    """``Pipeline`` живёт в ``if TYPE_CHECKING`` блоке (type-hint only)."""
    tree = _parse_builder_service()

    typechecking_imports: list[ast.ImportFrom] = []
    for node in tree.body:
        if isinstance(node, ast.If) and (
            isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"
        ):
            for child in node.body:
                if isinstance(child, ast.ImportFrom):
                    typechecking_imports.append(child)

    modules = [n.module for n in typechecking_imports if n.module]
    assert "src.backend.dsl.engine.pipeline" in modules, (
        f"Ожидался TYPE_CHECKING import "
        f"'src.backend.dsl.engine.pipeline', найдено: {modules}"
    )

    # Конкретно — ``Pipeline``, не другой alias.
    pipeline_node = next(
        n for n in typechecking_imports if n.module == "src.backend.dsl.engine.pipeline"
    )
    imported_names = {alias.name for alias in pipeline_node.names}
    assert "Pipeline" in imported_names, (
        f"Ожидался импорт Pipeline из dsl.engine.pipeline, найдено: {imported_names}"
    )


def test_no_lazy_imports() -> None:
    """Zero ``from src.backend.dsl`` imports внутри Function/AsyncFunction.

    Lazy imports ВНУТРИ методов = нарушение стиля (см. TD-S65-W4 + S69 W3
    прецедент для ``entrypoints/graphql/schema.py``).
    """
    tree = _parse_builder_service()
    lazy_imports: list[tuple[int, str]] = []

    def _walk_with_parents(
        node: ast.AST, in_function: bool, parents: tuple[ast.AST, ...]
    ) -> None:
        for child in ast.iter_child_nodes(node):
            new_in_function = in_function or isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)
            )
            if (
                new_in_function
                and isinstance(child, ast.ImportFrom)
                and child.module
                and "src.backend.dsl" in child.module
            ):
                lazy_imports.append((child.lineno, child.module))
            _walk_with_parents(child, new_in_function, parents + (node,))

    for top_node in tree.body:
        _walk_with_parents(top_node, False, ())

    assert lazy_imports == [], (
        f"Найдено {len(lazy_imports)} lazy dsl import(s) внутри функций: "
        f"{lazy_imports}. Должны быть top-level only."
    )


def test_no_duplicate_imports() -> None:
    """Ровно 2 top-level + 1 TYPE_CHECKING dsl-импорта, без дубликатов.

    Считаем и total-count, и top-vs-typecheck split, чтобы регрессия
    (например, второй ``YAMLStore`` import) ловилась явно.
    """
    source = Path(_TARGET_FILE).read_text()
    total = source.count("from src.backend.dsl")
    # 2 top-level (route_registry, YAMLStore) + 1 TYPE_CHECKING (Pipeline) = 3.
    assert total == 3, (
        f"Найдено {total} 'from src.backend.dsl' imports, ожидалось 3. "
        f"Возможен дубликат или новый импорт не по стилю."
    )

    # Top-level (вне TYPE_CHECKING) — ровно 2.
    tree = _parse_builder_service()
    top_level_dsl = 0
    typechecking_dsl = 0
    for node in _top_level_import_froms(tree):
        if node.module and "src.backend.dsl" in node.module:
            # Проверяем, в TYPE_CHECKING ли мы: родитель — If с test=Name(id=TYPE_CHECKING)
            # AST 3.11+: ``get_parent_map`` нет, обходим через body nesting.
            # Здесь: _top_level_import_froms уже даёт нам direct children of
            # Module или children of TYPE_CHECKING-if. Считаем split.
            pass

    # Robust split via line-number range: TYPE_CHECKING import находится ПОСЛЕ
    # ``if TYPE_CHECKING:`` строки. Берём индекс строки TYPE_CHECKING.
    lines = source.split("\n")
    tc_line_idx = next(
        i for i, ln in enumerate(lines) if ln.strip().startswith("if TYPE_CHECKING")
    )
    for ln_no, line in enumerate(lines, start=1):
        if "from src.backend.dsl" in line:
            if ln_no > tc_line_idx + 1:  # +1: сама строка if TYPE_CHECKING:
                typechecking_dsl += 1
            else:
                top_level_dsl += 1

    assert top_level_dsl == 2, (
        f"Top-level dsl imports: {top_level_dsl}, ожидалось 2 "
        f"(route_registry, YAMLStore)"
    )
    assert typechecking_dsl == 1, (
        f"TYPE_CHECKING dsl imports: {typechecking_dsl}, ожидалось 1 (Pipeline)"
    )
