"""Unit-тесты PluginCodegen (Sprint 9 K5 W3)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]


def _load_codegen():
    """Загружает tools/codegen_plugin.py напрямую (минуя package import)."""
    src = _ROOT / "tools" / "codegen_plugin.py"
    spec = importlib.util.spec_from_file_location("codegen_plugin_mod", src)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["codegen_plugin_mod"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.PluginCodegen


PluginCodegen = _load_codegen()


@pytest.fixture
def codegen(tmp_path: Path) -> PluginCodegen:
    return PluginCodegen(target_dir=tmp_path)


def test_scaffold_creates_plugin_dir(codegen: PluginCodegen, tmp_path: Path) -> None:
    plugin = codegen.scaffold(name="my_plugin")
    assert plugin == tmp_path / "my_plugin"
    assert plugin.is_dir()
    assert (plugin / "plugin.toml").exists()
    assert (plugin / "plugin.py").exists()
    assert (plugin / "functions").is_dir()
    assert (plugin / "routes").is_dir()
    assert (plugin / "workflows").is_dir()
    assert (plugin / "tests").is_dir()


def test_scaffold_with_features_writes_actions(codegen: PluginCodegen) -> None:
    plugin = codegen.scaffold(name="my_plugin", features=["ping", "echo"])
    manifest = (plugin / "plugin.toml").read_text()
    assert '"my_plugin.ping"' in manifest
    assert '"my_plugin.echo"' in manifest


def test_scaffold_with_capabilities(codegen: PluginCodegen) -> None:
    plugin = codegen.scaffold(
        name="my_plugin", capabilities=["mq.publish:topic.events.*", "http.outbound"]
    )
    manifest = (plugin / "plugin.toml").read_text()
    assert 'name = "mq.publish"' in manifest
    assert 'scope = "topic.events.*"' in manifest
    assert 'name = "http.outbound"' in manifest


def test_scaffold_duplicate_raises(codegen: PluginCodegen) -> None:
    codegen.scaffold(name="my_plugin")
    with pytest.raises(FileExistsError):
        codegen.scaffold(name="my_plugin")


def test_scaffold_with_overwrite(codegen: PluginCodegen) -> None:
    codegen.scaffold(name="my_plugin")
    codegen.scaffold(name="my_plugin", overwrite=True)  # no raise


def test_scaffold_invalid_name_raises(codegen: PluginCodegen) -> None:
    with pytest.raises(ValueError):
        codegen.scaffold(name="My-Bad-Name")


def test_list_existing_empty(codegen: PluginCodegen) -> None:
    assert codegen.list_existing() == []


def test_list_existing_after_scaffold(codegen: PluginCodegen) -> None:
    codegen.scaffold(name="alpha")
    codegen.scaffold(name="beta")
    assert codegen.list_existing() == ["alpha", "beta"]


def test_default_with_frontend(tmp_path: Path) -> None:
    codegen = PluginCodegen(target_dir=tmp_path, default_with_frontend=True)
    plugin = codegen.scaffold(name="ui_plugin")
    assert (plugin / "frontend" / "pages").is_dir()
