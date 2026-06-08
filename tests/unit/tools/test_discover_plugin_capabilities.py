# ruff: noqa: S101
"""Unit-тесты для ``tools/discover_plugin_capabilities.py`` (V15 GAP Gap 4).

Покрытие:

* ``discover_capabilities`` — AST-обход, извлечение строковых литералов
  из ``gate.check`` / ``gate.check_tenant`` / ``gate.declare_tenant`` /
  ``self.requires_capability``;
* ``_is_in_type_checking`` — игнорирование ``if TYPE_CHECKING:`` блоков;
* ``_resolve_plugin_path`` — резолв директории / прямого ``.py`` пути;
* CLI — help message, default path, exit codes, output format.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

TOOL_PATH = Path("tools/discover_plugin_capabilities.py")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Запускает ``python tools/discover_plugin_capabilities.py <args>``."""
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
_PLUGIN_WITH_CHECK_TENANT = '''"""Plugin с gate.check_tenant вызовами (capability = 1-й арг)."""

from __future__ import annotations


async def use_caps(gate) -> None:
    """Демонстрация нескольких capability-gate вызовов."""
    await gate.check_tenant("mq.publish", "tenant_a", "plugin")
    await gate.check_tenant("db.read", "tenant_a", "plugin")
    await gate.check_tenant("mq.publish", "tenant_b", "plugin")  # дубликат
'''

_PLUGIN_WITH_GATE_CHECK = '''"""Plugin с gate.check вызовами (capability = 2-й арг)."""

from __future__ import annotations


async def check_caps(gate) -> None:
    """``gate.check`` — capability во 2-м позиционном аргументе."""
    if await gate.check("plugin", "secrets.read"):
        pass
    if await gate.check("plugin", "fs.write"):
        pass
'''

_PLUGIN_WITH_DECLARE_AND_REQUIRES = '''"""Plugin с declare_tenant / requires_capability (оба: 1-й арг)."""

from __future__ import annotations


async def setup(gate, self) -> None:
    """declare_tenant + requires_capability — 1-й позиционный аргумент."""
    await gate.declare_tenant("vault.read", "tenant_x", "principal")
    if self.requires_capability("analytics.export"):
        pass
'''

_PLUGIN_EMPTY = '''"""Plugin без capability-вызовов."""

from __future__ import annotations


class Empty:
    """Пустой класс без gate.* вызовов."""

    name = "empty"
'''

_PLUGIN_TYPE_CHECKING_IGNORED = '''"""TYPE_CHECKING-вызовы — НЕ должны попасть в рекомендации."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # В type-only блоке может быть любой код; здесь — вызов,
    # который при runtime не существует, но AST его видит.
    _phantom: bool = check_tenant("phantom.cap", "x")  # type: ignore


def runtime_call(gate) -> None:
    """Runtime вызов со строковым литералом — должен быть обнаружен."""
    gate.check_tenant("real.cap", "tenant")
'''

_PLUGIN_SYNTAX_ERROR = '''"""Plugin с синтаксической ошибкой — graceful handling."""

from __future__ import annotations


def broken(gate) -> None:
    """Отсутствует двоеточие — SyntaxError при parse."""
    gate.check_tenant("won't.parse"


class X:
    pass
'''


# ---------------------------------------------------------------------------
# 1) discover_capabilities: gate.check_tenant
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_discover_finds_check_tenant_calls(tmp_path: Path) -> None:
    """``gate.check_tenant("cap", ...)`` → cap = 1-й позиционный аргумент."""
    from tools.discover_plugin_capabilities import (  # type: ignore[import-not-found]
        discover_capabilities,
    )

    plugin = tmp_path / "plugin.py"
    _write_py(plugin, _PLUGIN_WITH_CHECK_TENANT)

    caps = discover_capabilities(plugin)
    # Дубликат mq.publish дедуплицируется; сортировка алфавитная.
    assert caps == ["db.read", "mq.publish"]


