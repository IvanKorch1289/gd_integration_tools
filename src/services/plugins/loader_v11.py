"""ADR-042 (R1.2) — :class:`PluginLoaderV11` для in-tree extensions/<name>/.

Discovery + lifecycle для V11-плагинов: scan каталога ``extensions/``,
parse ``plugin.toml``, проверка ``requires_core`` + capability-allocation
**до** ``import_module(entry_class)``, затем lifecycle-хуки
:class:`BasePlugin`. Параллельно с Wave 4.4 :mod:`loader` (entry_points),
который остаётся deprecated-shim'ом.

V11.1 фиксирует: плагины поставляются ТОЛЬКО in-tree
(``extensions/<name>/``); pip / entry_points для бизнес-плагинов больше
не используются.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.core.interfaces.plugin import (
    ActionRegistryProtocol,
    BasePlugin,
    PluginContext,
    ProcessorRegistryProtocol,
    RepositoryRegistryProtocol,
)
from src.core.security.capabilities import CapabilityError, CapabilityGate
from src.services.plugins.manifest_v11 import (
    PluginManifestError,
    PluginManifestV11,
    load_plugin_manifest,
)

__all__ = ("LoadedPluginV11", "PluginInventoryConflictError", "PluginLoaderV11")

_logger = logging.getLogger("services.plugins.loader_v11")


class PluginInventoryConflictError(RuntimeError):
    """Имя из ``provides`` уже зарегистрировано другим плагином."""

    def __init__(self, *, plugin: str, kind: str, name: str, owner: str) -> None:
        self.plugin = plugin
        self.kind = kind
        self.name = name
        self.owner = owner
        super().__init__(
            f"Plugin {plugin!r} cannot register {kind} {name!r} — "
            f"already provided by {owner!r}"
        )


@dataclass(slots=True)
class LoadedPluginV11:
    """Метаданные одного загруженного плагина для admin-эндпоинта."""

    name: str
    version: str
    manifest_path: Path
    status: str  # "loaded" | "failed" | "skipped"
    reason: str | None = None
    instance: BasePlugin | None = None
    manifest: PluginManifestV11 | None = None

    def to_dict(self) -> dict[str, Any]:
        """Сериализация для ``/api/v1/plugins/inventory``."""
        return {
            "name": self.name,
            "version": self.version,
            "status": self.status,
            "reason": self.reason,
            "manifest_path": str(self.manifest_path),
        }


class PluginLoaderV11:
    """V11 PluginLoader: scan ``extensions/<name>/plugin.toml``.

    Args:
        extensions_dir: Каталог с подкаталогами плагинов
            (``extensions/<name>/`` каждый со своим ``plugin.toml``).
        capability_gate: Runtime-gate для декларации capabilities.
        action_registry: Реестр actions (контракт из
            :mod:`src.core.interfaces.plugin`).
        repository_registry: Реестр repository-hook'ов.
        processor_registry: Реестр DSL-процессоров.
        core_version: Текущая версия ядра (``"0.2.0"`` и т.п.); сверяется
            с ``manifest.requires_core`` при load.
    """

    def __init__(
        self,
        *,
        extensions_dir: Path,
        capability_gate: CapabilityGate,
        action_registry: ActionRegistryProtocol,
        repository_registry: RepositoryRegistryProtocol,
        processor_registry: ProcessorRegistryProtocol,
        core_version: str,
    ) -> None:
        self._extensions_dir = Path(extensions_dir)
        self._gate = capability_gate
        self._actions = action_registry
        self._repos = repository_registry
        self._processors = processor_registry
        self._core_version = core_version
        self._loaded: dict[str, LoadedPluginV11] = {}
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
    def loaded(self) -> tuple[LoadedPluginV11, ...]:
        """Все попытки загрузки (loaded / failed / skipped)."""
        return tuple(self._loaded.values())

    @property
    def successful(self) -> tuple[LoadedPluginV11, ...]:
        """Только успешно загруженные плагины."""
        return tuple(p for p in self._loaded.values() if p.status == "loaded")

    async def discover_and_load(self) -> tuple[LoadedPluginV11, ...]:
        """Сканировать ``extensions/`` и загрузить все ``plugin.toml``."""
        if not self._extensions_dir.is_dir():
            _logger.info(
                "Extensions dir %s not found — no V11 plugins discovered",
                self._extensions_dir,
            )
            return ()

        for child in sorted(self._extensions_dir.iterdir()):
            manifest_path = child / "plugin.toml"
            if not manifest_path.is_file():
                continue
            await self._load_one(manifest_path)
        return self.loaded

    async def shutdown_all(self) -> None:
        """Graceful shutdown всех загруженных плагинов."""
        for entry in tuple(self._loaded.values()):
            if entry.status != "loaded" or entry.instance is None:
                continue
            try:
                await entry.instance.on_shutdown()
            except Exception:
                _logger.exception("Plugin %s on_shutdown failed", entry.name)
            self._gate.revoke(entry.name)

    # ── private ──────────────────────────────────────────────────────

    async def _load_one(self, manifest_path: Path) -> None:
        """Загрузить один плагин по ``plugin.toml``."""
        try:
            manifest = load_plugin_manifest(manifest_path)
        except PluginManifestError as exc:
            _logger.warning("Plugin manifest invalid (%s): %s", manifest_path, exc)
            self._loaded[manifest_path.parent.name] = LoadedPluginV11(
                name=manifest_path.parent.name,
                version="?",
                manifest_path=manifest_path,
                status="failed",
                reason=f"manifest_error: {exc}",
            )
            return

        # Pre-conditions: версия, коллизии inventory
        if not manifest.is_compatible_with_core(self._core_version):
            _logger.info(
                "Plugin %s skipped: requires_core=%s, core=%s",
                manifest.name,
                manifest.requires_core,
                self._core_version,
            )
            self._loaded[manifest.name] = LoadedPluginV11(
                name=manifest.name,
                version=manifest.version,
                manifest_path=manifest_path,
                manifest=manifest,
                status="skipped",
                reason=(
                    f"requires_core={manifest.requires_core}, core={self._core_version}"
                ),
            )
            return

        try:
            self._check_inventory_collisions(manifest)
        except PluginInventoryConflictError as exc:
            _logger.warning("Plugin %s inventory conflict: %s", manifest.name, exc)
            self._loaded[manifest.name] = LoadedPluginV11(
                name=manifest.name,
                version=manifest.version,
                manifest_path=manifest_path,
                manifest=manifest,
                status="failed",
                reason=f"inventory_conflict: {exc}",
            )
            return

        # Capability-allocation ДО import_module
        try:
            self._gate.declare(manifest.name, manifest.capabilities)
        except (CapabilityError, ValueError) as exc:
            _logger.warning(
                "Plugin %s capability allocation failed: %s", manifest.name, exc
            )
            self._loaded[manifest.name] = LoadedPluginV11(
                name=manifest.name,
                version=manifest.version,
                manifest_path=manifest_path,
                manifest=manifest,
                status="failed",
                reason=f"capability_error: {exc}",
            )
            return

        # Import + instantiate + lifecycle
        try:
            plugin = self._instantiate(manifest)
        except Exception as exc:
            _logger.exception("Plugin %s import failed", manifest.name)
            self._gate.revoke(manifest.name)
            self._loaded[manifest.name] = LoadedPluginV11(
                name=manifest.name,
                version=manifest.version,
                manifest_path=manifest_path,
                manifest=manifest,
                status="failed",
                reason=f"import_error: {exc}",
            )
            return

        ctx = PluginContext(
            plugin_name=manifest.name,
            actions=self._actions,
            repositories=self._repos,
            processors=self._processors,
            config=dict(manifest.config),
        )

        try:
            await plugin.on_load(ctx)
            await plugin.on_register_actions(ctx.actions)
            await plugin.on_register_repositories(ctx.repositories)
            await plugin.on_register_processors(ctx.processors)
        except Exception as exc:
            _logger.exception("Plugin %s lifecycle failed", manifest.name)
            self._gate.revoke(manifest.name)
            self._loaded[manifest.name] = LoadedPluginV11(
                name=manifest.name,
                version=manifest.version,
                manifest_path=manifest_path,
                manifest=manifest,
                status="failed",
                reason=f"lifecycle_error: {exc}",
            )
            return

        self._record_owners(manifest)
        self._loaded[manifest.name] = LoadedPluginV11(
            name=manifest.name,
            version=manifest.version,
            manifest_path=manifest_path,
            manifest=manifest,
            status="loaded",
            instance=plugin,
        )
        _logger.info(
            "Plugin loaded (V11): %s v%s (%s)",
            manifest.name,
            manifest.version,
            manifest_path,
        )

    def _check_inventory_collisions(self, manifest: PluginManifestV11) -> None:
        """Гарантирует, что provides не конфликтует с уже загруженными."""
        for kind, names in (
            ("actions", manifest.provides.actions),
            ("repositories", manifest.provides.repositories),
            ("processors", manifest.provides.processors),
            ("sources", manifest.provides.sources),
            ("sinks", manifest.provides.sinks),
            ("schemas", manifest.provides.schemas),
        ):
            for name in names:
                owner = self._owners[kind].get(name)
                if owner is not None and owner != manifest.name:
                    raise PluginInventoryConflictError(
                        plugin=manifest.name, kind=kind, name=name, owner=owner
                    )

    def _record_owners(self, manifest: PluginManifestV11) -> None:
        """Запоминает имена из provides, чтобы детектить коллизии в будущем."""
        for kind, names in (
            ("actions", manifest.provides.actions),
            ("repositories", manifest.provides.repositories),
            ("processors", manifest.provides.processors),
            ("sources", manifest.provides.sources),
            ("sinks", manifest.provides.sinks),
            ("schemas", manifest.provides.schemas),
        ):
            for name in names:
                self._owners[kind][name] = manifest.name

    def _instantiate(self, manifest: PluginManifestV11) -> BasePlugin:
        """Импортирует ``entry_class`` и возвращает экземпляр плагина."""
        module_path, _, class_name = manifest.entry_class.rpartition(".")
        if not module_path or not class_name:
            raise ValueError(
                f"entry_class must be dotted path 'module.Class', "
                f"got {manifest.entry_class!r}"
            )
        module = importlib.import_module(module_path)
        target = getattr(module, class_name)
        if isinstance(target, type) and issubclass(target, BasePlugin):
            return target()
        # Factory-функция, возвращающая BasePlugin.
        if callable(target):
            instance = target()
            if not isinstance(instance, BasePlugin):
                raise TypeError(
                    f"entry_class {manifest.entry_class!r} factory returned "
                    f"{type(instance).__name__}, not BasePlugin"
                )
            return instance
        raise TypeError(
            f"entry_class {manifest.entry_class!r} is neither a BasePlugin "
            f"subclass nor a factory callable"
        )
