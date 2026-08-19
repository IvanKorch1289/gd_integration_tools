# ruff: noqa: S101
"""Smoke-тесты для in-tree плагина ``extensions/core_entities/orderkinds``.

Проверяет:
* parse manifest V11 (ADR-042);
* совместимость с целевой версией ядра ``0.2.x``;
* корректность объявленных capabilities (db.read/db.write на ``orderkinds``).
"""

from __future__ import annotations

from pathlib import Path

from src.backend.core.api import load_plugin_manifest

_MANIFEST_PATH = (
    Path(__file__).resolve().parents[4]
    / "extensions"
    / "core_entities"
    / "orderkinds"
    / "plugin.toml"
)


def test_orderkinds_manifest_loads_and_is_core_compatible() -> None:
    """``plugin.toml`` парсится и совместим с ядром ``0.2.5``."""
    manifest = load_plugin_manifest(_MANIFEST_PATH)
    assert manifest.name == "core_entities_orderkinds"
    assert manifest.version == "1.0.0"
    assert manifest.is_compatible_with_core("0.2.5") is True


def test_orderkinds_manifest_declares_db_capabilities() -> None:
    """Манифест объявляет ``db.read``/``db.write`` на ресурсе ``orderkinds``."""
    manifest = load_plugin_manifest(_MANIFEST_PATH)
    caps = {(c.name, c.scope) for c in manifest.capabilities}
    assert ("db.read", "orderkinds") in caps
    assert ("db.write", "orderkinds") in caps
