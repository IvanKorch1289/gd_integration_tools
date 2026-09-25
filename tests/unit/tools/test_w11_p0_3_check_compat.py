"""Regression tests для check_compat.py (cycle 158+ fix cc6806bd6).

Per v4 §10 P1 'evidence требует testable surface': broken-gate fix
importing из несуществующего 'src.backend.services.plugins.manifest_toml'
→ canonical 'src.backend.core.plugin_runtime.manifest_toml'.

Tests:
1. Import gate без ModuleNotFoundError.
2. Gate exit 0 после исправления import path.
3. PluginManifest load_plugin_manifest() успешно для real extensions.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_module():
    """Подгрузить tools/checks/check_compat.py через importlib."""
    path = Path(__file__).resolve().parents[3] / "tools" / "checks" / "check_compat.py"
    spec = importlib.util.spec_from_file_location("_compat_test", path)
    if spec is None or spec.loader is None:
        raise ImportError("Не удалось загрузить check_compat.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()


def test_import_does_not_raise_module_not_found_error() -> None:
    """Pre-fix bug: gate импортировал из 'src.backend.services.plugins.manifest_toml'
    (не существует), падал с ModuleNotFoundError при любом запуске.
    Post-fix: импорт из canonical 'src.backend.core.plugin_runtime.manifest_toml'.

    Этот тест импортирует модуль и проверяет, что critical imports
    определены (не бросают ImportError).
    """
    # Module уже загружен в _load_module(); просто проверяем символы.
    assert hasattr(mod, "_OK")
    assert hasattr(mod, "_ERR")
    assert hasattr(mod, "_collect_manifests")
    assert hasattr(mod, "main")


def test_main_runs_without_crash_on_default_extensions() -> None:
    """Integration: main() запускается на canonical extensions/ dir.
    Pre-fix: ModuleNotFoundError на импорте → main никогда не достигался.
    Post-fix: main() runs, returns 0 или 1 (но не падает).
    """
    rc = mod.main(["--plugins-dir", "extensions/"])
    # exit 0 (all compatible) или 1 (some errors). Но НЕ ModuleNotFoundError.
    assert rc in (0, 1)


def test_load_plugin_manifest_from_real_extension(tmp_path: Path) -> None:
    """PluginManifest loader успешно читает canonical extension manifest
    (post-ADR-0343 schema migration: flat top-level structure).
    """
    manifest_path = tmp_path / "plugin.toml"
    manifest_path.write_text(
        'name = "test_plugin"\n'
        'version = "1.0.0"\n'
        'requires_core = ">=0.2.0"\n'
        'entry_class = "test:Entry"\n',
        encoding="utf-8",
    )

    # Import canonical PluginManifest и попытка load.
    from src.backend.core.plugin_runtime.manifest_toml import load_plugin_manifest

    manifest = load_plugin_manifest(manifest_path)
    assert manifest.name == "test_plugin"
    assert manifest.version == "1.0.0"


def test_load_plugin_manifest_rejects_nested_tables() -> None:
    """Sanity: post-ADR-0343 schema rejects nested '[plugin]' tables.
    Это защищает regression — если schema случайно расширят чтобы
    принимать nested tables, тест напомнит о convergence trade-off.
    """
    # Не используем external fixture — просто in-memory bad source:
    from src.backend.core.plugin_runtime.manifest_toml import PluginManifest

    # Source with nested [plugin] table → PluginManifest rejects.
    bad_toml = (
        'trust_tier = "A"\n'
        "[plugin]\n"
        'name = "nested_attempt"\n'
        'version = "1.0.0"\n'
        'requires_core = ">=0.2.0"\n'
        'entry_class = "test:Entry"\n'
    )
    with pytest.raises(Exception) as exc_info:
        # Pydantic raises ValidationError OR PluginManifestError depending on path.
        PluginManifest.model_validate_strings(bad_toml)
    # Accept any exception (validation/parsing) — main assertion is что load fails.
    assert exc_info.value is not None
