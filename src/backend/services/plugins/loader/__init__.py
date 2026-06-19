"""PluginLoader package (S52 W3 decomp from loader.py 724 LOC).

14 methods decomposed в 3 mixin files:
- ``discovery.py`` (2): _topo_sort_non_blocked, _reorder_manifest_paths
- ``loading.py`` (5): _load_one, _instantiate, _plugin_page_prefix, _mount_frontend_pages, _unmount_frontend_pages
- ``validation.py`` (2): _check_inventory_collisions, _record_owners

Public surface (__init__ + loaded + successful + discover_and_load + shutdown_all) остается в __init__.py.

Backward-compat: ``from src.backend.services.plugins.loader import PluginLoader`` works.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.core.interfaces.plugin import (
        ActionRegistryProtocol,
        ProcessorRegistryProtocol,
        RepositoryRegistryProtocol,
    )
    from src.backend.core.security.capabilities import CapabilityGate

from src.backend.core.logging import get_logger
from src.backend.core.plugin_runtime.compat_checker import (
    CompatViolation,
    check_compatibility,
)
from src.backend.services.plugins.loader.discovery import (
    DiscoveryMixin,  # S52 W3: MRO
    LoadedPlugin,  # S52 W3: re-export для backward compat
    PluginInventoryConflictError,  # S52 W3: re-export для backward compat
)
from src.backend.services.plugins.loader.loading import LoadingMixin  # S52 W3: MRO
from src.backend.services.plugins.loader.validation import (
    ValidationMixin,  # S52 W3: MRO
)
from src.backend.services.plugins.manifest_toml import (  # S52 W3: needed for _load_one's compat_violations
    PluginManifestError,
    PluginManifest,
    load_plugin_manifest,
)

_logger = get_logger(
    "services.plugins.loader"
)  # S52 W3: re-defined for backward compat

__all__ = ("LoadedPlugin", "PluginInventoryConflictError", "PluginLoader")


class PluginLoader(DiscoveryMixin, ValidationMixin, LoadingMixin):
    """In-tree plugin loader (3 mixins = 9 internal methods + 5 public).

    ADR-042 R1.2: V11 plugin loader (in-tree extensions/<name>/, no entry_points).

    S133 W4 MRO: ValidationMixin ДО LoadingMixin, чтобы concrete реализации
    ``_check_inventory_collisions`` / ``_record_owners`` из ValidationMixin
    брались до Protocol-заглушек в ``_LoadingProtocol`` (иначе mypy считает
    класс abstract).
    """

    # State attrs set in __init__ (S52 W3: class-level annotations for mypy MRO)
    _extensions_dir: Path
    _gate: CapabilityGate
    _actions: ActionRegistryProtocol
    _repos: RepositoryRegistryProtocol
    _processors: ProcessorRegistryProtocol
    _core_version: str
    _streamlit_pages_dir: Path | None
    _loaded: dict[str, LoadedPlugin]
    _owners: dict[str, dict[str, str]]
    _loaded_failed: list[LoadedPlugin]
    _loaded_skipped: list[LoadedPlugin]

    def __init__(
        self,
        *,
        extensions_dir: Path,
        capability_gate: CapabilityGate,
        action_registry: ActionRegistryProtocol,
        repository_registry: RepositoryRegistryProtocol,
        processor_registry: ProcessorRegistryProtocol,
        core_version: str,
        streamlit_pages_dir: Path | None = None,
    ) -> None:
        self._extensions_dir = Path(extensions_dir)
        self._gate = capability_gate
        self._actions = action_registry
        self._repos = repository_registry
        self._processors = processor_registry
        self._core_version = core_version
        self._streamlit_pages_dir = (
            Path(streamlit_pages_dir) if streamlit_pages_dir is not None else None
        )
        self._loaded: dict[str, LoadedPlugin] = {}
        # owner-tracking для inventory-коллизий: kind → name → plugin
        self._owners: dict[str, dict[str, str]] = {
            "actions": {},
            "repositories": {},
            "processors": {},
            "sources": {},
            "sinks": {},
            "schemas": {},
        }

    @property
    def loaded(self) -> tuple[LoadedPlugin, ...]:
        """Все попытки загрузки (loaded / failed / skipped)."""
        return tuple(self._loaded.values())

    @property
    def successful(self) -> tuple[LoadedPlugin, ...]:
        """Только успешно загруженные плагины."""
        return tuple(p for p in self._loaded.values() if p.status == "loaded")

    async def discover_and_load(self) -> tuple[LoadedPlugin, ...]:
        """Сканировать ``extensions/`` и загрузить все ``plugin.toml``.

        Sprint 14 W1: перед `_load_one` собирает все валидные манифесты
        и прогоняет через :func:`check_compatibility`. Плагины с
        нарушениями compatibility-матрицы помечаются ``status="failed"``
        ещё до import_module.

        Sprint 16 K5-W1 (L8-P1-1): после compat-check выполняется
        topological sort не-blocked плагинов по
        ``compatibility.requires_plugins`` через
        :class:`PluginGraphResolver`. Гарантирует bootstrap-порядок
        «зависимость → зависимый». Циклы детектируются и помечают
        затронутые плагины ``status="failed"`` с reason
        ``dependency_cycle``.
        """
        if not self._extensions_dir.is_dir():
            _logger.info(
                "Extensions dir %s not found — no V11 plugins discovered",
                self._extensions_dir,
            )
            return ()

        manifest_paths: list[Path] = []
        parsed_manifests: list[PluginManifest] = []
        parse_failures: list[tuple[Path, str]] = []
        for child in sorted(self._extensions_dir.iterdir()):
            manifest_path = child / "plugin.toml"
            if not manifest_path.is_file():
                continue
            manifest_paths.append(manifest_path)
            try:
                manifest = load_plugin_manifest(manifest_path)
            except PluginManifestError as exc:
                parse_failures.append((manifest_path, str(exc)))
                continue
            parsed_manifests.append(manifest)

        compat_blocked: set[str] = set()
        violations: tuple[CompatViolation, ...] = ()
        if parsed_manifests:
            violations = check_compatibility(
                parsed_manifests, core_version=self._core_version
            )
            for violation in violations:
                compat_blocked.add(violation.plugin)
                _logger.warning(
                    "Plugin %s blocked by compatibility matrix: %s",
                    violation.plugin,
                    violation.reason,
                )

        cycle_blocked: set[str] = set()
        cycle_reason: str | None = None
        sorted_names = self._topo_sort_non_blocked(
            parsed_manifests, compat_blocked, cycle_blocked
        )
        if cycle_blocked:
            cycle_reason = (
                f"dependency_cycle: plugins {sorted(cycle_blocked)!r} form a cycle"
            )

        ordered_paths = self._reorder_manifest_paths(
            manifest_paths=manifest_paths, sorted_names=sorted_names
        )

        parse_failures_map = dict(parse_failures)
        for manifest_path in ordered_paths:
            await self._load_one(
                manifest_path,
                compat_violations=violations,
                blocked=compat_blocked,
                parse_failures=parse_failures_map,
                cycle_blocked=cycle_blocked,
                cycle_reason=cycle_reason,
            )
        return self.loaded

    async def shutdown_all(self) -> None:
        """Graceful shutdown всех загруженных плагинов."""
        for entry in tuple(self._loaded.values()):
            if entry.status != "loaded" or entry.instance is None:
                continue
            try:
                await entry.instance.on_shutdown()
            except Exception as _:
                _logger.exception("Plugin %s on_shutdown failed", entry.name)
            self._unmount_frontend_pages(entry.name)
            self._gate.revoke(entry.name)


# Backward-compat singleton accessor (S168 W15-17 deprecation shim).
# The new PluginLoader requires explicit DI (extensions_dir, capability_gate,
# action_registry, repository_registry, processor_registry, core_version);
# use the constructor directly. This function is kept for startup.py:421
# which expects a get_plugin_loader() singleton. If app.state.plugin_loader
# is set, returns it; otherwise raises (caught by try/except in startup,
# falls back to bootstrap_v11_plugin_loader).
from src.backend.core.di.app_state import app_state_singleton  # noqa: E402


def _empty_plugin_loader_factory() -> "PluginLoader":
    """Factory для app_state_singleton — raises с понятной ошибкой."""
    raise RuntimeError(
        "PluginLoader требует explicit DI. Use PluginLoader("
        "extensions_dir=..., capability_gate=..., action_registry=..., "
        "repository_registry=..., processor_registry=..., core_version=..."
        ") constructor или set app.state.plugin_loader в startup."
    )


@app_state_singleton("plugin_loader", factory=_empty_plugin_loader_factory)
def get_plugin_loader() -> "PluginLoader":
    """Singleton-accessor (backward compat, see app_state_singleton)."""
    raise RuntimeError("unreachable — see app_state_singleton decorator")