# ---------------------------------------------------------------------------
# 2) discover_capabilities: gate.check
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_discover_finds_gate_check_calls(tmp_path: Path) -> None:
    """``gate.check("plugin", "cap")`` → cap = 2-й позиционный аргумент."""
    from tools.discover_plugin_capabilities import (  # type: ignore[import-not-found]
        discover_capabilities,
    )

    plugin = tmp_path / "plugin.py"
    _write_py(plugin, _PLUGIN_WITH_GATE_CHECK)

    caps = discover_capabilities(plugin)
    assert caps == ["fs.write", "secrets.read"]


# ---------------------------------------------------------------------------
# 3) discover_capabilities: declare_tenant + requires_capability
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_discover_finds_declare_and_requires(tmp_path: Path) -> None:
    """``declare_tenant`` и ``requires_capability`` — оба берут 1-й арг."""
    from tools.discover_plugin_capabilities import (  # type: ignore[import-not-found]
        discover_capabilities,
    )

    plugin = tmp_path / "plugin.py"
    _write_py(plugin, _PLUGIN_WITH_DECLARE_AND_REQUIRES)

    caps = discover_capabilities(plugin)
    assert caps == ["analytics.export", "vault.read"]


# ---------------------------------------------------------------------------
# 4) discover_capabilities: пустой plugin → []
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_discover_empty_plugin(tmp_path: Path) -> None:
    """Plugin без capability-вызовов → ``[]`` (CLI печатает 'no capabilities')."""
    from tools.discover_plugin_capabilities import (  # type: ignore[import-not-found]
        discover_capabilities,
    )

    plugin = tmp_path / "plugin.py"
    _write_py(plugin, _PLUGIN_EMPTY)

    assert discover_capabilities(plugin) == []


# ---------------------------------------------------------------------------
# 5) discover_capabilities: syntax error → [] (graceful)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_discover_handles_syntax_errors(tmp_path: Path) -> None:
    """SyntaxError в plugin.py → пустой список, без raise."""
    from tools.discover_plugin_capabilities import (  # type: ignore[import-not-found]
        discover_capabilities,
    )

    plugin = tmp_path / "plugin.py"
    _write_py(plugin, _PLUGIN_SYNTAX_ERROR)

    # Не должно бросить исключение.
    caps = discover_capabilities(plugin)
    assert caps == []


# ---------------------------------------------------------------------------
# 6) discover_capabilities: TYPE_CHECKING игнорируется
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_discover_type_checking_ignored(tmp_path: Path) -> None:
    """TYPE_CHECKING-вызовы НЕ попадают в рекомендации."""
    from tools.discover_plugin_capabilities import (  # type: ignore[import-not-found]
        discover_capabilities,
    )

    plugin = tmp_path / "plugin.py"
    _write_py(plugin, _PLUGIN_TYPE_CHECKING_IGNORED)

    caps = discover_capabilities(plugin)
    # phantom.cap из TYPE_CHECKING-блока — НЕ должен попасть.
    assert "phantom.cap" not in caps
    # Реальный runtime-вызов — должен попасть.
    assert "real.cap" in caps


# ---------------------------------------------------------------------------
# 7) discover_capabilities: missing file → []
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_discover_missing_file_returns_empty(tmp_path: Path) -> None:
    """Несуществующий путь → ``[]`` (не бросает)."""
    from tools.discover_plugin_capabilities import (  # type: ignore[import-not-found]
        discover_capabilities,
    )

    assert discover_capabilities(tmp_path / "nope.py") == []


# ---------------------------------------------------------------------------
# 8) _resolve_plugin_path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_resolve_plugin_path_from_directory(tmp_path: Path) -> None:
    """Директория → ``<dir>/plugin.py`` если он существует."""
    from tools.discover_plugin_capabilities import (  # type: ignore[import-not-found]
        _resolve_plugin_path,
    )

    plugin = tmp_path / "plugin.py"
    _write_py(plugin, "x = 1")
    resolved = _resolve_plugin_path(str(tmp_path))
    assert resolved == plugin


@pytest.mark.unit
def test_resolve_plugin_path_direct_file(tmp_path: Path) -> None:
    """Прямой путь к ``.py`` → сам файл (если существует)."""
    from tools.discover_plugin_capabilities import (  # type: ignore[import-not-found]
        _resolve_plugin_path,
    )

    target = tmp_path / "custom_name.py"
    _write_py(target, "x = 1")
    resolved = _resolve_plugin_path(str(target))
    assert resolved == target


