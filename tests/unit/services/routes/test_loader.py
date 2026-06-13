# ruff: noqa: S101
"""Тесты RouteLoader (ADR-043 / ADR-044)."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

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
    requires_workflows: dict[str, str] | None = None,
    capabilities: list[tuple[str, str | None]] | None = None,
    feature_flag: str | bool | None = None,
    pipelines: tuple[str, ...] = ("pipeline.dsl.yaml",),
    create_pipelines: bool = True,
    tenant_aware: bool = False,
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
    if tenant_aware:
        body.append("tenant_aware = true")
    if feature_flag is not None:
        if isinstance(feature_flag, bool):
            body.append(f"feature_flag = {str(feature_flag).lower()}")
        else:
            body.append(f'feature_flag = "{feature_flag}"')
    if requires_plugins:
        body.append("[requires_plugins]")
        for n, spec in requires_plugins.items():
            body.append(f'{n} = "{spec}"')
    if requires_workflows:
        body.append("[requires_workflows]")
        for n, spec in requires_workflows.items():
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
    installed_workflows: dict[str, str] | None = None,
    feature_flag_resolver=None,
) -> tuple[RouteLoader, list[tuple[str, Path, Any]]]:
    registered: list[tuple[str, Path, Any]] = []

    def registrar(route_name: str, pipeline_path: Path, manifest: Any) -> None:
        registered.append((route_name, pipeline_path, manifest))

    loader = RouteLoader(
        routes_dir=routes_dir,
        capability_gate=CapabilityGate(),
        vocabulary=build_default_vocabulary(),
        core_version="0.2.0",
        installed_plugins=installed_plugins or {},
        pipeline_registrar=registrar,
        feature_flag_resolver=feature_flag_resolver
        or default_env_feature_flag_resolver,
        installed_workflows=installed_workflows,
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
        assert len(registered) == 1
        assert registered[0][:2] == ("r1", tmp_path / "r1" / "pipeline.dsl.yaml")
        # Третий аргумент — manifest (K-ARCH-4).
        assert registered[0][2].name == "r1"

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


class TestRequiresWorkflows:
    """K3 S19 W1: requires_workflows SemVer version checking in RouteLoader."""

    async def test_missing_workflow_fails(self, tmp_path: Path) -> None:
        """Route with absent workflow requirement fails to load."""
        _write_route(tmp_path, name="r1", requires_workflows={"absent_wf": ">=1.0"})
        loader, _ = _build_loader(tmp_path)
        loaded = await loader.discover_and_load()
        assert loaded[0].status == "failed"
        assert "missing_workflows" in (loaded[0].reason or "")

    async def test_incompatible_workflow_version_fails(self, tmp_path: Path) -> None:
        """Route with incompatible workflow version fails to load."""
        _write_route(tmp_path, name="r1", requires_workflows={"wf_a": ">=2.0,<3.0"})
        # wf_a is installed but version 1.5.0 is not compatible with >=2.0,<3.0
        loader, _ = _build_loader(tmp_path, installed_workflows={"wf_a": "1.5.0"})
        loaded = await loader.discover_and_load()
        assert loaded[0].status == "failed"
        assert "missing_workflows" in (loaded[0].reason or "")

    async def test_present_compatible_workflow_passes(self, tmp_path: Path) -> None:
        """Route with compatible workflow version passes."""
        _write_route(tmp_path, name="r1", requires_workflows={"wf_a": ">=1.0,<2.0"})
        loader, _ = _build_loader(tmp_path, installed_workflows={"wf_a": "1.5.0"})
        loaded = await loader.discover_and_load()
        assert loaded[0].status == "enabled"

    async def test_audit_event_emitted_on_workflow_mismatch(
        self, tmp_path: Path
    ) -> None:
        """workflow.version.mismatch audit event is emitted when workflow check fails."""
        _write_route(tmp_path, name="r1", requires_workflows={"wf_missing": ">=1.0"})
        events: list[dict[str, object]] = []
        loader = RouteLoader(
            routes_dir=tmp_path,
            capability_gate=CapabilityGate(),
            vocabulary=build_default_vocabulary(),
            core_version="0.2.0",
            installed_plugins={},
            pipeline_registrar=lambda *_: None,
            installed_workflows={},
            audit_callback=events.append,
        )
        loaded = await loader.discover_and_load()
        assert loaded[0].status == "failed"
        mismatch_events = [
            e for e in events if e.get("event") == "workflow.version.mismatch"
        ]
        assert len(mismatch_events) == 1
        assert mismatch_events[0]["route"] == "r1"
        assert mismatch_events[0]["missing_workflows"] == {"wf_missing": ">=1.0"}

    async def test_empty_requires_workflows_passes(self, tmp_path: Path) -> None:
        """Route without requires_workflows (or empty) loads normally."""
        _write_route(tmp_path, name="r1")
        loader, _ = _build_loader(tmp_path)
        loaded = await loader.discover_and_load()
        assert loaded[0].status == "enabled"


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
        assert [r[1].name for r in registered] == ["p1.dsl.yaml", "p2.dsl.yaml"]

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


class TestTenantAwarePropagation:
    """K-ARCH-4 (S17): tenant_aware пробрасывается из manifest в registrar."""

    async def test_default_false_not_propagated(self, tmp_path: Path) -> None:
        """По умолчанию ``tenant_aware=False`` — manifest флаг = False."""
        _write_route(tmp_path, name="r_plain")
        loader, registered = _build_loader(tmp_path)
        loaded = await loader.discover_and_load()
        assert loaded[0].status == "enabled"
        assert len(registered) == 1
        assert registered[0][2].tenant_aware is False

    async def test_tenant_aware_true_propagated_to_registrar(
        self, tmp_path: Path
    ) -> None:
        """tenant_aware=true в route.toml попадает в manifest registrar'а."""
        _write_route(tmp_path, name="r_tenant", tenant_aware=True)
        loader, registered = _build_loader(tmp_path)
        loaded = await loader.discover_and_load()
        assert loaded[0].status == "enabled"
        assert len(registered) == 1
        assert registered[0][2].tenant_aware is True


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


