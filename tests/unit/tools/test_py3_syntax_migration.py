"""Regression test: Py2 → Py3 syntax migration guard.

Защищает от повторного появления Python 2 ``except X, Y:`` синтаксиса
в ``src/backend/**``, ``tests/**`` и ``tools/**``. Этот синтаксис не
парсится в Python 3.7+ и блокирует любой import (включая pytest assert
rewrite) и любую загрузку tools-скриптов, поэтому критично, чтобы
``ast.parse`` чисто проходил по всем модулям в этих трёх директориях.

История: в 2026-Q3 найдено 138 Py2-``except`` в 112 модулях ``src/backend/``
после миграции на Python 3.14. В round 2 (commit ``a543fbaf6``) добиты
оставшиеся 200 случаев в ``src/backend/``. В round 3 (commit
``ae5bb0490``) устранены 37 случаев в ``tests/`` и ``tools/``. Этот тест
предотвращает регрессию во всех трёх директориях.

Тест не фиксирует список путей (это хрупко); он проверяет **все** файлы
в охраняемых корнях на двух инвариантах:

1. ``ast.parse`` принимает файл без ``SyntaxError``.
2. В коде нет паттерна ``except X, Y:`` (Py2-форма).

Это покрывает любые новые файлы, добавленные в проект.
"""

from __future__ import annotations

import ast
import pathlib

# Корни, которые мы охраняем от Py2-syntax regression.
SRC_ROOTS: tuple[pathlib.Path, ...] = (
    pathlib.Path("src/backend"),
    pathlib.Path("tests"),
    pathlib.Path("tools"),
)


def _iter_py_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for root in SRC_ROOTS:
        if root.exists():
            files.extend(root.rglob("*.py"))
    return sorted(files)
    return sorted(SRC_ROOT.rglob("*.py"))


def _check_clean(path: pathlib.Path) -> str | None:
    """Возвращает сообщение об ошибке или ``None`` если всё ОК."""
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return f"{path}: UnicodeDecodeError: {exc}"
    try:
        ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return f"{path}:{exc.lineno}: {exc.msg}"
    return None


def test_all_src_backend_files_parse_cleanly() -> None:
    """Все ``src/backend/**/*.py`` парсятся Python 3 без ``SyntaxError``."""
    failures: list[str] = []
    files = _iter_py_files()
    assert files, f"no .py files under {SRC_ROOT}"
    for path in files:
        err = _check_clean(path)
        if err:
            failures.append(err)
    assert not failures, (
        f"{len(failures)} files failed syntax check; "
        f"first 10:\n  " + "\n  ".join(failures[:10])
    )


def test_no_py2_except_pattern_anywhere() -> None:
    """Защита от случайного появления ``except X, Y:`` в любом файле.

    Это второй проход — на случай если ``ast.parse`` всё же что-то
    пропустит (например, обёрнутый в ``type: ignore`` синтаксис).
    """
    import re

    pattern = re.compile(r"^\s*except\s+(?!\()[\w.]+(?:\s*,\s*[\w.]+)+\s*:")
    violations: list[str] = []
    for path in _iter_py_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.match(line):
                violations.append(f"{path}:{lineno}: {line.strip()}")
    assert not violations, (
        f"Py2 except syntax detected in {len(violations)} files:\n  "
        + "\n  ".join(violations[:10])
    )
