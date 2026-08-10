"""Cycle-15 (D-AUDIT-1502): tests for models_discovery helper.

Coverage:
- Empty / missing extensions_dir → returns []
- One valid manifest with models_module → returned
- Multiple valid manifests → returned in sorted order
- Invalid TOML → logged warning, skipped (partial discovery)
- Manifest without models_module → returned (caller filters)
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.backend.services.plugins.loader import load_plugin_manifests_for_migrations


def _write_plugin(
    root: Path,
    *,
    name: str,
    manifest_body: str | None = None,
) -> Path:
    """Создать минимальный ``extensions/<name>/plugin.toml``."""
    pkg = root / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    body = manifest_body or textwrap.dedent(
        f"""
        name = "{name}"
        version = "1.0.0"
        requires_core = ">=0.2,<0.3"
        entry_class = "ext.{name}.Plugin"
        models_module = ["ext.{name}.domain.models"]
        """
    )
    (pkg / "plugin.toml").write_text(body, encoding="utf-8")
    return pkg / "plugin.toml"


class TestLoadPluginManifestsForMigrations:
    def test_no_extensions_dir(self, tmp_path: Path) -> None:
        """Cycle-15 (D-AUDIT-1502): missing dir → empty list, no raise."""
        assert load_plugin_manifests_for_migrations(tmp_path / "missing") == []

    def test_empty_extensions_dir(self, tmp_path: Path) -> None:
        """Cycle-15 (D-AUDIT-1502): пустой каталог → пустой результат."""
        assert load_plugin_manifests_for_migrations(tmp_path) == []

    def test_single_valid_manifest(self, tmp_path: Path) -> None:
        """Cycle-15 (D-AUDIT-1502): один плагин с models_module."""
        _write_plugin(tmp_path, name="alpha")
        results = load_plugin_manifests_for_migrations(tmp_path)
        assert len(results) == 1
        manifest, path = results[0]
        assert manifest.name == "alpha"
        assert manifest.models_module == ("ext.alpha.domain.models",)
        assert path.parent.name == "alpha"

    def test_multiple_manifests_sorted(self, tmp_path: Path) -> None:
        """Cycle-15 (D-AUDIT-1502): порядок детерминирован (sorted)."""
        for name in ("zebra", "alpha", "mango"):
            _write_plugin(tmp_path, name=name)
        results = load_plugin_manifests_for_migrations(tmp_path)
        names = [r.manifest.name for r in results]
        assert names == ["alpha", "mango", "zebra"]

    def test_invalid_toml_skipped(self, tmp_path: Path) -> None:
        """Cycle-15 (D-AUDIT-1502): битый TOML — warning + skip, partial discovery."""
        _write_plugin(tmp_path, name="good")
        bad = tmp_path / "bad"
        bad.mkdir()
        (bad / "plugin.toml").write_text("name = 'x\nnot valid toml", encoding="utf-8")
        results = load_plugin_manifests_for_migrations(tmp_path)
        names = [r.manifest.name for r in results]
        assert "good" in names
        assert "bad" not in names

    def test_manifest_without_models_module_returned(self, tmp_path: Path) -> None:
        """Cycle-15 (D-AUDIT-1502): пустой models_module — manifest в выдаче,
        downstream сам решает фильтровать.
        """
        _write_plugin(
            tmp_path,
            name="schemas_only",
            manifest_body=textwrap.dedent(
                """
                name = "schemas_only"
                version = "1.0.0"
                requires_core = ">=0.2,<0.3"
                entry_class = "ext.schemas_only.Entry"
                """
            ),
        )
        results = load_plugin_manifests_for_migrations(tmp_path)
        assert len(results) == 1
        assert results[0].manifest.models_module == ()

    def test_subdir_without_plugin_toml_skipped(self, tmp_path: Path) -> None:
        """Cycle-15 (D-AUDIT-1502): каталог без plugin.toml пропускается."""
        pkg = tmp_path / "no_manifest"
        pkg.mkdir()
        (pkg / "README.md").write_text("# nope", encoding="utf-8")
        assert load_plugin_manifests_for_migrations(tmp_path) == []


@pytest.mark.parametrize(
    "manifest_body",
    [
        # missing requires_core
        'name = "x"\nversion = "1.0.0"\nentry_class = "ext.x.Plugin"\n',
        # missing entry_class
        'name = "x"\nversion = "1.0.0"\nrequires_core = ">=0.1"\n',
    ],
)
def test_schema_violation_skipped(tmp_path: Path, manifest_body: str) -> None:
    """Cycle-15 (D-AUDIT-1502): schema violation → skip с warning."""
    pkg = tmp_path / "bad_schema"
    pkg.mkdir()
    (pkg / "plugin.toml").write_text(manifest_body, encoding="utf-8")
    assert load_plugin_manifests_for_migrations(tmp_path) == []
