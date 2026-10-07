"""Smoke-тест для in-tree reference-плагина ``extensions/example_plugin``.

Проверяет, что манифест V11 (ADR-042) парсится и совместим с целевой
версией ядра ``0.2.x``.
"""

from __future__ import annotations

from pathlib import Path

from src.backend.core.plugin_runtime.manifest_toml import load_plugin_manifest

_MANIFEST_PATH = (
    Path(__file__).resolve().parents[4]
    / "extensions"
    / "example_plugin"
    / "plugin.toml"
)


def test_example_plugin_manifest_loads_and_is_core_compatible() -> None:
    """``plugin.toml`` парсится и совместим с текущей версией ядра.

    Манифест объявляет ``requires_core = ">=0.20,<0.21"``. Раньше тест
    сверялся с ядром ``0.2.5``, что проходило только пока в манифесте стоял
    диапазон ``>=0.2,<0.3``; после нормализации диапазонов ядро сверяется с
    фактической версией дистрибутива.
    """
    from importlib.metadata import version

    manifest = load_plugin_manifest(_MANIFEST_PATH)
    assert manifest.name == "example_plugin"
    core_version = version("gd_advanced_tools")
    assert manifest.is_compatible_with_core(core_version) is True, (
        f"example_plugin requires_core={manifest.requires_core!r} "
        f"несовместим с версией ядра {core_version!r}"
    )
