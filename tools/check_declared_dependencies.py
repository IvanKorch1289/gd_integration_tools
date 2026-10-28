#!/usr/bin/env python3
"""Гейт: third-party импорты объявлены в ``pyproject.toml`` (Wave 13 Q8).

Зачем
----
Класс дефекта «висячая зависимость»: модуль импортируется в коде, но его
дистрибутив не объявлен ни в ``[project].dependencies``, ни в одном из
``[project.optional-dependencies]``. Итог — ``ModuleNotFoundError`` в
рантайме (когда пакет не установлен) либо «висячий» mypy-override.

Живой пример (Wave 13 Q8): ``clickhouse_connect`` использовался в 6 местах
``src/``, но не был объявлен нигде — только как mypy-override.

Что делает гейт
---------------
1. AST-скан статических импортов (``import`` / ``from ... import ...``) в
   ``src/`` и ``tests/``. Динамические ``importlib.import_module(...)`` не
   детектируются — гейт работает по синтаксису, а не по поведению в рантайме.
2. Сравнение с объявленными дистрибутивами: ``[project].dependencies`` +
   все секции ``[project.optional-dependencies]``.
3. Необъявленные пакеты → нарушение. Текущий долг зафиксирован в
   ``tools/check_declared_dependencies_allowlist.txt``; гейт падает только
   на **новых** пакетах.

Результат детерминирован: зависит только от содержимого репозитория и
``pyproject.toml`` — установленное окружение на результат не влияет. Если
имя модуля отличается от имени дистрибутива в PyPI (``yaml`` → ``pyyaml``,
``grpc`` → ``grpcio``), соответствие задаётся вручную в
:data:`IMPORT_NAME_TO_DISTRIBUTION`.

Запуск
------
::

    python tools/check_declared_dependencies.py
    python tools/check_declared_dependencies.py --update-allowlist
    python tools/check_declared_dependencies.py --json

Exit codes
----------
    0 — новых необъявленных пакетов нет.
    1 — появились новые необъявленные пакеты.
    2 — ошибка запуска (нет / битый ``pyproject.toml``).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

__all__ = (
    "ALLOWLIST_PATH",
    "DEFAULT_PYPROJECT",
    "DEFAULT_ROOTS",
    "FIRST_PARTY_ROOTS",
    "IMPORT_NAME_TO_DISTRIBUTION",
    "ImportSite",
    "UndeclaredPackage",
    "declared_distributions",
    "load_allowlist",
    "main",
    "normalize_distribution",
    "save_allowlist",
    "scan_tree",
)

_ROOT = Path(__file__).resolve().parents[1]

#: Корни, которые сканируются по умолчанию.
DEFAULT_ROOTS: tuple[str, ...] = ("src", "tests")

#: Манифест с объявленными зависимостями.
DEFAULT_PYPROJECT = _ROOT / "pyproject.toml"

#: Baseline известного долга (необъявленные, но уже известные пакеты).
ALLOWLIST_PATH = _ROOT / "tools" / "check_declared_dependencies_allowlist.txt"

#: Корни first-party модулей проекта (не third-party пакеты).
FIRST_PARTY_ROOTS: frozenset[str] = frozenset(
    {
        "app",
        "conftest",
        "extensions",
        "manage",
        "migrations",
        "ops",
        "plugins",
        "routes",
        "scripts",
        "src",
        "testkit",
        "tests",
        "tools",
    }
)

#: Import name → distribution name для случаев, когда имя модуля и имя
#: дистрибутива в PyPI различаются. Нужен для детерминизма гейта: без него
#: ``import yaml`` выглядел бы как необъявленный пакет, хотя ``pyyaml``
#: объявлен. Обновляется вместе с ``[project.dependencies]``.
IMPORT_NAME_TO_DISTRIBUTION: dict[str, str] = {
    "PIL": "pillow",
    "argon2": "argon2-cffi",
    "bs4": "beautifulsoup4",
    "bson": "pymongo",
    "docx": "python-docx",
    "dotenv": "python-dotenv",
    "google": "protobuf",
    "grpc": "grpcio",
    "idempotency_header_middleware": "asgi-idempotency-header",
    "nats": "nats-py",
    "onelogin": "python3-saml",
    "opentelemetry": "opentelemetry-api",
    "strawberry": "strawberry-graphql",
    "whoosh": "whoosh-reloaded",
    "yaml": "pyyaml",
}

#: Каталоги репозитория, чьи модули импортируются как top-level
#: (тесты добавляют их в ``sys.path``).
_LOCAL_MODULE_DIRS: tuple[str, ...] = ("tools", "tools/checks")

#: Сгенерированные protobuf-пакеты (импортируются как ``auto.*`` и т. п.).
_GENERATED_PROTO_DIR = "src/backend/entrypoints/grpc/protobuf"


@dataclass(frozen=True)
class ImportSite:
    """Место импорта пакета (файл + строка)."""

    path: str
    lineno: int


@dataclass(frozen=True)
class UndeclaredPackage:
    """Необъявленный пакет и список мест его импорта.

    Attributes:
        name: Import name верхнего уровня (как в коде).
        sites: Места импорта (отсортированы).

    """

    name: str
    sites: tuple[ImportSite, ...]


def normalize_distribution(name: str) -> str:
    """Приводит имя дистрибутива к PEP 503-виду.

    Args:
        name: Имя пакета/дистрибутива в любом регистре и разделителе.

    Returns:
        Нормализованное имя (``clickhouse_connect`` → ``clickhouse-connect``).

    """
    return re.sub(r"[-_.]+", "-", name.strip()).lower()


def _distribution_from_spec(spec: str) -> str:
    """Извлекает имя дистрибутива из PEP 508-спеки.

    Args:
        spec: Спека зависимости (``httpx[http2]>=0.28.0``).

    Returns:
        Нормализованное имя дистрибутива.

    """
    head = re.split(r"[\s\[<>=!;~@]", spec.strip(), maxsplit=1)[0]
    return normalize_distribution(head)


def declared_distributions(pyproject: Path) -> set[str]:
    """Собирает множество объявленных дистрибутивов из ``pyproject.toml``.

    Args:
        pyproject: Путь к манифесту.

    Returns:
        Нормализованные имена дистрибутивов из ``[project].dependencies`` и
        всех ``[project.optional-dependencies]``.

    Raises:
        FileNotFoundError: манифест не найден.
        tomllib.TOMLDecodeError: манифест не разбирается.

    """
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = data.get("project", {})
    names = {
        _distribution_from_spec(spec) for spec in project.get("dependencies", []) or []
    }
    for specs in (project.get("optional-dependencies", {}) or {}).values():
        names.update(_distribution_from_spec(spec) for spec in specs or [])
    return names


def _iter_python_files(root: Path) -> Iterator[Path]:
    """Итерирует по ``*.py`` внутри корня (без ``__pycache__``)."""
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def _imported_roots(tree: ast.AST) -> Iterator[tuple[str, int]]:
    """Извлекает top-level имена импортируемых модулей из AST.

    Relative-импорты (``from . import x``) пропускаются — они всегда
    указывают на модули самого проекта.

    Args:
        tree: Разобранное AST-дерево модуля.

    Yields:
        Кортежи ``(top_level_module, lineno)``.

    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0], node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                continue
            yield node.module.split(".")[0], node.lineno


