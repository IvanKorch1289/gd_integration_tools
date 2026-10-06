"""Генератор манифеста мёртвого кода для gd_integration_tools.

Проверяет каждого кандидата из реестра (tools/deadcode_candidates.json) на
текущем состоянии рабочего дерева и печатает ГОТОВЫЙ К СПИСАНИЮ набор:
модуль, LOC, число импортёров, доказательство «никем не импортируется».

Правила проекта запрещают удалять файлы без явного подтверждения, поэтому
скрипт ничего не удаляет — он только доказывает безопасность кандидата.

Запуск:
    .venv/bin/python tools/deadcode_verify.py            # таблица
    .venv/bin/python tools/deadcode_verify.py --paths    # готовые пути
"""

from __future__ import annotations

import ast
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: Корни, в которых ищем определения модулей.
SRC_ROOTS = ("src", "extensions", "plugins", "routes", "testkit", "tools", "ops")

#: Каталоги, которые сканируются на предмет импортёров.
SCAN_ROOTS = (
    "src",
    "extensions",
    "plugins",
    "routes",
    "testkit",
    "tools",
    "ops",
    "tests",
)


def _iter_python_files() -> list[Path]:
    """Собрать все Python-файлы проекта вне служебных каталогов."""
    out: list[Path] = []
    for root_name in SCAN_ROOTS:
        root = REPO / root_name
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            parts = set(path.parts)
            if parts & {".venv", "venv", "__pycache__", "node_modules", ".git"}:
                continue
            out.append(path)
    return out


