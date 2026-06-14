# ruff: noqa: S101
"""Smoke-тесты для in-tree плагина ``extensions/core_entities/orders``.

Проверяет:
* parse manifest V11 (ADR-042);
* совместимость с ядром ``0.2.x``;
* capabilities: db.read+write на ``orders`` + db.read на ``orderkinds``
  (cross-reference);
* отсутствие shim для services/core/orders.py — миграция Order сервиса
  оставляет legacy as-is (см. extensions/.../services/orders.py
  re-export через resolve_module).
"""

from __future__ import annotations

from pathlib import Path

from src.backend.core.plugin_runtime.manifest import load_plugin_manifest

_MANIFEST_PATH = (
    Path(__file__).resolve().parents[4]
    / "extensions"
    / "core_entities"
    / "orders"
    / "plugin.toml"
)


def test_orders_manifest_loads_and_is_core_compatible() -> None:
    """``plugin.toml`` парсится и совместим с ядром 0.2.x."""
    manifest = load_plugin_manifest(_MANIFEST_PATH)
    assert manifest.name == "core_entities_orders"
    assert manifest.version == "1.0.0"
    assert manifest.requires_core == ">=0.2,<0.3"
    assert manifest.entry_class.endswith(".OrdersPlugin")


def test_orders_capabilities_declare_db_read_write_and_kinds_ref() -> None:
    """capability-список содержит db.read/write на orders + db.read на orderkinds."""
    manifest = load_plugin_manifest(_MANIFEST_PATH)
    cap_pairs = {(c.name, c.scope) for c in manifest.capabilities}
    assert ("db.read", "orders") in cap_pairs
    assert ("db.write", "orders") in cap_pairs
    assert ("db.read", "orderkinds") in cap_pairs
    assert len(cap_pairs) == 3
