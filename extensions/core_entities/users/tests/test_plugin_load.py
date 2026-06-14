# ruff: noqa: S101
"""Smoke-тесты для in-tree плагина ``extensions/core_entities/users``.

Проверяет:
* parse manifest V11 (ADR-042);
* совместимость с целевой версией ядра ``0.2.x``;
* корректность объявленных capabilities (db.read/db.write на ``users``);
* импорт shim'а ``src.backend.services.core.users`` отдаёт каноническое
  имя из extensions/ (R-V15-16) и эмитит DeprecationWarning.
"""

from __future__ import annotations

import warnings
from pathlib import Path

from src.backend.core.plugin_runtime.manifest import load_plugin_manifest

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


def test_users_shim_module_emits_deprecation_warning() -> None:
    """``services.core.users`` остался shim'ом + DeprecationWarning."""
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        import importlib

        importlib.reload(importlib.import_module("src.backend.services.core.users"))

    assert any(
        issubclass(w.category, DeprecationWarning)
        and "extensions.core_entities.users" in str(w.message)
        for w in captured
    )
