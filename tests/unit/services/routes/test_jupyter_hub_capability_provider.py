"""ADR-0415 — capability-провайдер ``jupyter.hub`` и загрузка роута.

До ADR-0415 capability ``jupyter.hub`` была объявлена в vocabulary
(:mod:`core.security.capabilities.vocabulary.defaults.base`), но **владельца**
capability в проекте не было: ни один плагин не объявлял
``[[capabilities]] name = "jupyter.hub"``. Поэтому subset-инвариант ADR-044
(``route.capabilities ⊆ union(requires_plugins) ∪ public``) отклонял
``routes/jupyter_hub_run`` с ``capability_superset`` — роут оставался
единственным неработающим из семи.

Провайдер — расширение ``extensions/jupyter_hub/`` (ADR-0078: форма
``[[capabilities]]`` с отдельными name/scope). Capability остаётся
**непубличной** — публичность отдала бы удалённое выполнение кода любому
роуту без провайдера (ADR-0405 §Альтернативы, вариант C).
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest

from src.backend.core.plugin_runtime.manifest_toml import load_plugin_manifest
from src.backend.core.security.capabilities import (
    CapabilityDeniedError,
    CapabilityGate,
    CapabilityRef,
    build_default_vocabulary,
)
from src.backend.services.routes.loader import InstalledPlugin, RouteLoader

REPO_ROOT = Path(__file__).resolve().parents[4]
ROUTES_DIR = REPO_ROOT / "routes"
PROVIDER_DIR = REPO_ROOT / "extensions" / "jupyter_hub"
CORE_VERSION = "0.20.0"


def _provider_manifest_raw() -> dict[str, Any]:
    """Сырой TOML-манифест провайдера."""
    return tomllib.loads((PROVIDER_DIR / "plugin.toml").read_text(encoding="utf-8"))


class TestProviderManifest:
    """Манифест провайдера объявляет capability в форме ADR-0078."""

    def test_provider_manifest_exists(self) -> None:
        """Расширение-провайдер существует в ``extensions/``."""
        assert (PROVIDER_DIR / "plugin.toml").is_file()
        assert (PROVIDER_DIR / "plugin.py").is_file()

    def test_capability_declared_as_table_with_scope(self) -> None:
        """``jupyter.hub`` объявлена таблицей ``name`` + ``scope``."""
        raw = _provider_manifest_raw()
        capabilities = raw.get("capabilities")
        assert isinstance(capabilities, list), "capabilities должны быть таблицами"
        entries = {(c["name"], c["scope"]) for c in capabilities}
        assert ("jupyter.hub", "run") in entries, entries

    def test_capability_is_not_public(self) -> None:
        """Capability не публичная — доступ только у явного провайдера."""
        vocabulary = build_default_vocabulary()
        assert not vocabulary.get("jupyter.hub").public

    def test_plugin_manifest_loads(self) -> None:
        """Манифест проходит штатную pydantic-валидацию."""
        manifest = load_plugin_manifest(PROVIDER_DIR / "plugin.toml")
        assert manifest.name == "jupyter_hub"
        assert (manifest.capabilities[0].name, manifest.capabilities[0].scope) == (
            "jupyter.hub",
            "run",
        )

    def test_entry_point_is_importable_base_plugin(self) -> None:
        """``entry_class`` — импортируемый :class:`BasePlugin`-наследник."""
        from extensions.jupyter_hub.plugin import JupyterHubPlugin
        from src.backend.core.api import BasePlugin

        assert issubclass(JupyterHubPlugin, BasePlugin)
        assert JupyterHubPlugin.name == "jupyter_hub"


class TestRouteWiring:
    """Роут запрашивает capability у провайдера."""

    def test_route_requires_provider_plugin(self) -> None:
        """``route.toml`` объявляет ``[route.requires_plugins] jupyter_hub``."""
        raw = tomllib.loads(
            (ROUTES_DIR / "jupyter_hub_run" / "route.toml").read_text(encoding="utf-8")
        )
        requires = raw["route"]["requires_plugins"]
        assert "jupyter_hub" in requires, requires

    def test_route_declares_matching_scope(self) -> None:
        """Scope роута (``run``) совпадает со scope провайдера."""
        raw = tomllib.loads(
            (ROUTES_DIR / "jupyter_hub_run" / "route.toml").read_text(encoding="utf-8")
        )
        declared = {(c["name"], c["scope"]) for c in raw["route"]["capabilities"]}
        assert ("jupyter.hub", "run") in declared, declared


class TestRouteLoader:
    """``RouteLoader`` принимает роут: capability-гейт не отвергает."""

    async def test_jupyter_hub_run_is_enabled(self) -> None:
        """Роут загружается (status="enabled"), а не "failed"."""
        gate = CapabilityGate()
        loader = RouteLoader(
            routes_dir=ROUTES_DIR,
            capability_gate=gate,
            vocabulary=build_default_vocabulary(),
            core_version=CORE_VERSION,
            installed_plugins={"jupyter_hub": _installed_provider()},
            pipeline_registrar=lambda *_args, **_kwargs: None,
            feature_flag_resolver=lambda _flag: True,
            strict_capabilities=True,
        )
        await loader.discover_and_load()
        loaded = {route.name: route for route in loader.loaded}
        route = loaded["jupyter_hub_run"]
        assert route.status == "enabled", route.reason
        assert not (route.reason or "")

    async def test_capability_declared_in_gate(self) -> None:
        """Capability роута попала в gate с корректным scope."""
        gate = CapabilityGate()
        loader = RouteLoader(
            routes_dir=ROUTES_DIR,
            capability_gate=gate,
            vocabulary=build_default_vocabulary(),
            core_version=CORE_VERSION,
            installed_plugins={"jupyter_hub": _installed_provider()},
            pipeline_registrar=lambda *_args, **_kwargs: None,
            feature_flag_resolver=lambda _flag: True,
            strict_capabilities=True,
        )
        await loader.discover_and_load()
        declared = {
            (ref.name, ref.scope) for ref in gate.declarations("jupyter_hub_run")
        }
        assert ("jupyter.hub", "run") in declared, declared


class TestProviderRuntimeEnforcement:
    """Провайдер проверяет capability в рантайме (fail-closed)."""

    async def test_denied_without_declaration(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Без декларации capability вызов отклоняется."""
        from extensions.jupyter_hub import plugin as provider

        monkeypatch.setattr(provider, "get_capability_gate", CapabilityGate)
        with pytest.raises(CapabilityDeniedError):
            await provider.run_notebook({"notebook_name": "demo"})

    async def test_granted_with_declaration(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """С декларацией capability вызов доходит до оркестратора."""
        from extensions.jupyter_hub import plugin as provider

        gate = CapabilityGate()
        gate.declare(
            provider.PLUGIN_NAME,
            (CapabilityRef(name=provider.CAPABILITY_NAME, scope="run"),),
        )
        monkeypatch.setattr(provider, "get_capability_gate", lambda: gate)

        calls: list[dict[str, Any]] = []

        async def _fake_run(**kwargs: Any) -> Any:
            calls.append(kwargs)
            return {"notebook_name": kwargs["notebook_name"], "outputs": []}

        monkeypatch.setattr(provider, "get_hub_run_provider", lambda: _fake_run)
        result = await provider.run_notebook(
            {"notebook_name": "demo", "parameters": {"a": 1}}
        )
        assert result["notebook_name"] == "demo"
        assert calls[0]["parameters"] == {"a": 1}


def _installed_provider() -> InstalledPlugin:
    """Провайдер в виде :class:`InstalledPlugin` (как его видит PluginLoader)."""
    manifest = load_plugin_manifest(PROVIDER_DIR / "plugin.toml")
    return InstalledPlugin(
        name=manifest.name, version=manifest.version, capabilities=manifest.capabilities
    )
