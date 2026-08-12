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


def test_orders_capabilities_declare_db_read_write() -> None:
    r"""capability-список содержит db.read/write на orders.

    Cycle-93 (D-AUDIT-9301): ранее тест ожидал отдельный `db.read`
    на `orderkinds` scope, но Cycle-17 (D-AUDIT-1701) удалил его —
    CapabilityGate.declare reject'ит дубликаты (uses `name` как
    bucket-key, без scope), а FK relationship на OrderKind реализован
    через `lazy="joined"` JOIN без отдельного capability check
    (см. ``extensions/core_entities/orders/plugin.toml`` comment block).
    Тест обновлён чтобы отражать актуальный contract.
    """
    manifest = load_plugin_manifest(_MANIFEST_PATH)
    cap_pairs = {(c.name, c.scope) for c in manifest.capabilities}
    assert ("db.read", "orders") in cap_pairs
    assert ("db.write", "orders") in cap_pairs
    assert len(cap_pairs) == 2
