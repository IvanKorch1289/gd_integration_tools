"""Codemod: ``except A, B:`` → ``except (A, B):``.

Назначение
----------
Python 3.x не отвергает синтаксис ``except A, B:`` как ``SyntaxError`` —
интерпретатор молча трактует его как кортеж эксепшенов
(``except (A, B):``). Это **не** Python-2-биндинг ``except A, B as e``
(уже невалиден в Python 3), но **стиль** идентичен Python-2 и легко вводит
читателя в заблуждение. PLAN.md V22 §S17 запрещает такой стиль в кодовой
базе и требует ``DoD #2: grep = 0``.

Codemod находит ``cst.ExceptHandler``, у которого ``handler.type`` —
``cst.Tuple`` без скобок (``lpar=()``), и оборачивает его в скобочную
форму. Семантика не меняется (Python 3 уже видит tuple), trailing-
комментарии, ``as``-биндинг и форматирование сохраняются.

Применение
----------
::

    # Применить ко всем файлам::
    python -m tools.codemods.fix_except_clause src/backend

    # Только показать diff, файлы не трогать::
    python -m tools.codemods.fix_except_clause --dry-run src/backend

    # CI-режим: exit 1 если есть что менять::
    python -m tools.codemods.fix_except_clause --check src/backend

Идемпотентность
---------------
Повторный запуск на уже исправленных файлах изменений не вносит:
скобки добавляются только при ``lpar=()``.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

import libcst as cst


# --- Codemod ---------------------------------------------------------------- #
class FixExceptClauseTransformer(cst.CSTTransformer):
    """Оборачивает ``except A, B:`` в ``except (A, B):``.

    Срабатывает на любом ``ExceptHandler``, у которого ``handler.type``
    является ``cst.Tuple`` без круглых скобок. Не трогает обработчики
    с одиночным эксепшеном, без ``type``, или уже скобочной формой.
    """

    def leave_ExceptHandler(  # noqa: N802 — libcst API
        self, original_node: cst.ExceptHandler, updated_node: cst.ExceptHandler
    ) -> cst.ExceptHandler:
        """Добавить скобки к tuple-эксепшену без скобок."""
        node_type = updated_node.type
        if not isinstance(node_type, cst.Tuple):
            return updated_node
        if node_type.lpar:
            return updated_node
        new_type = node_type.with_changes(
            lpar=[cst.LeftParen()], rpar=[cst.RightParen()]
        )
        return updated_node.with_changes(type=new_type)


# --- Файловые операции ------------------------------------------------------ #
_SKIP_DIRS: frozenset[str] = frozenset(
    {
        "__pycache__",
        ".venv",
        "venv",
        ".git",
        "build",
        "dist",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "node_modules",
    }
)


def iter_python_files(roots: Iterable[Path]) -> Iterator[Path]:
    """Обойти ``.py``-файлы под списком корней (файлов или директорий)."""
    for root in roots:
        if root.is_file():
            if root.suffix == ".py":
                yield root
            continue
        for path in root.rglob("*.py"):
            if _SKIP_DIRS & set(path.parts):
                continue
            yield path


def transform_source(source: str) -> str:
    """Применить codemod к строке исходника и вернуть результат."""
    tree = cst.parse_module(source)
    new_tree = tree.visit(FixExceptClauseTransformer())
    return new_tree.code


def process_file(path: Path, *, check_only: bool, dry_run: bool) -> bool:
    """Обработать один файл. Вернуть ``True``, если файл изменился (или изменился бы)."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"WARN: не удалось прочитать {path}: {exc}", file=sys.stderr)
        return False
    try:
        new_source = transform_source(source)
    except cst.ParserSyntaxError as exc:
        print(f"WARN: parse error в {path}: {exc}", file=sys.stderr)
        return False

    if new_source == source:
        return False

    if dry_run:
        diff = difflib.unified_diff(
            source.splitlines(keepends=True),
            new_source.splitlines(keepends=True),
            fromfile=f"{path} (before)",
            tofile=f"{path} (after)",
        )
        sys.stdout.writelines(diff)
        return True

    if check_only:
        print(f"NEEDS FIX: {path}")
        return True

    path.write_text(new_source, encoding="utf-8")
    print(f"FIXED: {path}")
    return True


# --- CLI -------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    """CLI-точка входа: разобрать аргументы и применить codemod к файлам.

    Аргументы:
        argv: список аргументов командной строки; ``None`` → ``sys.argv[1:]``.

    Возвращает:
        ``0`` — нет изменений (или все применены успешно);
        ``1`` — в ``--check`` режиме нашлись файлы, требующие исправления.
    """
    parser = argparse.ArgumentParser(
        description="Codemod: except A, B: → except (A, B): (libcst)"
    )
    parser.add_argument(
        "paths", nargs="+", type=Path, help="Файлы или директории для обхода"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--check",
        action="store_true",
        help="CI-режим: не менять файлы, exit 1 если есть что менять",
    )
    group.add_argument(
        "--dry-run",
        action="store_true",
        help="Только вывести unified-diff, файлы не менять",
    )
    args = parser.parse_args(argv)

    files = list(iter_python_files(args.paths))
    changed_count = 0
    for path in files:
        if process_file(path, check_only=args.check, dry_run=args.dry_run):
            changed_count += 1

    if args.check:
        if changed_count:
            print(f"\n{changed_count} файл(ов) требует исправления.", file=sys.stderr)
            return 1
        print("OK: все файлы соответствуют стилю.")
        return 0

    if args.dry_run:
        print(f"\n{changed_count} файл(ов) изменилось бы (dry-run).", file=sys.stderr)
        return 0

    print(f"\n{changed_count} файл(ов) исправлено.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
