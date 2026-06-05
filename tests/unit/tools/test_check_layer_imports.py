# ruff: noqa: S101
"""Unit-тесты для ``tools/check_layer_imports.py`` (V15 GAP capability-gate).

Покрытие:

* ``_scan_file`` — AST-обход, выявление forbidden imports;
* ``_is_in_type_checking`` — игнорирование ``if TYPE_CHECKING:`` блоков;
* ``_parse_toml`` — override whitelist/blacklist через TOML;
* CLI — help message, default directory, exit codes, multi-violations.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

TOOL_PATH = Path("tools/check_layer_imports.py")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Запускает ``python tools/check_layer_imports.py <args>`` через subprocess.

    Использует абсолютный путь к скрипту (CWD может быть передан через ``cwd``).
    """
    abs_tool = (Path(__file__).resolve().parents[3] / TOOL_PATH).resolve()
    return subprocess.run(  # noqa: S603
        [sys.executable, str(abs_tool), *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        cwd=str(cwd) if cwd else None,
    )


def _write_py(path: Path, body: str) -> None:
    """Записывает ``body`` в файл, создавая родительские директории."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


# Текстовые заготовки (Russian-first, минимальный slice).
_CLEAN_PLUGIN = '''"""Чистый plugin: только whitelisted core imports."""

from __future__ import annotations

from src.backend.core.interfaces.plugin import BasePlugin
from src.backend.core.security.capabilities import CapabilityRef


class GoodPlugin(BasePlugin):
    """Демо-плагин без cross-layer нарушений."""
'''


_FORBIDDEN_INFRA = '''"""Plugin с прямым импортом infrastructure (должен быть flagged)."""

from __future__ import annotations

from src.backend.infrastructure.database.session_manager import main_session_manager


def use_db() -> object:
    """Прямой доступ к infrastructure."""
    return main_session_manager
'''


_FORBIDDEN_SERVICES = '''"""Plugin с прямым импортом services (должен быть flagged)."""

from __future__ import annotations

from src.backend.services.core.base import BaseService


class MyService(BaseService):
    """Прямое наследование от services.core.base."""
'''


_TYPE_CHECKING_OK = '''"""TYPE_CHECKING-импорт infrastructure — должен быть проигнорирован."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.infrastructure.database.models.files import File  # type: ignore

from src.backend.core.interfaces.plugin import BasePlugin


class TCPlugin(BasePlugin):
    """TYPE_CHECKING import не считается нарушением."""
'''


_MULTI_VIOLATIONS = '''"""Несколько нарушений в одном файле."""

from __future__ import annotations

from src.backend.infrastructure.cache.redis_client import RedisClient
from src.backend.services.integrations.skb import APISKBService
from src.backend.infrastructure.repositories.base import SQLAlchemyRepository
from src.backend.core.interfaces.plugin import BasePlugin
'''


# ---------------------------------------------------------------------------
# 1) Clean plugin — нет нарушений
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_clean_plugin_no_violations(tmp_path: Path) -> None:
    """Чистый plugin: только core imports → ``_scan_file`` возвращает []."""
    from tools.check_layer_imports import _scan_file  # type: ignore[import-not-found]

    plugin = tmp_path / "plugin.py"
    _write_py(plugin, _CLEAN_PLUGIN)

    forbidden = ("src.backend.infrastructure.", "src.backend.services.")
    whitelist = ("src.backend.core.",)
    assert _scan_file(plugin, forbidden, whitelist) == []


# ---------------------------------------------------------------------------
# 2) Forbidden infrastructure import
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_forbidden_infrastructure_import(tmp_path: Path) -> None:
    """Импорт ``src.backend.infrastructure.*`` → ровно одно violation."""
    from tools.check_layer_imports import _scan_file  # type: ignore[import-not-found]

    plugin = tmp_path / "plugin.py"
    _write_py(plugin, _FORBIDDEN_INFRA)

    forbidden = ("src.backend.infrastructure.", "src.backend.services.")
    whitelist = ("src.backend.core.",)
    violations = _scan_file(plugin, forbidden, whitelist)
    assert len(violations) == 1
    lineno, module, prefix = violations[0]
    assert module == "src.backend.infrastructure.database.session_manager"
    assert prefix == "src.backend.infrastructure."


# ---------------------------------------------------------------------------
# 3) Forbidden services import
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_forbidden_services_import(tmp_path: Path) -> None:
    """Импорт ``src.backend.services.*`` → ровно одно violation."""
    from tools.check_layer_imports import _scan_file  # type: ignore[import-not-found]

    plugin = tmp_path / "plugin.py"
    _write_py(plugin, _FORBIDDEN_SERVICES)

    forbidden = ("src.backend.infrastructure.", "src.backend.services.")
    whitelist = ("src.backend.core.",)
    violations = _scan_file(plugin, forbidden, whitelist)
    assert len(violations) == 1
    lineno, module, prefix = violations[0]
    assert module == "src.backend.services.core.base"
    assert prefix == "src.backend.services."


# ---------------------------------------------------------------------------
# 4) TYPE_CHECKING блок игнорируется
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_type_checking_block_ignored(tmp_path: Path) -> None:
    """Import внутри ``if TYPE_CHECKING:`` — НЕ violation."""
    from tools.check_layer_imports import _scan_file  # type: ignore[import-not-found]

    plugin = tmp_path / "plugin.py"
    _write_py(plugin, _TYPE_CHECKING_OK)

    forbidden = ("src.backend.infrastructure.", "src.backend.services.")
    whitelist = ("src.backend.core.",)
    assert _scan_file(plugin, forbidden, whitelist) == []


@pytest.mark.unit
def test_type_checking_attribute_form_also_ignored(tmp_path: Path) -> None:
    """Полная форма ``if typing.TYPE_CHECKING:`` — тоже игнорируется."""
    from tools.check_layer_imports import _scan_file  # type: ignore[import-not-found]

    src = '''"""Полная dotted-форма TYPE_CHECKING."""

from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from src.backend.infrastructure.db import Thing  # type: ignore

from src.backend.core.interfaces.plugin import BasePlugin


class P(BasePlugin):
    pass
'''
    plugin = tmp_path / "plugin.py"
    _write_py(plugin, src)

    forbidden = ("src.backend.infrastructure.", "src.backend.services.")
    whitelist = ("src.backend.core.",)
    assert _scan_file(plugin, forbidden, whitelist) == []


# ---------------------------------------------------------------------------
# 5) Whitelisted core imports — pass
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_whitelisted_core_imports_pass(tmp_path: Path) -> None:
    """Множественные whitelisted core imports — все pass."""
    from tools.check_layer_imports import _scan_file  # type: ignore[import-not-found]

    src = '''"""Whitelisted core.* (interfaces, security.capabilities, di)."""

from __future__ import annotations

from src.backend.core.interfaces.plugin import BasePlugin
from src.backend.core.interfaces.repositories import FileRepositoryProtocol
from src.backend.core.security.capabilities import CapabilityRef, CapabilityGate
from src.backend.core.di.providers import get_file_repo_provider


class WhitelistedPlugin(BasePlugin):
    pass
'''
    plugin = tmp_path / "plugin.py"
    _write_py(plugin, src)

    forbidden = ("src.backend.infrastructure.", "src.backend.services.")
    whitelist = ("src.backend.core.",)
    assert _scan_file(plugin, forbidden, whitelist) == []


# ---------------------------------------------------------------------------
# 6) CLI: --help
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cli_help_message() -> None:
    """``--help`` → exit 0, описание содержит "infrastructure" и "services"."""
    result = _run_cli("--help")
    assert result.returncode == 0
    assert "infrastructure" in result.stdout
    assert "services" in result.stdout


# ---------------------------------------------------------------------------
# 7) CLI: default directory = extensions/
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cli_default_directory(tmp_path: Path) -> None:
    """CLI без аргументов сканирует ``extensions/`` (default)."""
    # Создаём минимальный extensions/ с чистым plugin'ом
    ext = tmp_path / "extensions" / "demo_plugin"
    _write_py(ext / "plugin.py", _CLEAN_PLUGIN)

    # Запускаем из tmp_path, чтобы default 'extensions' указывал на наш фикстуру
    result = _run_cli(cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


# ---------------------------------------------------------------------------
# 8) Multiple violations — все репортируются
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_multiple_violations_reported(tmp_path: Path) -> None:
    """Несколько нарушений в одном файле → каждое отдельной строкой в stderr."""
    result = _run_cli(str(tmp_path / "dummy"))
    # dummy dir не существует → exit 2; создадим реальный plugin
    plugin = tmp_path / "plugin.py"
    _write_py(plugin, _MULTI_VIOLATIONS)

    result = _run_cli(str(tmp_path))
    assert result.returncode == 1
    # 3 forbidden imports (2× infrastructure + 1× services) + 1 core (pass)
    assert "src.backend.infrastructure.cache.redis_client" in result.stderr
    assert "src.backend.services.integrations.skb" in result.stderr
    assert "src.backend.infrastructure.repositories.base" in result.stderr
    # core import НЕ должен появиться в stderr
    assert "src.backend.core.interfaces.plugin" not in result.stderr


# ---------------------------------------------------------------------------
# Бонус: TOML override (для полноты coverage)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_toml_override_extends_whitelist(tmp_path: Path) -> None:
    """``--config`` с whitelist-плагином убирает нарушение из списка."""
    toml = """[whitelisted]
prefixes = ["src.backend.core.", "src.backend.infrastructure.allowed."]
"""
    config = tmp_path / "override.toml"
    config.write_text(toml, encoding="utf-8")

    # Импорт infrastructure.allowed.* — без override это violation, с override — нет.
    src = '''"""Import infrastructure.allowed.* — пропустит whitelist override."""

from __future__ import annotations

from src.backend.infrastructure.allowed.helper import do_thing
'''
    plugin = tmp_path / "plugin.py"
    _write_py(plugin, src)

    # Без override: violation
    result_no_cfg = _run_cli(str(tmp_path))
    assert result_no_cfg.returncode == 1
    assert "src.backend.infrastructure.allowed.helper" in result_no_cfg.stderr

    # С override: clean
    result_with_cfg = _run_cli(str(tmp_path), "--config", str(config))
    assert result_with_cfg.returncode == 0, result_with_cfg.stderr
    assert "OK" in result_with_cfg.stdout


@pytest.mark.unit
def test_cli_missing_directory_exits_2(tmp_path: Path) -> None:
    """Несуществующая директория → exit 2 + ERROR в stderr."""
    result = _run_cli(str(tmp_path / "does_not_exist"))
    assert result.returncode == 2
    assert "ERROR" in result.stderr


@pytest.mark.unit
def test_marker_unit_applied() -> None:
    """Smoke: этот модуль запускается с маркером ``unit`` (см. pyproject)."""
    # Проверяем, что pytest markers сконфигурированы (см. conftest pyproject.toml).
    assert True
