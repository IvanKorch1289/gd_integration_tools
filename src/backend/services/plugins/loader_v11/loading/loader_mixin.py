from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.core.interfaces.plugin import BasePlugin
    from src.backend.services.plugins.manifest_v11 import PluginManifestV11

import importlib

from src.backend.core.interfaces.plugin import BasePlugin, PluginContext
from src.backend.core.logging import get_logger
from src.backend.core.plugin_runtime.compat_checker import CompatViolation
from src.backend.core.security.capabilities import CapabilityError, CapabilityRef
from src.backend.services.plugins.manifest_v11 import (
    PluginManifestError,
    PluginManifestV11,
    load_plugin_manifest,
)
from src.backend.services.plugins.loader_v11.discovery import LoadedPluginV11
from src.backend.services.plugins.loader_v11.validation import (
    PluginInventoryConflictError,
)

_logger = get_logger("services.plugins.loader_v11")


class LoaderMixin:
    """plugin loading internals (_load_one BIG 253 LOC + _instantiate) для LoadingMixin. S63 W1 extraction."""

    __slots__ = ()

    async def _load_one(
        self,
        manifest_path: Path,
        *,
        compat_violations: tuple[CompatViolation, ...] = (),
        blocked: set[str] | None = None,
        parse_failures: dict[Path, str] | None = None,
        cycle_blocked: set[str] | None = None,
        cycle_reason: str | None = None,
    ) -> None:
        """Загрузить один плагин по ``plugin.toml``.

        Args:
            manifest_path: Путь к ``plugin.toml``.
            compat_violations: Заранее посчитанные нарушения compatibility
                matrix (см. :meth:`discover_and_load`).
            blocked: Имена плагинов, которые compat-чекер забраковал.
            parse_failures: Mapping ``manifest_path → ошибка`` парсинга,
                переданный из discover_and_load.
            cycle_blocked: Sprint 16 K5-W1 — имена плагинов, попавших в
                цикл зависимостей; помечаются ``status="failed"`` с
                ``reason=cycle_reason`` до import_module.
            cycle_reason: Текст причины для cycle_blocked плагинов.
        """
        blocked = blocked or set()
        parse_failures = parse_failures or {}
        cycle_blocked = cycle_blocked or set()
        cached_error = parse_failures.get(manifest_path)
        if cached_error is not None:
            _logger.warning(
                "Plugin manifest invalid (%s): %s", manifest_path, cached_error
            )
            self._loaded[manifest_path.parent.name] = LoadedPluginV11(
                name=manifest_path.parent.name,
                version="?",
                manifest_path=manifest_path,
                status="failed",
                reason=f"manifest_error: {cached_error}",
            )
            return

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

        if manifest.name in blocked:
            reasons = "; ".join(
                v.reason for v in compat_violations if v.plugin == manifest.name
            )
            self._loaded[manifest.name] = LoadedPluginV11(
                name=manifest.name,
                version=manifest.version,
                manifest_path=manifest_path,
                manifest=manifest,
                status="failed",
                reason=f"compat_conflict: {reasons}",
            )
            return

        if manifest.name in cycle_blocked:
            self._loaded[manifest.name] = LoadedPluginV11(
                name=manifest.name,
                version=manifest.version,
                manifest_path=manifest_path,
                manifest=manifest,
                status="failed",
                reason=cycle_reason or "dependency_cycle",
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

        # V15 GAP Gap 4: tenant-aware declarations (после declare, до import).
        # Backward compat (KIMI Q2): пустой tenants + tenant_aware=false —
        # silent fallback к system tenant (pre-sprint-36 поведение).
        # Пустой tenants + tenant_aware=true → warning (вероятно misconfig).
        #
        # Slice 1 caveat (KIMI risk §"CapabilityRef requires scope"): все
        # capabilities в :data:`DEFAULT_CAPABILITY_CATALOG` имеют
        # ``scope_required=True``, поэтому ``declare_tenant(scope=None)``
        # упадёт в :meth:`CapabilityVocabulary.validate_ref`. По плану
        # slice 1 это **ожидаемая** ситуация: scope для ``[[tenants]]``
        # ещё не реализован (следующий slice). Поэтому для таких
        # capabilities — warning + skip (НЕ fail). Плагин всё равно
        # грузится, runtime API :meth:`CapabilityGate.declare_tenant`
        # остаётся доступным для scope-aware регистрации.
        if not manifest.tenants and manifest.tenant_aware:
            _logger.warning(
                "Plugin %s is tenant_aware=true but has no [[tenants]] section; "
                "falling back to system tenant",
                manifest.name,
            )
        for tenant_decl in manifest.tenants:
            for cap_name in tenant_decl.capabilities:
                cap_ref = CapabilityRef(name=cap_name)  # scope=None в slice 1
                try:
                    self._gate.declare_tenant(
                        cap_ref, tenant=tenant_decl.name, principal=manifest.name
                    )
                except ValueError as exc:
                    # Slice 1 limitation: ``scope_required=True`` capabilities
                    # не могут быть задекларированы без scope. Warn + continue
                    # (плагин грузится, но tenant-таблица остаётся пустой).
                    _logger.warning(
                        "Plugin %s tenant capability %r skipped: %s "
                        "(slice 1 supports only capabilities with "
                        "scope_required=False; declare via "
                        "CapabilityGate.declare_tenant at runtime)",
                        manifest.name,
                        cap_name,
                        exc,
                    )
                except CapabilityError as exc:
                    # Hard fail: capability отсутствует в vocabulary или
                    # уже задекларирована. Schema-валидация должна была
                    # поймать unknown cap, но оставляем safety net.
                    _logger.warning(
                        "Plugin %s tenant capability allocation failed "
                        "(tenant=%s, capability=%s): %s",
                        manifest.name,
                        tenant_decl.name,
                        cap_name,
                        exc,
                    )
                    self._loaded[manifest.name] = LoadedPluginV11(
                        name=manifest.name,
                        version=manifest.version,
                        manifest_path=manifest_path,
                        manifest=manifest,
                        status="failed",
                        reason=f"tenant_capability_error: {exc}",
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
        plugin_root = manifest_path.parent
        pages_count = self._mount_frontend_pages(manifest.name, plugin_root)
        self._loaded[manifest.name] = LoadedPluginV11(
            name=manifest.name,
            version=manifest.version,
            manifest_path=manifest_path,
            manifest=manifest,
            status="loaded",
            instance=plugin,
            pages_count=pages_count,
        )
        _logger.info(
            "Plugin loaded (V11): %s v%s (%s) pages=%d",
            manifest.name,
            manifest.version,
            manifest_path,
            pages_count,
        )

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
