# ruff: noqa: S101
"""Smoke-тест для in-tree reference-плагина ``extensions/example_plugin``.

Проверяет, что манифест V11 (ADR-042) парсится и совместим с целевой
версией ядра ``0.2.x``.
"""

from __future__ import annotations

from pathlib import Path

from src.backend.services.plugins.manifest_v11 import load_plugin_manifest

_MANIFEST_PATH = (
    Path(__file__).resolve().parents[4]
    / "extensions"
    / "example_plugin"
    / "plugin.toml"
)


def test_example_plugin_manifest_loads_and_is_core_compatible() -> None:
    """``plugin.toml`` парсится и совместим с ядром ``0.2.5``."""
    manifest = load_plugin_manifest(_MANIFEST_PATH)
    assert manifest.name == "example_plugin"
    assert manifest.is_compatible_with_core("0.2.5") is True
