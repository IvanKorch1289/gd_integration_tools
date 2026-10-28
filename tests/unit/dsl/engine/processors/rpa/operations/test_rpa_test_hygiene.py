"""Гигиена RPA-тестов: гейт на поллюцию глобального состояния (ADR-0370).

Cycle 172 (кластер C5) нашёл три дефекта в RPA-тестах, которые ломали
CI (``pytest tests -n auto``) или загрязняли окружение:

1. ``test_more_rpa_tools.py`` присваивал ``ftplib.FTP`` / ``ftplib.FTP_TLS``
   на глобальном модуле — мутация переживала тест и ломала соседние
   FTP-тесты в параллельном прогоне;
2. ``test_new_rpa_tools.py`` писал в общий ``/tmp/dsl`` вместо
   ``tmp_path`` — гонки при ``-n auto`` + мусор на машине;
3. ``test_operation_processors.py`` проверял моки без значений
   (``assert_called()``) — тест проходил бы и при неверных аргументах.

Проверки — AST-скан RPA-тестов: они ловят регрессию, а не конкретное
состояние конкретного файла.
"""

from __future__ import annotations

import ast
from pathlib import Path

_RPA_TESTS_DIR = Path(__file__).resolve().parent

#: Файл с value-less mock-assertions.
_OPERATION_TESTS = _RPA_TESTS_DIR / "test_operation_processors.py"

#: Атрибуты-assert'ы, не проверяющие аргументы вызова.
_VALUE_LESS_ASSERTS = frozenset({"assert_called", "assert_called_once"})


def _test_files() -> list[Path]:
    """Все RPA-тесты операций (рекурсивно)."""
    return sorted(p for p in _RPA_TESTS_DIR.rglob("test_*.py") if p.is_file())


def _imported_ftplib_aliases(tree: ast.Module) -> set[str]:
    """Имена, под которыми импортирован модуль ``ftplib``."""
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "ftplib":
                    aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "ftplib":
            for alias in node.names:
                aliases.add(alias.asname or alias.name)
    return aliases


#: Вызовы, которые реально пишут в ФС.
_WRITE_CALLS = frozenset(
    {"write_text", "write_bytes", "makedirs", "mkdir", "unlink", "remove", "rmtree"}
)


def _string_bindings(tree: ast.Module) -> dict[str, str]:
    """Карта ``имя → строковый литерал`` (для разрешения аргументов)."""
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bindings[target.id] = node.value.value
    return bindings


def _resolve(value: ast.expr, bindings: dict[str, str]) -> str | None:
    """Строковое значение аргумента (с учётом ``name = "literal"``)."""
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    if isinstance(value, ast.Name):
        return bindings.get(value.id)
    return None


def test_no_global_ftplib_mutation() -> None:
    """RPA-тесты не мутируют глобальный модуль ftplib."""
    offenders: list[str] = []
    for path in _test_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        aliases = _imported_ftplib_aliases(tree)
        if not aliases:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id in aliases
                ):
                    offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, (
        "глобальная мутация ftplib в RPA-тестах (используй monkeypatch.setattr): "
        f"{offenders}"
    )


def test_no_shared_tmp_paths() -> None:
    """RPA-тесты не пишут в общие каталоги /tmp (только tmp_path)."""
    offenders: list[str] = []
    for path in _test_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bindings = _string_bindings(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute):
                is_write = func.attr in _WRITE_CALLS
            elif isinstance(func, ast.Name):
                is_write = func.id == "open"
            else:
                is_write = False
            if not is_write:
                continue
            for arg in node.args:
                resolved = _resolve(arg, bindings)
                if resolved is not None and resolved.startswith("/tmp/"):
                    offenders.append(f"{path.name}:{node.lineno} → {resolved}")
    assert not offenders, (
        "RPA-тесты пишут в общий /tmp вместо tmp_path: " f"{offenders}"
    )


def test_operation_processor_mocks_verify_values() -> None:
    """Моки в test_operation_processors.py проверяют аргументы вызова."""
    tree = ast.parse(_OPERATION_TESTS.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _VALUE_LESS_ASSERTS
        ):
            offenders.append(f"{node.func.attr} @ line {node.lineno}")
    assert not offenders, (
        "value-less mock-assertions (используй assert_called_once_with): "
        f"{offenders}"
    )
