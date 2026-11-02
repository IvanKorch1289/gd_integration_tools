"""ADR-0405 — гейт миграции ``routes/*/route.toml`` на namespace capability.

Задача (owner-задача №1 из ``docs/roadmap/OWNER_TASKS.md``): в репозитории
сосуществовали две формы объявления capability:

* **legacy** — плоский список ``capabilities = ["net.outbound", "audit.write"]``
  (``routes/hello_route``, ``routes/test_route_w1``, ``routes/jupyter_hub_run``,
  ``routes/osint_agent``);
* **каноничная** — ``[[route.capabilities]]`` с ``name`` + ``scope``
  (``composition_demo``, ``echo_demo``, ``health_proxy_demo``).

Legacy-форма не только расходилась с каноничной, но и **ломала загрузку**:
плоская строка без ``:scope`` превращалась в ``CapabilityRef(scope=None)``,
а ``CapabilityVocabulary.validate_ref`` отвергает ``scope=None`` для
capability с ``scope_required=True`` (``net.outbound``, ``audit.write``) →
``CapabilityGate.declare`` бросал ``ValueError`` → ``RouteLoader`` помечал
роут как ``failed`` (дефект маскировался выключенным feature-flag).

Гейт проверяет **структуру декларации и её валидность**, а не наличие
строки в файле: манифест разбирается штатным ``load_route_manifest``,
а capability сверяются с ``CapabilityVocabulary`` и subset-инвариантом
ADR-044 (``route.capabilities ⊆ union(plugins) ∪ public``).
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from src.backend.core.plugin_runtime.manifest_toml import load_plugin_manifest
from src.backend.core.security.capabilities import (
    CapabilityGate,
    CapabilityRef,
    build_default_vocabulary,
)
from src.backend.services.routes.loader import InstalledPlugin, RouteLoader
from src.backend.services.routes.manifest_toml import load_route_manifest

REPO_ROOT = Path(__file__).resolve().parents[4]
ROUTES_DIR = REPO_ROOT / "routes"
CORE_VERSION = "0.20.0"

#: Роуты, которые честно остаются незагруженными: capability без
#: плагина-провайдера. После ADR-0415 список пуст — у ``jupyter.hub``
#: появился владелец ``extensions/jupyter_hub/`` (см.
#: ``tests/unit/services/routes/test_jupyter_hub_capability_provider.py``).
EXPECTED_UNCOVERED_ROUTES = frozenset()


def _manifest_paths() -> list[Path]:
    """Все ``routes/*/route.toml`` репозитория."""
    return sorted(ROUTES_DIR.glob("*/route.toml"))


def _raw_manifest(path: Path) -> dict[str, Any]:
    """Разобранный TOML манифеста (без pydantic-нормализации)."""
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _declared_capabilities(path: Path) -> list[dict[str, Any]]:
    """Сырые декларации capability из манифеста (как в TOML)."""
    raw = _raw_manifest(path)
    envelope = raw.get("route")
    if not isinstance(envelope, dict):
        return []
    capabilities = envelope.get("capabilities")
    if not isinstance(capabilities, list):
        return []
    return [entry for entry in capabilities if isinstance(entry, dict)]


def _required_plugins() -> dict[str, InstalledPlugin]:
    """Плагины, которых требуют роуты (как это делает PluginLoader)."""
    plugins: dict[str, InstalledPlugin] = {}
    for path in _manifest_paths():
        manifest = load_route_manifest(path)
        for plugin_name in manifest.requires_plugins:
            plugin_manifest = load_plugin_manifest(
                REPO_ROOT / "extensions" / plugin_name / "plugin.toml"
            )
            plugins[plugin_name] = InstalledPlugin(
                name=plugin_manifest.name,
                version=plugin_manifest.version,
                capabilities=plugin_manifest.capabilities,
            )
    return plugins


class TestRouteCapabilitiesForm:
    """Форма декларации capability в ``routes/*/route.toml``."""

    def test_routes_exist(self) -> None:
        """В репозитории есть роуты (иначе гейт проверяет пустоту)."""
        assert len(_manifest_paths()) >= 7

    def test_no_legacy_flat_capability_list(self) -> None:
        """Ни один манифест не использует плоскую форму ``capabilities = [...]``."""
        offenders: list[str] = []
        for path in _manifest_paths():
            raw = _raw_manifest(path)
            legacy = raw.get("capabilities")
            if legacy is not None:
                offenders.append(
                    f"{path.parent.name}: top-level capabilities={legacy!r}"
                )
            envelope = raw.get("route")
            if isinstance(envelope, dict):
                flat = envelope.get("capabilities")
                if isinstance(flat, list) and any(
                    isinstance(item, str) for item in flat
                ):
                    offenders.append(f"{path.parent.name}: flat capability strings")
        assert offenders == [], offenders

    def test_capabilities_declared_as_tables_with_scope(self) -> None:
        """Каждая capability — таблица ``name`` + ``scope`` (ADR-0078/ADR-0405)."""
        offenders: list[str] = []
        for path in _manifest_paths():
            raw = _raw_manifest(path)
            envelope = raw.get("route")
            assert isinstance(envelope, dict), (
                f"{path.parent.name}: манифест должен быть в конверте [route] "
                f"(ADR-0405), получено top-level ключи {sorted(raw)}"
            )
            capabilities = envelope.get("capabilities")
            assert isinstance(capabilities, list) and capabilities, (
                f"{path.parent.name}: нет [[route.capabilities]]"
            )
            for entry in capabilities:
                assert isinstance(entry, dict), (
                    f"{path.parent.name}: capability должна быть таблицей, "
                    f"получено {entry!r}"
                )
                if set(entry) != {"name", "scope"}:
                    offenders.append(f"{path.parent.name}: {sorted(entry)}")
                if (
                    not isinstance(entry.get("scope"), str)
                    or not entry["scope"].strip()
                ):
                    offenders.append(f"{path.parent.name}: пустой scope {entry!r}")
        assert offenders == [], offenders

    def test_capability_names_have_no_colon(self) -> None:
        """Имя capability — только ``name``; scope лежит в отдельном поле.

        Legacy-форма прятала scope внутрь имени (``"jupyter.hub:run"``,
        ``"ai.invoke:*"``) — по новой модели это разные поля.
        """
        offenders: list[str] = []
        for path in _manifest_paths():
            for entry in _declared_capabilities(path):
                name = entry.get("name")
                if not isinstance(name, str) or ":" in name:
                    offenders.append(f"{path.parent.name}: {name!r}")
        assert offenders == [], offenders

    def test_capability_names_are_in_vocabulary(self) -> None:
        """Все имена capability существуют в ``CapabilityVocabulary``."""
        vocabulary = build_default_vocabulary()
        offenders: list[str] = []
        for path in _manifest_paths():
            for entry in _declared_capabilities(path):
                name = entry.get("name")
                if not isinstance(name, str) or not vocabulary.has(name):
                    offenders.append(f"{path.parent.name}: {name!r}")
        assert offenders == [], offenders


