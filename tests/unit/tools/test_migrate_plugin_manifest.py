# ruff: noqa: S101
"""Тесты tools/migrate_plugin_manifest.py."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

# Добавляем tools/ в sys.path, потому что это CLI-скрипт, не пакет.
_TOOLS = Path(__file__).resolve().parents[3] / "tools"
sys.path.insert(0, str(_TOOLS))

import migrate_plugin_manifest as mod  # noqa: E402

from src.backend.services.plugins.manifest_v11 import load_plugin_manifest  # noqa: E402


def _legacy_yaml(content: str) -> str:
    return textwrap.dedent(content).lstrip()


def test_migrate_minimal(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "demo"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yaml").write_text(
        _legacy_yaml(
            """
            name: demo
            version: "0.5.0"
            entry_class: demo.plugin.Plugin
            actions:
              - demo.echo
              - demo.ping
            repositories:
              - demo_repo
            processors:
              - demo_proc
            config:
              timeout_ms: 30000
              enabled: true
            """
        ),
        encoding="utf-8",
    )
    target, rendered = mod.migrate_one(
        plugin_dir, core_spec=">=0.2,<0.3", overwrite=False, dry_run=False
    )
    assert target == plugin_dir / "plugin.toml"
    assert target.is_file()

    parsed = load_plugin_manifest(target)
    assert parsed.name == "demo"
    assert parsed.version == "0.5.0"
    assert parsed.requires_core == ">=0.2,<0.3"
    assert parsed.entry_class == "demo.plugin.Plugin"
    assert parsed.tenant_aware is False
    assert parsed.provides.actions == ("demo.echo", "demo.ping")
    assert parsed.provides.repositories == ("demo_repo",)
    assert parsed.provides.processors == ("demo_proc",)
    assert parsed.config == {"timeout_ms": 30000, "enabled": True}
    # Capability-секция — placeholder через TODO-комментарий.
    assert "TODO" in rendered
    assert parsed.capabilities == ()


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "demo"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yaml").write_text(
        'name: demo\nversion: "1.0.0"\nentry_class: demo.plugin.X\n', encoding="utf-8"
    )
    target, rendered = mod.migrate_one(
        plugin_dir, core_spec=">=0.2,<0.3", overwrite=False, dry_run=True
    )
    assert not target.exists()
    assert 'name = "demo"' in rendered


def test_overwrite_required(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "demo"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yaml").write_text(
        'name: demo\nversion: "1.0.0"\nentry_class: demo.plugin.X\n', encoding="utf-8"
    )
    (plugin_dir / "plugin.toml").write_text("# existing\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        mod.migrate_one(
            plugin_dir, core_spec=">=0.2,<0.3", overwrite=False, dry_run=False
        )
    # с overwrite — успех.
    mod.migrate_one(plugin_dir, core_spec=">=0.2,<0.3", overwrite=True, dry_run=False)
    assert (
        (plugin_dir / "plugin.toml")
        .read_text(encoding="utf-8")
        .startswith('name = "demo"')
    )


def test_missing_legacy_manifest(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "absent"
    plugin_dir.mkdir()
    with pytest.raises(FileNotFoundError):
        mod.migrate_one(
            plugin_dir, core_spec=">=0.2,<0.3", overwrite=False, dry_run=False
        )


def test_render_toml_unsupported_value() -> None:
    """Сложный объект в config даёт явный TypeError, не silent skip."""
    with pytest.raises(TypeError, match="Unsupported config value"):
        mod.render_toml(
            name="x",
            version="1.0.0",
            requires_core=">=0.1",
            entry_class="x.X",
            description=None,
            actions=(),
            repositories=(),
            processors=(),
            config={"obj": object()},  # not int/float/bool/str/list
        )


def test_main_entry(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plugin_dir = tmp_path / "demo"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yaml").write_text(
        'name: demo\nversion: "1.0.0"\nentry_class: demo.plugin.X\n', encoding="utf-8"
    )
    rc = mod.main([str(plugin_dir)])
    assert rc == 0
    assert (plugin_dir / "plugin.toml").is_file()
    captured = capsys.readouterr()
    assert "WROTE" in captured.out
