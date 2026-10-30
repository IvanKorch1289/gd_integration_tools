"""ADR-0400: ``.env`` загружается ЯВНО при старте CLI/процесса.

Дефект (долг ADR-0372, п. 1): ``load_env_file()`` упоминался только в
``core/config/config_loader.py`` — из ``manage.py`` / ``src/backend/main.py``
его никто не звал. Формально ``.env`` подхватывался входом в цепочку
источников (``ensure_env_file_loaded()``), но CLI-старт не объявлял это
явно: потребители ``os.environ`` (feature-флаги, DSN) читали окружение
раньше, чем файл был прочитан.

Тесты фиксируют:
1. в ``manage.py`` и ``src/backend/main.py`` есть явный вызов
   ``load_env_file()`` на уровне модуля;
2. в ``src/backend/main.py`` вызов идёт ДО импорта ``settings``;
3. ``manage.py`` действительно вызывает ``load_env_file()`` при старте
   (функциональная проверка через переимпорт модуля с подменой).
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MANAGE_PY = _REPO_ROOT / "manage.py"
_MAIN_PY = _REPO_ROOT / "src" / "backend" / "main.py"

_LOAD_ENV_NAMES = {"load_env_file", "ensure_env_file_loaded"}


def _module_level_env_calls(path: Path) -> list[ast.Call]:
    """Найти вызовы ``load_env_file``/``ensure_env_file_loaded`` на уровне модуля.

    Args:
        path: Путь к анализируемому Python-файлу.

    Returns:
        Список AST-вызовов (без вложенных в функции/классы).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls: list[ast.Call] = []
    for node in tree.body:
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name in _LOAD_ENV_NAMES:
            calls.append(node.value)
    return calls


def _settings_import_line(path: Path) -> int:
    """Найти номер строки импорта ``settings`` в модуле.

    Args:
        path: Путь к анализируемому Python-файлу.

    Returns:
        Номер строки (1-based) или ``0``, если импорта нет.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "src.backend.core.config.settings"
        ):
            return node.lineno
    return 0


@pytest.mark.unit
def test_manage_py_calls_load_env_file_explicitly() -> None:
    """``manage.py`` явно вызывает ``load_env_file()`` при старте CLI."""
    calls = _module_level_env_calls(_MANAGE_PY)
    assert calls, "manage.py обязан явно вызывать load_env_file() при старте CLI"


@pytest.mark.unit
def test_main_py_calls_load_env_file_explicitly() -> None:
    """``src/backend/main.py`` явно вызывает ``load_env_file()`` при старте."""
    calls = _module_level_env_calls(_MAIN_PY)
    assert calls, "main.py обязан явно вызывать load_env_file() при старте процесса"


@pytest.mark.unit
def test_main_py_loads_env_before_settings_import() -> None:
    """Вызов в ``main.py`` расположен ДО импорта ``settings``."""
    calls = _module_level_env_calls(_MAIN_PY)
    assert calls
    settings_line = _settings_import_line(_MAIN_PY)
    assert settings_line, "main.py должен импортировать settings"
    call_line = min(call.lineno for call in calls)
    assert call_line < settings_line, (
        f"load_env_file() (строка {call_line}) должен вызываться до импорта "
        f"settings (строка {settings_line})"
    )


@pytest.mark.unit
def test_manage_py_calls_load_env_file_at_runtime() -> None:
    """Функциональная проверка: старт CLI действительно читает ``.env``."""
    import manage

    with patch("src.backend.core.config.config_loader.load_env_file") as mock_load_env:
        importlib.reload(manage)

    mock_load_env.assert_called()