def _is_first_party(name: str, repo_root: Path) -> bool:
    """Проверяет, что модуль принадлежит репозиторию, а не стороннему пакету.

    Args:
        name: Import name верхнего уровня.
        repo_root: Корень репозитория.

    Returns:
        ``True`` для модулей проекта.

    """
    if name in FIRST_PARTY_ROOTS:
        return True
    if (repo_root / f"{name}.py").is_file():
        return True
    for sub in _LOCAL_MODULE_DIRS:
        if (repo_root / sub / f"{name}.py").is_file():
            return True
        if (repo_root / sub / name).is_dir():
            return True
    if (repo_root / _GENERATED_PROTO_DIR / name).is_dir():
        return True
    return False


def scan_tree(
    roots: list[Path], declared: set[str], *, repo_root: Path = _ROOT
) -> dict[str, UndeclaredPackage]:
    """Сканирует деревья и возвращает необъявленные пакеты.

    Результат детерминирован: зависит только от содержимого репозитория и
    ``pyproject.toml`` (никакой зависимости от установленного окружения).

    Args:
        roots: Корни сканирования (каталоги с ``*.py``).
        declared: Множество объявленных дистрибутивов.
        repo_root: Корень репозитория (для определения first-party модулей).

    Returns:
        Словарь ``import name → UndeclaredPackage``.

    """
    found: dict[str, list[ImportSite]] = {}
    parse_failures: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for path in _iter_python_files(root):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError as exc:
                parse_failures.append(f"{path.as_posix()} ({exc.msg})")
                continue
            rel = path.as_posix()
            for name, lineno in _imported_roots(tree):
                if name in sys.stdlib_module_names:
                    continue
                if _is_first_party(name, repo_root):
                    continue
                if normalize_distribution(name) in declared:
                    continue
                alias = IMPORT_NAME_TO_DISTRIBUTION.get(name)
                if alias is not None and normalize_distribution(alias) in declared:
                    continue
                found.setdefault(name, []).append(ImportSite(path=rel, lineno=lineno))
    if parse_failures:
        print(
            f"[check_declared_dependencies] пропущено {len(parse_failures)} "
            f"файл(ов) с синтаксическими ошибками (первые 5: "
            f"{', '.join(parse_failures[:5])})",
            file=sys.stderr,
        )
    return {
        name: UndeclaredPackage(
            name=name, sites=tuple(sorted(sites, key=lambda s: (s.path, s.lineno)))
        )
        for name, sites in sorted(found.items())
    }


