#!/usr/bin/env python3
"""Гейт декоративных capability-деклараций процессоров (Wave 13 Q15).

Класс дефекта
-------------
``@processor(..., capabilities=(...))`` сохраняет capability в
:class:`ProcessorSpec` и публикует её как ``x-gd-capabilities`` в JSON-схеме.
Эти метаданные используются LSP/linter, но сам DSL-движок их не проверяет.
Рабочий runtime-механизм — ``BaseProcessor.required_capability``, который
вызывает ``auth_check``/``check_source_capability``.

Если непустая декоративная capability-declared у процессора не сопровождается
``required_capability``, она создаёт ложное впечатление защиты. Гейт не меняет
поведение процессоров: он делает существующий долг видимым и запрещает его
увеличивать.

Правило
-------
1. AST-скан находит классы с ``@processor(capabilities=(...))``.
2. Непустая capability-декларация без прямого ``required_capability`` (или с
   ``required_capability = None``) считается декоративной.
3. Известный долг перечислен в ``tools/check_decorative_capabilities_allowlist.txt``.
   Только новые нарушения завершают проверку с exit code 1.

Запуск
------
::

    python tools/check_decorative_capabilities.py
    python tools/check_decorative_capabilities.py --ci
    python tools/check_decorative_capabilities.py --update-allowlist
    python tools/check_decorative_capabilities.py --json

Exit codes
----------
    0 — новых декоративных деклараций нет.
    1 — появились новые декоративные декларации.
    2 — ошибка запуска (например, не найден корень сканирования).
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

__all__ = (
    "ALLOWLIST_PATH",
    "DEFAULT_ROOT",
    "DecorativeDeclaration",
    "load_allowlist",
    "main",
    "save_allowlist",
    "scan_tree",
)

_ROOT = Path(__file__).resolve().parents[1]

#: Корень AST-сканирования по умолчанию.
DEFAULT_ROOT = _ROOT / "src"

#: Baseline известного долга.
ALLOWLIST_PATH = _ROOT / "tools" / "check_decorative_capabilities_allowlist.txt"

_DEFAULT_REASON = "S-18 baseline: capability проверяется только в метаданных"


@dataclass(frozen=True, slots=True)
class DecorativeDeclaration:
    """Декоративная capability-декларация процессора.

    Attributes:
        path: Путь Python-файла относительно корня сканирования.
        lineno: Строка ``@processor(...)``.
        class_name: Имя класса-процессора.
        capabilities: Непустой набор capability-литералов.

    """

    path: str
    lineno: int
    class_name: str
    capabilities: tuple[str, ...]

    @property
    def key(self) -> str:
        """Стабильный ключ baseline без номера строки."""
        return f"{self.path}::{self.class_name}"

    def as_dict(self) -> dict[str, object]:
        """Представляет декларацию для JSON-вывода."""
        return {
            "path": self.path,
            "lineno": self.lineno,
            "class_name": self.class_name,
            "capabilities": list(self.capabilities),
            "key": self.key,
        }


def _iter_python_files(root: Path) -> Iterator[Path]:
    """Итерирует по ``*.py`` внутри корня без ``__pycache__``."""
    if root.is_file():
        if root.suffix == ".py":
            yield root
        return
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def _display_path(path: Path, root: Path) -> str:
    """Возвращает стабильный путь относительно родителя корня сканирования."""
    base = root.parent if root.is_dir() else root.parent
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _decorator_name(node: ast.Call) -> str:
    """Извлекает имя вызываемого декоратора."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _processor_aliases(tree: ast.AST) -> set[str]:
    """Возвращает локальные имена для декоратора ``processor``.

    Учитывает alias-импорт из публичного registry, чтобы переименованный
    декоратор не позволял скрыть декоративную capability-декларацию.

    Args:
        tree: Разобранное AST-дерево модуля.

    Returns:
        Множество локальных имён registry-декоратора.

    """
    aliases = {"processor"}
    registry_modules = {
        "src.backend.dsl.registry",
        "src.backend.dsl.registry.processor",
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module not in registry_modules:
            continue
        for alias in node.names:
            if alias.name == "processor":
                aliases.add(alias.asname or alias.name)
    return aliases


def _extract_capabilities(node: ast.AST) -> tuple[str, ...] | None:
    """Извлекает непустой набор capability-литералов из AST-выражения.

    Динамическое выражение считается декларацией и требует явного решения:
    иначе новый декоративный capability можно было бы скрыть за константой.

    Args:
        node: AST-значение аргумента ``capabilities``.

    Returns:
        Кортеж capability-литералов, пустой кортеж для пустой декларации или
        ``None``, если аргумента нет.

    """
    try:
        value = ast.literal_eval(node)
    except ValueError:
        return ("<dynamic>",)
    except TypeError:
        return ("<dynamic>",)
    except SyntaxError:
        return ("<dynamic>",)

    if isinstance(value, (tuple, list)):
        return tuple(str(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted(str(item) for item in value))
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return (str(value),)


def _required_capability_state(class_node: ast.ClassDef) -> bool:
    """Проверяет наличие непустого прямого ``required_capability``.

    Args:
        class_node: Класс-процессор.

    Returns:
        ``True``, если класс задаёт runtime-enforced capability; ``False`` для
        отсутствующего или ``None``-значения.

    """
    enforced = False
    for statement in class_node.body:
        value: ast.expr | None = None
        is_assignment = False
        if isinstance(statement, ast.Assign):
            is_assignment = any(
                isinstance(target, ast.Name) and target.id == "required_capability"
                for target in statement.targets
            )
            value = statement.value
        elif isinstance(statement, ast.AnnAssign):
            is_assignment = (
                isinstance(statement.target, ast.Name)
                and statement.target.id == "required_capability"
            )
            value = statement.value
        if not is_assignment:
            continue
        if value is None or (isinstance(value, ast.Constant) and value.value is None):
            continue
        enforced = True
    return enforced


def _decorative_declarations(
    tree: ast.AST, path: str
) -> Iterator[DecorativeDeclaration]:
    """Извлекает декоративные декларации из одного разобранного модуля."""
    processor_names = _processor_aliases(tree)
    for class_node in (
        node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    ):
        for decorator in class_node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if _decorator_name(decorator) not in processor_names:
                continue
            capabilities_node = next(
                (
                    keyword.value
                    for keyword in decorator.keywords
                    if keyword.arg == "capabilities"
                ),
                None,
            )
            if capabilities_node is None:
                continue
            capabilities = _extract_capabilities(capabilities_node)
            if not capabilities:
                continue
            if _required_capability_state(class_node):
                continue
            yield DecorativeDeclaration(
                path=path,
                lineno=decorator.lineno,
                class_name=class_node.name,
                capabilities=capabilities,
            )


def scan_tree(roots: Iterable[Path]) -> list[DecorativeDeclaration]:
    """Сканирует корни и возвращает декоративные capability-декларации.

    Args:
        roots: Каталоги или отдельные ``*.py``-файлы для сканирования.

    Returns:
        Отсортированный список декоративных деклараций.

    """
    declarations: list[DecorativeDeclaration] = []
    for root in roots:
        for path in _iter_python_files(root):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except OSError:
                continue
            except SyntaxError:
                continue
            declarations.extend(
                _decorative_declarations(tree, _display_path(path, root))
            )
    return sorted(
        declarations,
        key=lambda declaration: (
            declaration.path,
            declaration.lineno,
            declaration.class_name,
        ),
    )


def load_allowlist(path: Path = ALLOWLIST_PATH) -> dict[str, str]:
    """Читает allowlist как ``{ключ: inline-комментарий}``.

    Args:
        path: Путь к allowlist-файлу.

    Returns:
        Словарь ключей и комментариев; отсутствующий файл даёт пустой словарь.

    """
    if not path.exists():
        return {}
    entries: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, _, comment = stripped.partition("#")
        entries[key.strip()] = comment.strip()
    return entries


def save_allowlist(path: Path, declarations: Iterable[DecorativeDeclaration]) -> None:
    """Перегенерирует baseline-файл текущего списка долга.

    Args:
        path: Путь к allowlist-файлу.
        declarations: Декоративные декларации для включения в baseline.

    """
    existing = load_allowlist(path)
    header = (
        "# Baseline декоративных capability-деклараций процессоров (Wave 13 Q15).\n"
        "# Формат: <path>::<ClassName>  # owner=<team> | reason=<note>\n"
        "# Каждая запись — известный долг: capabilities есть в метаданных,\n"
        "# но required_capability не включает runtime capability-gate.\n"
        "# Гейт падает только на НОВЫХ декларациях (не из этого списка).\n"
        "# Обновление: python tools/check_decorative_capabilities.py --update-allowlist\n"
        "\n"
    )
    lines: list[str] = []
    for declaration in sorted(declarations, key=lambda item: item.key):
        comment = existing.get(declaration.key) or (
            f"owner=dsl | reason={_DEFAULT_REASON}"
        )
        lines.append(f"{declaration.key}  # {comment}\n")
    path.write_text(header + "".join(lines), encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    """Собирает CLI-парсер гейта."""
    parser = argparse.ArgumentParser(
        description="Wave 13 Q15 — гейт декоративных capability-деклараций."
    )
    parser.add_argument(
        "--root",
        action="append",
        dest="roots",
        help="Корень сканирования (по умолчанию: src).",
    )
    parser.add_argument(
        "--allowlist", default=str(ALLOWLIST_PATH), help="Путь к allowlist-файлу."
    )
    parser.add_argument(
        "--update-allowlist",
        action="store_true",
        help="Перегенерировать allowlist текущим списком долга.",
    )
    parser.add_argument(
        "--ci", action="store_true", help="Режим CI: exit 1 при новых нарушениях."
    )
    parser.add_argument(
        "--json", action="store_true", help="JSON-вывод для CI-интеграции."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Точка входа гейта.

    Args:
        argv: Аргументы CLI (по умолчанию — ``sys.argv[1:]``).

    Returns:
        0 — новых нарушений нет; 1 — новые нарушения; 2 — ошибка запуска.

    """
    args = _build_parser().parse_args(argv)
    roots = [Path(root) for root in (args.roots or [str(DEFAULT_ROOT)])]
    missing = [root for root in roots if not root.exists()]
    if missing:
        print(
            "[check_decorative_capabilities] корни не найдены: "
            + ", ".join(root.as_posix() for root in missing),
            file=sys.stderr,
        )
        return 2

    declarations = scan_tree(roots)
    allowlist_path = Path(args.allowlist)
    allowlist = load_allowlist(allowlist_path)
    current_keys = {declaration.key for declaration in declarations}
    new_declarations = [
        declaration for declaration in declarations if declaration.key not in allowlist
    ]
    stale = sorted(set(allowlist) - current_keys)

    if args.update_allowlist:
        save_allowlist(allowlist_path, declarations)
        print(f"Allowlist обновлён: {len(declarations)} запис(и/ей) → {allowlist_path}")
        return 0

    if args.json:
        payload = {
            "total_decorative": len(declarations),
            "allowlisted": sorted(current_keys & set(allowlist)),
            "new_violations": [
                declaration.as_dict() for declaration in new_declarations
            ],
            "stale_allowlist": stale,
            "decorative": [declaration.as_dict() for declaration in declarations],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1 if new_declarations else 0

    if new_declarations:
        print(f"НОВЫЕ декоративные capability-декларации: {len(new_declarations)}")
        for declaration in new_declarations:
            capabilities = ", ".join(declaration.capabilities)
            print(
                f"  {declaration.key}  ← {declaration.path}:{declaration.lineno} "
                f"capabilities=({capabilities})"
            )
        print(
            "\nДобавьте работающий required_capability либо внесите известный "
            "долг в baseline:\n"
            "  python tools/check_decorative_capabilities.py --update-allowlist"
        )
        return 1

    if stale:
        print(
            f"СТЕЙЛ записи в allowlist: {len(stale)} "
            "(декларация исправлена — обновите allowlist)"
        )
        for key in stale[:10]:
            print(f"  {key}")
        if len(stale) > 10:
            print(f"  ... и ещё {len(stale) - 10}")

    print(
        f"Декоративные capability-декларации: 0 новых "
        f"(всего в долге: {len(declarations)}; allowlist: {len(allowlist)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