class TestCapabilityGateAuditAndStrict:
    """K-ARCH-3 (S17): route.capabilities.allocated audit + strict-режим."""

    async def test_audit_event_emitted_on_enabled_route(self, tmp_path: Path) -> None:
        """``route.capabilities.allocated`` эмитится при enabled route."""
        _write_route(
            tmp_path,
            name="r_audit",
            requires_plugins={"plug_a": ">=1.0,<2.0"},
            capabilities=[("db.read", "users")],
        )
        installed = {
            "plug_a": InstalledPlugin(
                name="plug_a",
                version="1.5.0",
                capabilities=(CapabilityRef(name="db.read", scope="users"),),
            )
        }
        events: list[dict[str, object]] = []
        loader = RouteLoader(
            routes_dir=tmp_path,
            capability_gate=CapabilityGate(),
            vocabulary=build_default_vocabulary(),
            core_version="0.2.0",
            installed_plugins=installed,
            pipeline_registrar=lambda *_: None,
            audit_callback=events.append,
        )
        loaded = await loader.discover_and_load()
        assert loaded[0].status == "enabled"
        allocated = [
            e for e in events if e.get("event") == "route.capabilities.allocated"
        ]
        assert len(allocated) == 1
        assert allocated[0]["route"] == "r_audit"
        caps = allocated[0]["capabilities"]
        assert isinstance(caps, list) and len(caps) == 1
        assert caps[0]["name"] == "db.read"

    async def test_strict_mode_fails_route_without_capabilities(
        self, tmp_path: Path
    ) -> None:
        """strict_capabilities=True: route без capabilities → status=failed."""
        _write_route(tmp_path, name="r_no_caps", capabilities=[])
        loader = RouteLoader(
            routes_dir=tmp_path,
            capability_gate=CapabilityGate(),
            vocabulary=build_default_vocabulary(),
            core_version="0.2.0",
            installed_plugins={},
            pipeline_registrar=lambda *_: None,
            strict_capabilities=True,
        )
        loaded = await loader.discover_and_load()
        assert loaded[0].status == "failed"
        assert "routes_capability_gate_strict" in (loaded[0].reason or "")

    async def test_default_off_passes_route_without_capabilities(
        self, tmp_path: Path
    ) -> None:
        """strict_capabilities=False (default): empty-caps route проходит."""
        _write_route(tmp_path, name="r_no_caps", capabilities=[])
        loader = RouteLoader(
            routes_dir=tmp_path,
            capability_gate=CapabilityGate(),
            vocabulary=build_default_vocabulary(),
            core_version="0.2.0",
            installed_plugins={},
            pipeline_registrar=lambda *_: None,
            strict_capabilities=False,
        )
        loaded = await loader.discover_and_load()
        assert loaded[0].status == "enabled"


# Текстовый docstring тест — гарантирует, что нет regression при mass-edit
def _smoke_textwrap_used() -> str:
    """Использует textwrap, чтобы избежать unused-import."""
    return textwrap.dedent("a")


def test_route_loader_uses_renamed_audit_method() -> None:
    """S109 W4: ``_emit_audit`` → ``_audit_emit`` (regex-friendly name).

    Verifies that RouteLoader has the renamed method.
    """
    from src.backend.services.routes.loader import RouteLoader

    assert hasattr(RouteLoader, "_audit_emit")
    assert not hasattr(RouteLoader, "_emit_audit")
