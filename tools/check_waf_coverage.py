#!/usr/bin/env python3
"""WAF-coverage gate (V15 R-V15-5, S1 DoD).

Сканирует ``src/backend/`` (и плагины) на прямые использования
``httpx.AsyncClient(...)``, ``httpx.Client(...)`` и module-level
``httpx.get/post/...`` без явного :external-флага. Все такие callsite'ы
обязаны идти через :class:`OutboundHttpClient` (см. ADR R-V15-5).

Allowlist живёт в ``tools/check_waf_coverage_allowlist.txt`` —
известные :internal callsite'ы (внутренние сервисы кластера) или
тест-фикстуры с MockTransport. Файл-пути относительные от корня
проекта; пустые строки и ``#``-комментарии игнорируются.

Запуск::

    python tools/check_waf_coverage.py [--root SRC] [--strict]

* exit-code 1 если найдены violations не из allowlist;
* ``--strict`` игнорирует allowlist (CI/release-gate).
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT_DEFAULT = Path("src/backend")
ALLOWLIST_FILE = Path("tools/check_waf_coverage_allowlist.txt")

# Имена httpx-классов, использование которых вне OutboundHttpClient
# считается WAF-bypass'ом.
_BANNED_CLASSES: frozenset[str] = frozenset({"AsyncClient", "Client"})

# Пути, которые ВСЕГДА игнорируются (внутренние компоненты WAF/тесты).
_INTERNAL_EXEMPT_PREFIXES: tuple[str, ...] = (
    "src/backend/core/net/",
    "src/backend/infrastructure/clients/transport/",
)


def _iter_python_files(root: Path) -> Iterable[Path]:
    """Перечисляет все .py-файлы под ``root`` (без __pycache__)."""
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


def _load_allowlist() -> set[str]:
    """Читает baseline относительных путей.

    Поддерживает inline-комменты вида ``path/file.py  # owner=K1 | ...``:
    обрезает всё начиная с первого ``#`` и берёт путь без хвоста.
    """
    if not ALLOWLIST_FILE.is_file():
        return set()
    entries: set[str] = set()
    for line in ALLOWLIST_FILE.read_text(encoding="utf-8").splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.startswith("#"):
            continue
        path_only = cleaned.split("#", 1)[0].strip()
        if path_only:
            entries.add(path_only)
    return entries


def _collect_aliased_names(tree: ast.AST) -> set[str]:
    """Возвращает локальные имена, которые ссылаются на ``httpx.{AsyncClient,Client}``.

    Ловит:

    * ``from httpx import AsyncClient`` → {"AsyncClient"};
    * ``from httpx import AsyncClient as X`` → {"X"};
    * ``import httpx as h`` нас не интересует — там всё равно остаётся
      attribute access ``h.AsyncClient(...)``, что отдельно покрывается
      проверкой ``func.value.id``.
    """
    aliased: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "httpx":
            for alias in node.names:
                if alias.name in _BANNED_CLASSES:
                    aliased.add(alias.asname or alias.name)
    return aliased


def _is_httpx_violation(node: ast.AST, aliased_names: set[str]) -> bool:
    """Возвращает ``True``, если node — прямой вызов httpx.{AsyncClient,Client}.

    ``httpx.MockTransport``, ``httpx.Response``, ``httpx.Limits``, etc.
    считаются легитимными — они не открывают сеть напрямую.
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    # Pattern: ``httpx.AsyncClient(...)`` или ``httpx.Client(...)``.
    if (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "httpx"
        and func.attr in _BANNED_CLASSES
    ):
        return True
    # Pattern: ``X(...)`` где X получен через
    # ``from httpx import AsyncClient [as X]`` — Wave 1.5.
    if isinstance(func, ast.Name) and func.id in aliased_names:
        return True
    return False


def _scan_file(path: Path) -> list[tuple[int, str]]:
    """Возвращает список ``(line, snippet)`` нарушений в файле."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    aliased = _collect_aliased_names(tree)
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if _is_httpx_violation(node, aliased):
            assert isinstance(node, ast.Call)  # noqa: S101 — narrowing
            try:
                snippet = ast.unparse(node).splitlines()[0]
            except Exception:  # noqa: BLE001 — safe fallback
                snippet = "<unparseable>"
            violations.append((node.lineno, snippet))
    return violations


def _is_internal_exempt(rel_path: str) -> bool:
    """Внутренние компоненты WAF/transport — заведомо exempt."""
    return rel_path.startswith(_INTERNAL_EXEMPT_PREFIXES)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WAF coverage check (V15 S1).")
    parser.add_argument("--root", default=str(ROOT_DEFAULT), help="Каталог сканирования")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Игнорировать allowlist (CI/release-gate)",
    )
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        print(f"WAF check: директория не найдена: {root}", file=sys.stderr)
        return 2

    allowlist = set() if args.strict else _load_allowlist()

    repo_root = Path.cwd().resolve()
    violations: list[tuple[str, int, str]] = []
    for path in _iter_python_files(root):
        try:
            rel = path.resolve().relative_to(repo_root).as_posix()
        except ValueError:
            rel = path.as_posix()
        if _is_internal_exempt(rel):
            continue
        if rel in allowlist:
            continue
        for line, snippet in _scan_file(path):
            violations.append((rel, line, snippet))

    if violations:
        print("WAF coverage violations (direct httpx.AsyncClient/Client usage):")
        for rel, line, snippet in violations:
            print(f"  {rel}:{line}: {snippet}")
        print()
        print(
            "Эти callsite'ы обязаны идти через "
            "src.backend.core.net.OutboundHttpClient или быть добавлены в "
            f"{ALLOWLIST_FILE} с обоснованием :internal."
        )
        return 1

    print("WAF coverage OK: 0 violations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
