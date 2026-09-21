"""Tests for ``StreamlitPageRegistry`` auto-seed (Sprint 175+ P1.1)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.backend.core.registry_explorer import (
    RegistryExplorer,
    StreamlitPageRegistry,
    auto_seed_from_project,
    get_page_registry,
    get_registry_explorer,
    reset_page_registry,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_page_registry()
    get_registry_explorer().clear()
    yield
    reset_page_registry()
    get_registry_explorer().clear()


class TestStreamlitPageRegistryInit:
    def test_init(self) -> None:
        explorer = RegistryExplorer()
        reg = StreamlitPageRegistry(explorer=explorer)
        assert reg.explorer is explorer
        assert reg.auto_seeded is False
        assert reg.errors == []


class TestAutoSeedIdempotent:
    def test_idempotent_without_force(self) -> None:
        explorer = RegistryExplorer()
        reg = StreamlitPageRegistry(
            explorer=explorer,
            extensions_dir=Path("/nonexistent"),
            routes_dir=Path("/nonexistent"),
        )
        # First call returns 0 (no items found).
        n1 = reg.auto_seed()
        assert n1 == 0
        assert reg.auto_seeded is True
        # Second call without force returns 0 (idempotent).
        n2 = reg.auto_seed()
        assert n2 == 0

    def test_force_rerun(self) -> None:
        explorer = RegistryExplorer()
        reg = StreamlitPageRegistry(
            explorer=explorer, extensions_dir=Path("/nonexistent")
        )
        reg.auto_seed()
        # Force re-run.
        n = reg.auto_seed(force=True)
        assert n == 0


class TestAutoSeedFromExtensions:
    def test_seed_with_fake_plugin_toml(self, tmp_path: Path) -> None:
        """Auto-seed from extensions/ subdir with plugin.toml."""
        ext_dir = tmp_path / "extensions"
        ext_dir.mkdir()
        (ext_dir / "my_plugin").mkdir()
        (ext_dir / "my_plugin" / "plugin.toml").write_text(
            textwrap.dedent("""
                name = "my-plugin"
                version = "1.0.0"
                category = "http"
                auth = "bearer"
            """).strip(),
            encoding="utf-8",
        )

        explorer = RegistryExplorer()
        reg = StreamlitPageRegistry(explorer=explorer, extensions_dir=ext_dir)
        n = reg.auto_seed(force=True)
        assert n == 1
        # Verify connector was registered.
        c = explorer.find_connector("my-plugin")
        assert c is not None
        assert c.category == "http"
        assert c.auth == "bearer"


class TestAutoSeedFromRoutes:
    def test_seed_with_fake_route_toml(self, tmp_path: Path) -> None:
        r_dir = tmp_path / "routes"
        r_dir.mkdir()
        (r_dir / "my_route").mkdir()
        (r_dir / "my_route" / "route.toml").write_text(
            textwrap.dedent("""
                id = "my-route"
                source = "timer:60s|api=skb"
                owner = "team-x"
            """).strip(),
            encoding="utf-8",
        )

        explorer = RegistryExplorer()
        reg = StreamlitPageRegistry(explorer=explorer, routes_dir=r_dir)
        n = reg.auto_seed(force=True)
        assert n == 1
        r = explorer.find_route("my-route")
        assert r is not None
        assert r.source == "timer:60s|api=skb"
        assert r.owner == "team-x"


class TestAutoSeedErrors:
    def test_errors_collected(self) -> None:
        """Errors are collected but don't raise."""
        explorer = RegistryExplorer()
        reg = StreamlitPageRegistry(
            explorer=explorer,
            extensions_dir=Path("/nonexistent"),
            routes_dir=Path("/nonexistent"),
        )
        reg.auto_seed(force=True)
        # No errors expected (paths don't exist, just skipped).
        assert reg.errors == []

    def test_invalid_toml_handled(self, tmp_path: Path) -> None:
        """Invalid plugin.toml не ломает весь auto-seed."""
        ext_dir = tmp_path / "extensions"
        ext_dir.mkdir()
        (ext_dir / "bad_plugin").mkdir()
        (ext_dir / "bad_plugin" / "plugin.toml").write_text(
            "name = invalid [unclosed", encoding="utf-8"
        )
        # Add a good one.
        (ext_dir / "good_plugin").mkdir()
        (ext_dir / "good_plugin" / "plugin.toml").write_text(
            'name = "good"', encoding="utf-8"
        )

        explorer = RegistryExplorer()
        reg = StreamlitPageRegistry(explorer=explorer, extensions_dir=ext_dir)
        n = reg.auto_seed(force=True)
        # At least 1 registered (the good one).
        assert n >= 1


class TestModuleLevelFunctions:
    def test_auto_seed_from_project(self) -> None:
        """Standalone auto-seed function returns registry."""
        reg = auto_seed_from_project(extensions_dir=Path("/nonexistent"))
        assert isinstance(reg, StreamlitPageRegistry)
        assert reg.auto_seeded is True

    def test_get_page_registry_singleton(self) -> None:
        r1 = get_page_registry()
        r2 = get_page_registry()
        assert r1 is r2

    def test_reset_page_registry(self) -> None:
        r1 = get_page_registry()
        reset_page_registry()
        r2 = get_page_registry()
        assert r1 is not r2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import registry_explorer

        # Should include new StreamlitPageRegistry exports.
        names = registry_explorer.__all__
        assert "StreamlitPageRegistry" in names
        assert "auto_seed_from_project" in names
        assert "get_page_registry" in names
        assert "reset_page_registry" in names