@pytest.mark.unit
def test_resolve_plugin_path_missing_dir_returns_none(tmp_path: Path) -> None:
    """Директория без ``plugin.py`` → ``None``."""
    from tools.discover_plugin_capabilities import (  # type: ignore[import-not-found]
        _resolve_plugin_path,
    )

    empty_dir = tmp_path / "no_plugin_here"
    empty_dir.mkdir()
    assert _resolve_plugin_path(str(empty_dir)) is None


# ---------------------------------------------------------------------------
# 9) CLI: --help
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cli_help_message() -> None:
    """``--help`` → exit 0, описание содержит ключевые термины."""
    result = _run_cli("--help")
    assert result.returncode == 0
    combined = result.stdout + result.stderr
    assert "capability" in combined.lower() or "capabilities" in combined.lower()
    # S62 W3: typer-native help использует rich panels; alias-имена могут
    # быть в description но truncated. Достаточно presence of plugin name.
    assert "plugin" in combined.lower() or "AST" in combined


# ---------------------------------------------------------------------------
# 10) CLI: default path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cli_default_path() -> None:
    """CLI без аргументов → exit 0, сканирует ``extensions/example_plugin``."""
    # Запускаем из корня репо (где лежит extensions/example_plugin).
    repo_root = Path(__file__).resolve().parents[3]
    result = _run_cli(cwd=repo_root)
    assert result.returncode == 0, result.stderr
    # В reference-плагине нет gate.* вызовов → "no capabilities discovered".
    assert "example_plugin" in result.stdout
    assert "no capabilities discovered" in result.stdout


# ---------------------------------------------------------------------------
# 11) CLI: synthetic plugin → "discovered capabilities: ..."
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cli_discovered_capabilities_output(tmp_path: Path) -> None:
    """CLI на синтетическом plugin.py → "discovered capabilities: ..."."""
    plugin_dir = tmp_path / "demo_plugin"
    plugin_dir.mkdir()
    _write_py(plugin_dir / "plugin.py", _PLUGIN_WITH_CHECK_TENANT)

    result = _run_cli(str(plugin_dir))
    assert result.returncode == 0, result.stderr
    assert "demo_plugin" in result.stdout
    assert "discovered capabilities:" in result.stdout
    # Алфавитная сортировка: db.read перед mq.publish
    assert "db.read" in result.stdout
    assert "mq.publish" in result.stdout


# ---------------------------------------------------------------------------
# 12) CLI: --recursive (принимается, но игнорируется)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cli_recursive_flag_accepted(tmp_path: Path) -> None:
    """``--recursive`` принимается без ошибки (на текущем slice — TODO)."""
    plugin_dir = tmp_path / "demo_plugin"
    plugin_dir.mkdir()
    _write_py(plugin_dir / "plugin.py", _PLUGIN_EMPTY)

    result = _run_cli(str(plugin_dir), "--recursive")
    assert result.returncode == 0, result.stderr
    assert "demo_plugin" in result.stdout


# ---------------------------------------------------------------------------
# 13) CLI: несуществующий путь → exit 2
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cli_missing_plugin_exits_2(tmp_path: Path) -> None:
    """Путь без ``plugin.py`` → exit 2 + ERROR в stderr."""
    result = _run_cli(str(tmp_path / "nonexistent"))
    assert result.returncode == 2
    assert "ERROR" in result.stderr


# ---------------------------------------------------------------------------
# 14) Backward compat: existing tools tests не сломаны (smoke)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_backward_compat_imports() -> None:
    """Smoke: модуль импортируется и экспортирует публичный API."""
    import tools.discover_plugin_capabilities as mod  # type: ignore[import-not-found]

    # Публичные функции, на которые подписывается CLI.
    assert callable(mod.discover_capabilities)
    assert callable(mod.main)
    # Внутренние хелперы тоже доступны для тестов.
    assert callable(mod._resolve_plugin_path)
    assert callable(mod._is_in_type_checking)
    assert callable(mod._iter_capability_calls)