def load_allowlist(path: Path = ALLOWLIST_PATH) -> set[str]:
    """Читает allowlist (baseline известного долга).

    Args:
        path: Путь к allowlist-файлу.

    Returns:
        Множество import name'ов из allowlist.

    """
    return set(_read_allowlist_entries(path))


def _read_allowlist_entries(path: Path) -> dict[str, str]:
    """Читает allowlist как ``{имя: комментарий}``.

    Args:
        path: Путь к allowlist-файлу.

    Returns:
        Словарь ``import name → комментарий`` (комментарий может быть пустым).

    """
    if not path.exists():
        return {}
    entries: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, _, comment = stripped.partition("#")
        entries[name.strip()] = comment.strip()
    return entries


def save_allowlist(path: Path, names: set[str]) -> None:
    """Перегенерирует allowlist-файл, сохраняя комментарии существующих записей.

    Args:
        path: Путь к allowlist-файлу.
        names: Имена необъявленных пакетов.

    """
    existing = _read_allowlist_entries(path)
    header = (
        "# Baseline необъявленных зависимостей (Wave 13 Q8).\n"
        "# Формат: <import_name>  # комментарий\n"
        "# Каждая запись — известный долг манифеста: пакет импортируется в коде,\n"
        "# но не объявлен в [project].dependencies / [project.optional-dependencies].\n"
        "# Гейт падает только на НОВЫХ пакетах (не из этого списка).\n"
        "# Обновление: python tools/check_declared_dependencies.py --update-allowlist\n"
        "\n"
    )
    lines = []
    for name in sorted(names):
        comment = existing.get(name) or "не объявлен в манифесте"
        lines.append(f"{name}  # {comment}\n")
    path.write_text(header + "".join(lines), encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    """Собирает CLI-парсер гейта."""
    parser = argparse.ArgumentParser(
        description="Wave 13 Q8 — гейт объявленных third-party зависимостей."
    )
    parser.add_argument(
        "--root",
        action="append",
        dest="roots",
        help=f"Корень сканирования (по умолчанию: {', '.join(DEFAULT_ROOTS)}).",
    )
    parser.add_argument(
        "--pyproject", default=str(DEFAULT_PYPROJECT), help="Путь к pyproject.toml."
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
        "--json", action="store_true", help="JSON-вывод (для CI-интеграции)."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Точка входа гейта.

    Args:
        argv: Аргументы CLI (по умолчанию — ``sys.argv[1:]``).

    Returns:
        Код возврата: 0 — чисто, 1 — новые нарушения, 2 — ошибка запуска.

    """
    args = _build_parser().parse_args(argv)

    pyproject = Path(args.pyproject)
    if not pyproject.is_file():
        print(
            f"[check_declared_dependencies] pyproject не найден: {pyproject}",
            file=sys.stderr,
        )
        return 2
    try:
        declared = declared_distributions(pyproject)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        print(
            f"[check_declared_dependencies] не удалось прочитать {pyproject}: {exc}",
            file=sys.stderr,
        )
        return 2

    roots = [Path(root) for root in (args.roots or list(DEFAULT_ROOTS))]
    undeclared = scan_tree(roots, declared)
    allowlist_path = Path(args.allowlist)
    allowlist = load_allowlist(allowlist_path)

    if args.update_allowlist:
        save_allowlist(allowlist_path, set(undeclared))
        print(f"Allowlist обновлён: {len(undeclared)} запис(и/ей) → {allowlist_path}")
        return 0

    new_violations = sorted(set(undeclared) - allowlist)
    stale = sorted(allowlist - set(undeclared))

    if args.json:
        payload = {
            "roots": [root.as_posix() for root in roots],
            "total_undeclared": len(undeclared),
            "allowlisted": sorted(set(undeclared) & allowlist),
            "new_violations": new_violations,
            "stale_allowlist": stale,
            "undeclared": {
                name: [site.path for site in pkg.sites]
                for name, pkg in undeclared.items()
            },
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1 if new_violations else 0

    if new_violations:
        print(f"НОВЫЕ необъявленные зависимости: {len(new_violations)}")
        for name in new_violations:
            sites = undeclared[name].sites
            preview = ", ".join(f"{site.path}:{site.lineno}" for site in sites[:3])
            print(f"  {name}  ← {preview}")
        print(
            "\nОбъявите пакет в [project].dependencies / [project.optional-dependencies] "
            "либо внесите его в allowlist:\n"
            "  python tools/check_declared_dependencies.py --update-allowlist"
        )
        return 1

    if stale:
        print(
            f"СТЕЙЛ записи в allowlist: {len(stale)} "
            "(пакет объявлен/удалён — обновите allowlist)"
        )
        for name in stale[:10]:
            print(f"  {name}")
        print(
            "\nОбновить: python tools/check_declared_dependencies.py --update-allowlist"
        )

    print(
        f"Необъявленных зависимостей: 0 новых "
        f"(всего в долге: {len(undeclared)}; allowlist: {len(allowlist)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
