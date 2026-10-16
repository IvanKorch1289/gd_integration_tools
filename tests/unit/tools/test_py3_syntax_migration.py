"""Regression test: Py2 → Py3 syntax migration guard.

Защищает от повторного появления Python 2 ``except X, Y:`` синтаксиса
в ``src/backend/**``. Этот синтаксис не парсится в Python 3.7+ и блокирует
любой import (включая pytest assert rewrite), поэтому критично, чтобы
``ast.parse`` чисто проходил по всем модулям ``src/backend/``.

История: в 2026-Q3 найдено 138 Py2-``except`` в 112 модулях после миграции
на Python 3.14. Они были исправлены одним проходом (см. commit
``fix(syntax): …``). Этот тест предотвращает регрессию.

Тест не фиксирует список путей (это хрупко); он проверяет **все** файлы
``src/backend/**/*.py`` на двух инвариантах:

1. ``ast.parse`` принимает файл без ``SyntaxError``.
2. В AST нет узла ``ast.ExceptHandler`` без скобок (т.е. Py2-форма).

Это покрывает любые новые файлы, добавленные в проект.
"""

from __future__ import annotations

import ast
import pathlib

# Корень исходников — единственная hard-coded точка.
SRC_ROOT = pathlib.Path("src/backend")


def _iter_py_files() -> list[pathlib.Path]:
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