class TestRouteManifestLoading:
    """Манифесты роутов читаются штатным загрузчиком без потерь."""

    def test_every_manifest_loads(self) -> None:
        """``load_route_manifest`` принимает каждый ``routes/*/route.toml``."""
        for path in _manifest_paths():
            manifest = load_route_manifest(path)
            assert manifest.name == path.parent.name

    def test_declared_capabilities_survive_normalization(self) -> None:
        """Декларация из TOML доходит до модели без потери name/scope."""
        for path in _manifest_paths():
            manifest = load_route_manifest(path)
            declared = [
                (str(entry["name"]), str(entry["scope"]))
                for entry in _declared_capabilities(path)
            ]
            assert [(ref.name, ref.scope) for ref in manifest.capabilities] == declared

    def test_every_capability_has_explicit_scope(self) -> None:
        """Ни одна capability не объявлена без scope (scope_required=True)."""
        vocabulary = build_default_vocabulary()
        for path in _manifest_paths():
            manifest = load_route_manifest(path)
            for ref in manifest.capabilities:
                definition = vocabulary.get(ref.name)
                if definition.scope_required:
                    assert ref.scope is not None, f"{path.parent.name}: {ref.name}"


class TestRouteLoaderAcceptsRoutes:
    """``RouteLoader`` принимает роуты, а capability-гейт не отвергает их."""

    async def test_all_routes_discovered_and_loaded(self) -> None:
        """Каждый ``route.toml`` найден и загружен (кроме документированного)."""
        loader = RouteLoader(
            routes_dir=ROUTES_DIR,
            capability_gate=CapabilityGate(),
            vocabulary=build_default_vocabulary(),
            core_version=CORE_VERSION,
            installed_plugins=_required_plugins(),
            pipeline_registrar=lambda *_args, **_kwargs: None,
            feature_flag_resolver=lambda _flag: True,
            strict_capabilities=True,
        )
        loaded = await loader.discover_and_load()
        discovered = {route.name for route in loaded}
        assert discovered == {path.parent.name for path in _manifest_paths()}

        failed = {
            route.name: route.reason or ""
            for route in loaded
            if route.status == "failed"
        }
        # Отказ допустим только там, где capability намеренно не покрыта
        # плагином-владельцем (least privilege, ADR-044).
        assert set(failed) == set(EXPECTED_UNCOVERED_ROUTES), failed
        for name, reason in failed.items():
            assert "capability_superset" in reason, (name, reason)

    async def test_loaded_routes_declare_capabilities_in_gate(self) -> None:
        """Capability загруженных роутов попали в gate (scope не потерян)."""
        gate = CapabilityGate()
        loader = RouteLoader(
            routes_dir=ROUTES_DIR,
            capability_gate=gate,
            vocabulary=build_default_vocabulary(),
            core_version=CORE_VERSION,
            installed_plugins=_required_plugins(),
            pipeline_registrar=lambda *_args, **_kwargs: None,
            feature_flag_resolver=lambda _flag: True,
            strict_capabilities=True,
        )
        await loader.discover_and_load()
        for route in loader.enabled:
            declared = gate.declarations(route.name)
            assert declared, route.name
            assert all(ref.scope for ref in declared), route.name
            assert {ref.name for ref in declared} == {
                ref.name for ref in route.manifest.capabilities if route.manifest
            }

    async def test_capability_subset_invariant_holds(self) -> None:
        """``route.capabilities ⊆ union(plugins) ∪ public`` (ADR-044)."""
        plugins = _required_plugins()
        vocabulary = build_default_vocabulary()
        public_names = {d.name for d in vocabulary.public_capabilities()}
        for path in _manifest_paths():
            manifest = load_route_manifest(path)
            available: list[CapabilityRef] = []
            for plugin_name in manifest.requires_plugins:
                available.extend(plugins[plugin_name].capabilities)
            for ref in manifest.capabilities:
                if ref.name in public_names:
                    continue
                if manifest.name in EXPECTED_UNCOVERED_ROUTES:
                    continue
                assert any(candidate.name == ref.name for candidate in available), (
                    f"{manifest.name}: {ref.name} не покрыта плагинами"
                )
