# ruff: noqa: S101
"""Smoke-тесты для in-tree плагина ``extensions/core_entities/orderkinds``.

Проверяет:
* parse manifest V11 (ADR-042);
* совместимость с целевой версией ядра ``0.2.x``;
* корректность объявленных capabilities (db.read/db.write на ``orderkinds``);
* импорт shim'а ``src.backend.services.core.orderkinds`` отдаёт
  каноническое имя из extensions/ (R-V15-16).
"""

from __future__ import annotations

import warnings
from pathlib import Path

from src.backend.core.plugin_runtime.manifest import load_plugin_manifest

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


def test_orderkinds_shim_emits_deprecation_warning() -> None:
    """Legacy shim ``src.backend.services.core.orderkinds`` всё ещё работает."""
    import importlib

    legacy = "src.backend.services.core.orderkinds"
    # Сбрасываем кеш, чтобы warning стрельнул на import-е.
    import sys

    sys.modules.pop(legacy, None)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        mod = importlib.import_module(legacy)
    # Проверяем, что shim предоставляет ту же поверхность.
    assert hasattr(mod, "get_order_kind_service")
    assert hasattr(mod, "OrderKindService")
    # И DeprecationWarning был эмитирован.
    assert any(
        issubclass(w.category, DeprecationWarning)
        and "orderkinds" in str(w.message).lower()
        for w in caught
    )
