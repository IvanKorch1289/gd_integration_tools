# ruff: noqa: S101
"""Unit-тесты ``tools/codegen_plugin.py`` (Wave K5/devx-codegen)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

_TOOLS = Path(__file__).resolve().parents[3] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import codegen_plugin  # noqa: E402


@pytest.fixture
def isolated_extensions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Изолированный extensions/ — codegen пишет туда, не в реальный."""
    fake = tmp_path / "extensions"
    fake.mkdir()
    monkeypatch.setattr(codegen_plugin, "EXTENSIONS_DIR", fake)
    return fake


def test_renders_full_layout(isolated_extensions: Path) -> None:
    """Полный layout: plugin.toml + plugin.py + functions/ + tests/."""
    cg = codegen_plugin.PluginCodegen(target_dir=isolated_extensions)
    plugin_dir = cg.scaffold(
        name="acme_demo",
        features=["ping", "echo"],
        capabilities=["mq.publish"],
        with_frontend=False,
    )

    assert (plugin_dir / "plugin.toml").is_file()
    assert (plugin_dir / "plugin.py").is_file()
    assert (plugin_dir / "README.md").is_file()
    assert (plugin_dir / "functions").is_dir()
    assert (plugin_dir / "tests").is_dir()


def test_plugin_toml_emits_capability_block(isolated_extensions: Path) -> None:
    """plugin.toml содержит [[capabilities]] секцию."""
    cg = codegen_plugin.PluginCodegen(target_dir=isolated_extensions)
    cg.scaffold(
        name="cap_demo",
        features=["ping"],
        capabilities=["db.read.orders"],
        with_frontend=False,
    )
    toml = (isolated_extensions / "cap_demo" / "plugin.toml").read_text(
        encoding="utf-8"
    )
    assert "[[capabilities]]" in toml
    assert 'name = "db.read.orders"' in toml
    assert '"cap_demo.ping"' in toml  # action name from features


def test_overwrite_protects_existing(isolated_extensions: Path) -> None:
    """Без overwrite повторный запуск падает с FileExistsError."""
    cg = codegen_plugin.PluginCodegen(
        target_dir=isolated_extensions, default_overwrite=False
    )
    cg.scaffold(name="test_one", features=["a"], capabilities=[], with_frontend=False)
    with pytest.raises(FileExistsError):
        cg.scaffold(name="test_one", features=["a"], capabilities=[], with_frontend=False)


def test_overwrite_allows_rewrite(isolated_extensions: Path) -> None:
    """С default_overwrite=True повторный запуск проходит."""
    cg = codegen_plugin.PluginCodegen(
        target_dir=isolated_extensions, default_overwrite=True
    )
    cg.scaffold(name="test_two", features=["a"], capabilities=[], with_frontend=False)
    cg.scaffold(name="test_two", features=["a"], capabilities=[], with_frontend=False)
    assert (isolated_extensions / "test_two" / "plugin.toml").is_file()


def test_cli_main(isolated_extensions: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI main возвращает 0 и пишет Created plugin."""
    rc = codegen_plugin.main(
        [
            "--name",
            "cli_demo",
            "--features",
            "ping,echo",
            "--capabilities",
            "mq.publish",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "Created plugin:" in out
    assert "cli_demo" in out
    plugin_dir = isolated_extensions / "cli_demo"
    assert (plugin_dir / "plugin.toml").is_file()


def test_cleanup(isolated_extensions: Path) -> None:
    """Smoke: tmp directory можно полностью удалить."""
    cg = codegen_plugin.PluginCodegen(target_dir=isolated_extensions)
    cg.scaffold(
        name="cleanup_demo", features=["a"], capabilities=[], with_frontend=False
    )
    shutil.rmtree(isolated_extensions / "cleanup_demo")