def _module_name(path: Path) -> str:
    """Представить путь файла как dotted-имя модуля.

    Args:
        path: Путь к ``.py``-файлу относительно репозитория.

    Returns:
        Dotted-имя модуля либо пустая строка для ``__init__``.

    """
    rel = path.relative_to(REPO)
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imported_names(tree: ast.AST) -> set[str]:
    """Собрать имена модулей, на которые ссылается AST-дерево файла.

    Учитывает и ``import X.Y``, и ``from X.Y import Z``, и относительные
    ``from . import Y`` (последние игнорируются — они внутри одного пакета).

    Args:
        tree: Разобранное AST-дерево модуля.

    Returns:
        Множество dotted-имён импортируемых модулей.

    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # относительный импорт — внутри пакета
                continue
            if node.module:
                names.add(node.module)
                # ``from pkg import sub`` может означать импорт ``pkg.sub``
                for alias in node.names:
                    names.add(f"{node.module}.{alias.name}")
    return names


def build_import_index() -> dict[str, list[str]]:
    """Построить индекс ``модуль -> список файлов-импортёров``.

    Returns:
        Словарь: dotted-имя модуля → импортирующие его файлы (как пути).

    """
    index: dict[str, list[str]] = defaultdict(list)
    for path in _iter_python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError, ValueError:
            continue
        for name in _imported_names(tree):
            index[name].append(str(path.relative_to(REPO)))
    return index


def main(argv: list[str]) -> int:
    """Проверить кандидатов и напечатать вердикт.

    Args:
        argv: Аргументы командной строки; ``--paths`` печатает только пути.

    Returns:
        Код возврата: 0 — успех.

    """
    registry = REPO / "tools" / "deadcode_candidates.json"
    if not registry.is_file():
        print(f"Реестр кандидатов не найден: {registry}")
        print("Создайте его из отчёта аудита мёртвого кода.")
        return 1

    candidates = json.loads(registry.read_text(encoding="utf-8"))
    index = build_import_index()
    all_files = _iter_python_files()

    print(f"Проиндексировано файлов: {len(all_files)}")
    print(f"Модулей в индексе импортов: {len(index)}")
    print()

    def _prod(files: list[str]) -> list[str]:
        """Отбросить тестовых импортёров — они не делают код живым."""
        return sorted({f for f in files if not f.startswith("tests/")})

    def _tests(files: list[str]) -> list[str]:
        """Оставить только тестовые импортёры."""
        return sorted({f for f in files if f.startswith("tests/")})

    rows: list[tuple[str, int, list[str], list[str], str]] = []
    self_path = str(Path(__file__).resolve().relative_to(REPO))
    for item in candidates:
        path = REPO / item["path"]
        if item["path"] == self_path:
            continue  # сам инструмент — не кандидат на удаление
        module = _module_name(path)
        importers = sorted(set(index.get(module, [])) - {item["path"]})
        if module in {"", "__init__"}:
            importers = sorted(
                {
                    imp
                    for name, files in index.items()
                    if name == module or name.startswith(f"{module}.")
                    for imp in files
                }
                - {item["path"]}
            )
        loc = item.get("loc", 0)
        if not path.exists():
            rows.append((item["path"], 0, [], [], "НЕТ ТАКОГО ФАЙЛА (реестр устарел)"))
            continue
        # Теневой sibling: файл ``X.py`` недостижим, если рядом лежит пакет
        # ``X/`` — CPython всегда резолвит имя в пакет. Импорты в коде при
        # этом есть, но попадают в пакет, а не в файл.
        if path.with_suffix("").is_dir():
            # Импорты существуют, но уходят в пакет — показываем честно.
            rows.append(
                (
                    item["path"],
                    loc,
                    _prod(importers),
                    _tests(importers),
                    "ТЕНЕВОЙ (перекрыт пакетом)",
                )
            )
            continue
        prod, tests = _prod(importers), _tests(importers)
        if not prod and tests:
            verdict = "МЁРТВЫЙ В ПРОД (только тесты)"
        elif not prod and not tests:
            verdict = "МЁРТВЫЙ"
        else:
            verdict = "ЖИВОЙ"
        rows.append((item["path"], loc, prod, tests, verdict))

    if "--paths" in argv:
        for path, _loc, _p, _t, verdict in rows:
            if verdict.startswith(("МЁРТВЫЙ", "ТЕНЕВОЙ")):
                print(path)
        return 0

    dead = [r for r in rows if r[4].startswith(("МЁРТВЫЙ", "ТЕНЕВОЙ"))]
    alive = [r for r in rows if r[4] == "ЖИВОЙ"]
    print(f"{'ВЕРДИКТ':32s} {'LOC':>6s}  ПУТЬ")
    print("-" * 104)
    for path, loc, prod, tests, verdict in sorted(rows, key=lambda r: (r[4], -r[1])):
        print(f"{verdict:32s} {loc:6d}  {path}")
        for i in prod:
            print(f"{'':32s} {'':6s}    prod <- {i}")
        for i in tests:
            print(f"{'':32s} {'':6s}    test <- {i}")
    print("-" * 104)
    print(f"Всего кандидатов: {len(rows)}  LOC: {sum(r[1] for r in rows)}")
    print(f"Мёртвых в проде: {len(dead)}  LOC: {sum(r[1] for r in dead)}")
    print(f"Живых (исключены): {len(alive)}  LOC: {sum(r[1] for r in alive)}")
    print()
    print(
        "ВАЖНО (2026-10-06): этот инструмент даёт ЛОЖНЫЕ срабатывания",
        "на автономных CLI-инструментах. Критерий «нет production-импортёров»",
        "неприменим к точкам входа: generate_api_client.py и",
        "classify_object_authorization.py не импортируются, потому что их",
        "запускают как CLI — при этом второй покрыт тестами tests/unit/tools/.",
        "Перед любым выводом проверяйте кандидата вручную (раздел 12",
        "AUDIT_2026-10-06_runtime_wiring.md). Из 3 кандидатов мёртв только 1.",
        sep="\n",
    )
    print()
    print("Оговорка: отсутствие production-импортёров не доказывает неиспользуемость —")
    print("модуль может грузиться рефлексией (importlib, плагины, entry-points,")
    print("реестры по строке). Перед удалением:")
    print("  1. ripgrep по имени модуля без учёта .py;")
    print("  2. полный pytest без этого модуля;")
    print("  3. удалять пачкой по слоям.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
