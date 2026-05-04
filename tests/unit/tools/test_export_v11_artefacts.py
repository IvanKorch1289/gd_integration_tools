# ruff: noqa: S101
"""Тесты tools/export_v11_artefacts.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[3] / "tools"
sys.path.insert(0, str(_TOOLS))

import export_v11_artefacts as mod  # noqa: E402


def test_plugin_schema_export_valid_json(tmp_path: Path) -> None:
    target = tmp_path / "plugin.toml.schema.json"
    out = mod.export_plugin_schema(target)
    assert out == target
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["title"] == "PluginManifestV11"
    # Обязательные поля присутствуют.
    required = set(payload["required"])
    assert {"name", "version", "requires_core", "entry_class"} <= required


def test_route_schema_export_valid_json(tmp_path: Path) -> None:
    target = tmp_path / "route.toml.schema.json"
    out = mod.export_route_schema(target)
    assert out == target
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["title"] == "RouteManifestV11"
    required = set(payload["required"])
    assert {"name", "version", "requires_core", "pipelines"} <= required


def test_capability_catalog_export(tmp_path: Path) -> None:
    target = tmp_path / "capabilities.md"
    out = mod.export_capability_catalog(target)
    text = out.read_text(encoding="utf-8")
    # Все имена v0-каталога в таблице.
    for name in (
        "db.read",
        "db.write",
        "secrets.read",
        "net.outbound",
        "fs.read",
        "mq.publish",
        "cache.write",
        "workflow.start",
        "llm.invoke",
    ):
        assert f"`{name}`" in text, f"missing {name}"


def test_export_is_deterministic(tmp_path: Path) -> None:
    """Двойной экспорт даёт байт-в-байт одинаковый артефакт."""
    a = tmp_path / "a.schema.json"
    b = tmp_path / "b.schema.json"
    mod.export_plugin_schema(a)
    mod.export_plugin_schema(b)
    assert a.read_bytes() == b.read_bytes()


def test_main_all_writes_default_artefacts() -> None:
    """``main(["all"])`` дописывает дефолтные артефакты в репозитории."""
    rc = mod.main(["all"])
    assert rc == 0
    assert (mod.SCHEMAS_DIR / "plugin.toml.schema.json").is_file()
    assert (mod.SCHEMAS_DIR / "route.toml.schema.json").is_file()
    assert mod.CAPABILITIES_MD.is_file()


def test_main_single_target(capsys) -> None:
    """``main(["plugin-schema"])`` пишет один файл."""
    rc = mod.main(["plugin-schema"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "plugin.toml.schema.json" in out
