# ruff: noqa: S101
"""Smoke-тесты для in-tree плагина ``extensions/core_entities/files``.

Проверяет:
* parse manifest V11 (ADR-042);
* совместимость с целевой версией ядра ``0.2.x``;
* корректность capabilities (db.read/db.write на ``files``,
  fs.read/fs.write на ``s3://*``);
* импорт shim'а ``src.backend.services.io.files`` отдаёт каноническое
  имя из extensions/ (R-V15-16).
"""

from __future__ import annotations

import warnings
from pathlib import Path

from src.backend.services.plugins.manifest_v11 import load_plugin_manifest

_MANIFEST_PATH = (
    Path(__file__).resolve().parents[4]
    / "extensions"
    / "core_entities"
    / "files"
    / "plugin.toml"
)


def test_files_manifest_loads_and_is_core_compatible() -> None:
    """``plugin.toml`` парсится и совместим с ядром ``0.2.5``."""
    manifest = load_plugin_manifest(_MANIFEST_PATH)
    assert manifest.name == "core_entities_files"
    assert manifest.version == "1.0.0"
    assert manifest.is_compatible_with_core("0.2.5") is True


def test_files_manifest_declares_db_and_fs_capabilities() -> None:
    """Манифест объявляет db.* для ``files`` и fs.* для ``s3://*``."""
    manifest = load_plugin_manifest(_MANIFEST_PATH)
    caps = {(c.name, c.scope) for c in manifest.capabilities}
    assert ("db.read", "files") in caps
    assert ("db.write", "files") in caps
    assert ("fs.read", "s3://*") in caps
    assert ("fs.write", "s3://*") in caps


def test_files_shim_emits_deprecation_warning() -> None:
    """Legacy shim ``src.backend.services.io.files`` всё ещё работает."""
    import importlib
    import sys

    legacy = "src.backend.services.io.files"
    sys.modules.pop(legacy, None)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        mod = importlib.import_module(legacy)
    assert hasattr(mod, "get_file_service")
    assert hasattr(mod, "FileService")
    assert any(
        issubclass(w.category, DeprecationWarning) and "files" in str(w.message).lower()
        for w in caught
    )
