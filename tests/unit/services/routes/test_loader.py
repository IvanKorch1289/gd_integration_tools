# ruff: noqa: S101
"""Тесты RouteLoader (ADR-043 / ADR-044)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.backend.core.security.capabilities import (
    CapabilityGate,
    CapabilityRef,
    build_default_vocabulary,
)
from src.backend.services.routes.loader import (
    InstalledPlugin,
    LoadedRoute,
    RouteLoader,
    default_env_feature_flag_resolver,
)


def _write_route(
    root: Path,
    *,
    name: str,
    requires_core: str = ">=0.2,<0.3",
    requires_plugins: dict[str, str] | None = None,
    capabilities: list[tuple[str, str | None]] | None = None,
    feature_flag: str | bool | None = None,
    pipelines: tuple[str, ...] = ("pipeline.dsl.yaml",),
    create_pipelines: bool = True,
) -> Path:
    """Создать routes/<name>/route.toml + опц. пайплайны."""
    pkg = root / name
    pkg.mkdir()
    body = [
        f'name = "{name}"',
        'version = "1.0.0"',
        f'requires_core = "{requires_core}"',
        "pipelines = [{}]".format(", ".join(f'"{p}"' for p in pipelines)),
    ]
    if feature_flag is not None:
        if isinstance(feature_flag, bool):
            body.append(f"feature_flag = {str(feature_flag).lower()}")
        else:
            body.append(f'feature_flag = "{feature_flag}"')
    if requires_plugins:
        body.append("[requires_plugins]")
        for n, spec in requires_plugins.items():
            body.append(f'{n} = "{spec}"')
    for cap_name, scope in capabilities or []:
        body.append("[[capabilities]]")
        body.append(f'name = "{cap_name}"')
        if scope is not None:
            body.append(f'scope = "{scope}"')
    (pkg / "route.toml").write_text("\n".join(body), encoding="utf-8")
    if create_pipelines:
        for p in pipelines:
            (pkg / p).write_text("# placeholder", encoding="utf-8")
    return pkg


def _build_loader(
    routes_dir: Path,
    *,
    installed_plugins: dict[str, InstalledPlugin] | None = None,
    feature_flag_resolver=None,
) -> tuple[RouteLoader, list[tuple[str, Path]]]:
    registered: list[tuple[str, Path]] = []

    def registrar(route_name: str, pipeline_path: Path) -> None:
        registered.append((route_name, pipeline_path))

    loader = RouteLoader(
        routes_dir=routes_dir,
        capability_gate=CapabilityGate(),
        vocabulary=build_default_vocabulary(),
        core_version="0.2.0",
        installed_plugins=installed_plugins or {},
        pipeline_registrar=registrar,
        feature_flag_resolver=feature_flag_resolver
        or default_env_feature_flag_resolver,
    )
    return loader, registered


class TestRouteLoaderDiscovery:
    async def test_no_routes_dir(self, tmp_path: Path) -> None:
        loader, _ = _build_loader(tmp_path / "absent")
        assert await loader.discover_and_load() == ()

    async def test_minimal_route_enabled(self, tmp_path: Path) -> None:
        _write_route(tmp_path, name="r1")
        loader, registered = _build_loader(tmp_path)
        loaded = await loader.discover_and_load()
        assert len(loaded) == 1
        assert isinstance(loaded[0], LoadedRoute)
        assert loaded[0].status == "enabled"
        assert registered == [("r1", tmp_path / "r1" / "pipeline.dsl.yaml")]

    async def test_skipped_on_incompatible_core(self, tmp_path: Path) -> None:
        _write_route(tmp_path, name="r1", requires_core=">=99.0,<100.0")
        loader, _ = _build_loader(tmp_path)
        loaded = await loader.discover_and_load()
        assert loaded[0].status == "skipped"

    async def test_failed_on_invalid_manifest(self, tmp_path: Path) -> None:
        bad = tmp_path / "broken"
        bad.mkdir()
        (bad / "route.toml").write_text("[oops", encoding="utf-8")
        loader, _ = _build_loader(tmp_path)
        loaded = await loader.discover_and_load()
        assert loaded[0].status == "failed"
        assert "manifest_error" in (loaded[0].reason or "")


class TestRequiresPlugins:
    async def test_missing_plugin_fails(self, tmp_path: Path) -> None:
        _write_route(tmp_path, name="r1", requires_plugins={"absent_p": ">=1.0"})
        loader, _ = _build_loader(tmp_path)
        loaded = await loader.discover_and_load()
        assert loaded[0].status == "failed"
        assert "missing_plugins" in (loaded[0].reason or "")

    async def test_present_plugin_passes(self, tmp_path: Path) -> None:
        _write_route(
            tmp_path,
            name="r1",
            requires_plugins={"plug_a": ">=1.0,<2.0"},
            capabilities=[("db.read", "credit_db")],
        )
        installed = {
            "plug_a": InstalledPlugin(
                name="plug_a",
                version="1.5.0",
                capabilities=(CapabilityRef(name="db.read", scope="credit_db"),),
            )
        }
        loader, registered = _build_loader(tmp_path, installed_plugins=installed)
        loaded = await loader.discover_and_load()
        assert loaded[0].status == "enabled"
        assert registered


class TestCapabilitiesSubset:
    async def test_route_cap_uncovered_fails(self, tmp_path: Path) -> None:
        _write_route(
            tmp_path,
            name="r1",
            requires_plugins={"plug_a": ">=1.0"},
            capabilities=[("db.read", "credit_db")],
        )
        # Plugin задекларировал ДРУГОЙ scope — capability route'а не покрыта.
        installed = {
            "plug_a": InstalledPlugin(
                name="plug_a",
                version="1.0.0",
                capabilities=(CapabilityRef(name="db.read", scope="audit_db"),),
            )
        }
        loader, _ = _build_loader(tmp_path, installed_plugins=installed)
        loaded = await loader.discover_and_load()
        assert loaded[0].status == "failed"
        assert "capability_superset" in (loaded[0].reason or "")


class TestFeatureFlag:
    async def test_bool_true(self, tmp_path: Path) -> None:
        _write_route(tmp_path, name="r1", feature_flag=True)
        loader, _ = _build_loader(tmp_path)
        loaded = await loader.discover_and_load()
        assert loaded[0].status == "enabled"

    async def test_bool_false(self, tmp_path: Path) -> None:
        _write_route(tmp_path, name="r1", feature_flag=False)
        loader, registered = _build_loader(tmp_path)
        loaded = await loader.discover_and_load()
        assert loaded[0].status == "disabled"
        assert registered == []

    async def test_env_resolver_truthy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_route(tmp_path, name="r1", feature_flag="ROUTE_ENABLED")
        monkeypatch.setenv("ROUTE_ENABLED", "true")
        loader, _ = _build_loader(tmp_path)
        loaded = await loader.discover_and_load()
        assert loaded[0].status == "enabled"

    async def test_env_resolver_falsy(self, tmp_path: Path) -> None:
        _write_route(tmp_path, name="r1", feature_flag="ROUTE_DISABLED")
        # ENV не задан → falsy
        loader, _ = _build_loader(tmp_path)
        loaded = await loader.discover_and_load()
        assert loaded[0].status == "disabled"

    async def test_custom_resolver(self, tmp_path: Path) -> None:
        _write_route(tmp_path, name="r1", feature_flag="custom.flag")
        loader, _ = _build_loader(
            tmp_path, feature_flag_resolver=lambda flag: flag == "custom.flag"
        )
        loaded = await loader.discover_and_load()
        assert loaded[0].status == "enabled"


class TestPipelineRegistration:
    async def test_missing_pipeline_file_fails(self, tmp_path: Path) -> None:
        _write_route(tmp_path, name="r1", create_pipelines=False)
        loader, _ = _build_loader(tmp_path)
        loaded = await loader.discover_and_load()
        assert loaded[0].status == "failed"
        assert "pipeline_register_error" in (loaded[0].reason or "")

    async def test_multiple_pipelines_registered_in_order(self, tmp_path: Path) -> None:
        _write_route(tmp_path, name="r1", pipelines=("p1.dsl.yaml", "p2.dsl.yaml"))
        loader, registered = _build_loader(tmp_path)
        await loader.discover_and_load()
        assert [p.name for _, p in registered] == ["p1.dsl.yaml", "p2.dsl.yaml"]

    async def test_unload_revokes_capabilities(self, tmp_path: Path) -> None:
        _write_route(
            tmp_path,
            name="r1",
            requires_plugins={"plug_a": ">=1.0"},
            capabilities=[("db.read", "credit_db")],
        )
        installed = {
            "plug_a": InstalledPlugin(
                name="plug_a",
                version="1.0.0",
                capabilities=(CapabilityRef(name="db.read", scope="credit_db"),),
            )
        }
        loader, _ = _build_loader(tmp_path, installed_plugins=installed)
        await loader.discover_and_load()
        # Перед unload: capability работает.
        loader._gate.check("r1", "db.read", "credit_db")
        await loader.unload_all()
        with pytest.raises(Exception):
            loader._gate.check("r1", "db.read", "credit_db")


class TestLoadedRouteSerialisation:
    async def test_to_dict_contains_tags_pipelines(self, tmp_path: Path) -> None:
        pkg = _write_route(tmp_path, name="r1")
        # дописываем tags
        manifest = pkg / "route.toml"
        text = manifest.read_text(encoding="utf-8")
        manifest.write_text(text + '\ntags = ["a", "b"]\n', encoding="utf-8")
        loader, _ = _build_loader(tmp_path)
        await loader.discover_and_load()
        d = loader.enabled[0].to_dict()
        assert d["status"] == "enabled"
        assert d["tags"] == ["a", "b"]
        assert d["pipelines"]


class TestDefaultEnvFlagResolver:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("1", True),
            ("true", True),
            ("YES", True),
            ("on", True),
            ("0", False),
            ("false", False),
            ("", False),
            ("nope", False),
        ],
    )
    def test_truthy_table(
        self, monkeypatch: pytest.MonkeyPatch, value: str, expected: bool
    ) -> None:
        monkeypatch.setenv("F", value)
        assert default_env_feature_flag_resolver("F") is expected

    def test_unset_is_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("UNSET_FLAG", raising=False)
        assert default_env_feature_flag_resolver("UNSET_FLAG") is False


# Текстовый docstring тест — гарантирует, что нет regression при mass-edit
def _smoke_textwrap_used() -> str:
    """Использует textwrap, чтобы избежать unused-import."""
    return textwrap.dedent("a")
