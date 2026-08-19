# ruff: noqa: S101
"""Smoke-тесты для in-tree плагина ``extensions/core_entities/users``.

Проверяет:
* parse manifest V11 (ADR-042);
* совместимость с целевой версией ядра ``0.2.x``;
* корректность объявленных capabilities (db.read/db.write на ``users``).
"""

from __future__ import annotations

from pathlib import Path

from src.backend.core.api import load_plugin_manifest

_MANIFEST_PATH = (
    Path(__file__).resolve().parents[4]
    / "extensions"
    / "core_entities"
    / "users"
    / "plugin.toml"
)


def test_users_manifest_loads_and_is_core_compatible() -> None:
    """``plugin.toml`` парсится и совместим с ядром 0.2.x."""
    manifest = load_plugin_manifest(_MANIFEST_PATH)
    assert manifest.name == "core_entities_users"
    assert manifest.version == "1.0.0"
    assert manifest.requires_core == ">=0.2,<0.3"
    assert manifest.entry_class.endswith(".UsersPlugin")


def test_users_capabilities_declare_db_read_and_write() -> None:
    """capability-список ровно ``[db.read, db.write]`` на scope=users."""
    manifest = load_plugin_manifest(_MANIFEST_PATH)
    cap_pairs = {(c.name, c.scope) for c in manifest.capabilities}
    assert ("db.read", "users") in cap_pairs
    assert ("db.write", "users") in cap_pairs
    assert len(cap_pairs) == 2
