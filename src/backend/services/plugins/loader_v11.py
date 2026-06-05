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

from src.backend.core.interfaces.plugin import (
    ActionRegistryProtocol,
    BasePlugin,
    PluginContext,
    ProcessorRegistryProtocol,
    RepositoryRegistryProtocol,
)
from src.backend.core.plugin_runtime.compat_checker import (
    CompatViolation,
    check_compatibility,
)
from src.backend.core.plugin_runtime.dependency_resolver import (
    PluginDependencyCycleError,
    PluginGraphResolver,
)
from src.backend.core.security.capabilities import (
    CapabilityError,
    CapabilityGate,
    CapabilityRef,
)
from src.backend.services.plugins.manifest_v11 import (
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
    pages_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Сериализация для ``/api/v1/plugins/inventory``.

        Sprint 3: добавлены ``requires_core``, ``tenant_aware``,
        ``capabilities`` и ``provides`` — нужны marketplace-UI для
        отображения детализации плагина без отдельных endpoint'ов.
        """
        payload: dict[str, Any] = {
            "name": self.name,
            "version": self.version,
            "status": self.status,
            "reason": self.reason,
            "manifest_path": str(self.manifest_path),
            "pages_count": self.pages_count,
        }
        if self.manifest is not None:
            payload["requires_core"] = self.manifest.requires_core
            payload["tenant_aware"] = self.manifest.tenant_aware
            payload["description"] = self.manifest.description
            payload["capabilities"] = [str(c) for c in self.manifest.capabilities]
            payload["tenants"] = [
                {"name": t.name, "capabilities": list(t.capabilities)}
                for t in self.manifest.tenants
            ]
            payload["provides"] = {
                "actions": list(self.manifest.provides.actions),
                "repositories": list(self.manifest.provides.repositories),
                "processors": list(self.manifest.provides.processors),
                "sources": list(self.manifest.provides.sources),
                "sinks": list(self.manifest.provides.sinks),
                "schemas": list(self.manifest.provides.schemas),
            }
        return payload


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
        parsed_manifests: list[PluginManifestV11] = []
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

    def _topo_sort_non_blocked(
        self,
        parsed_manifests: list[PluginManifestV11],
        compat_blocked: set[str],
        cycle_blocked: set[str],
    ) -> tuple[str, ...]:
        """Применяет :class:`PluginGraphResolver` к не-blocked плагинам.

        Args:
            parsed_manifests: Все успешно распарсенные манифесты.
            compat_blocked: Имена, забракованные compat-checker'ом.
            cycle_blocked: Изменяемое множество — заполняется именами
                плагинов, образующих цикл (для последующей пометки
                ``status="failed"``).

        Returns:
            Кортеж имён в bootstrap-порядке для НЕ заблокированных
            плагинов. Если граф валит resolver, возвращается пустой
            кортеж и ``cycle_blocked`` пополняется именами участников
            цикла (или всеми не-blocked, если SDK не передал детали).
        """
        non_blocked = [m for m in parsed_manifests if m.name not in compat_blocked]
        if not non_blocked:
            return ()
        resolver = PluginGraphResolver()
        try:
            ordered = resolver.resolve({m.name: m for m in non_blocked})
        except PluginDependencyCycleError as exc:
            cycle_blocked.update(exc.cycle or {m.name for m in non_blocked})
            _logger.error(
                "Plugin dependency cycle detected: %s — affected plugins will fail", exc
            )
            return ()
        except KeyError as exc:
            cycle_blocked.update(m.name for m in non_blocked)
            _logger.error(
                "Plugin dependency resolution failed: %s — affected plugins will fail",
                exc,
            )
            return ()
        return tuple(m.name for m in ordered)

    def _reorder_manifest_paths(
        self, *, manifest_paths: list[Path], sorted_names: tuple[str, ...]
    ) -> list[Path]:
        """Возвращает ``manifest_paths`` в bootstrap-порядке.

        Args:
            manifest_paths: Исходный discovery-порядок (сортировка
                каталогов ``extensions/<name>/``).
            sorted_names: Результат :meth:`_topo_sort_non_blocked` —
                имена в bootstrap-порядке.

        Returns:
            Список Path: сначала пути, не попавшие в ``sorted_names``
            (parse-failed, blocked, cycle-blocked) в discovery-порядке,
            затем topo-sorted не-blocked плагины. Если ``sorted_names``
            пуст — список возвращается без изменений.

        Note:
            По валидации ADR-042 имя каталога ``extensions/<name>/``
            совпадает с ``manifest.name``; поэтому ``parent.name``
            пути — стабильный ключ сопоставления.
        """
        if not sorted_names:
            return list(manifest_paths)
        path_by_name: dict[str, Path] = {p.parent.name: p for p in manifest_paths}
        ordered_named: list[Path] = []
        used: set[Path] = set()
        for name in sorted_names:
            path = path_by_name.get(name)
            if path is not None and path not in used:
                ordered_named.append(path)
                used.add(path)
        remainder = [p for p in manifest_paths if p not in used]
        return remainder + ordered_named

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

    # ── private ──────────────────────────────────────────────────────

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

    # ── Sprint 3: plugin-local Streamlit pages auto-discovery ──────────

    def _plugin_page_prefix(self, plugin_name: str) -> str:
        """Префикс для смонтированных файлов: ``plugin_<name>_``."""
        return f"plugin_{plugin_name}_"

    def _mount_frontend_pages(self, plugin_name: str, plugin_root: Path) -> int:
        """Монтирует ``extensions/<name>/frontend/pages/*.py`` через symlinks.

        Args:
            plugin_name: Имя плагина (для префикса в pages-каталоге).
            plugin_root: Путь к каталогу плагина (там где ``plugin.toml``).

        Returns:
            Количество смонтированных файлов (0 если папка отсутствует
            или streamlit_pages_dir не сконфигурирован).
        """
        if self._streamlit_pages_dir is None:
            return 0
        pages_src = plugin_root / "frontend" / "pages"
        if not pages_src.is_dir():
            return 0
        try:
            self._streamlit_pages_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            _logger.warning(
                "Plugin %s: cannot create streamlit pages dir %s: %s",
                plugin_name,
                self._streamlit_pages_dir,
                exc,
            )
            return 0

        prefix = self._plugin_page_prefix(plugin_name)
        mounted = 0
        for src in sorted(pages_src.iterdir()):
            if not src.is_file() or src.suffix != ".py":
                continue
            dst = self._streamlit_pages_dir / f"{prefix}{src.name}"
            try:
                if dst.is_symlink() or dst.exists():
                    if dst.is_symlink() and dst.resolve() == src.resolve():
                        mounted += 1
                        continue
                    dst.unlink()
                dst.symlink_to(src.resolve())
            except OSError as exc:
                _logger.warning(
                    "Plugin %s: cannot symlink %s → %s: %s", plugin_name, src, dst, exc
                )
                continue
            mounted += 1
        return mounted

    def _unmount_frontend_pages(self, plugin_name: str) -> int:
        """Удаляет symlinks, смонтированные при load.

        Идемпотентно: при повторном вызове просто 0 удалений.
        """
        if self._streamlit_pages_dir is None or not self._streamlit_pages_dir.is_dir():
            return 0
        prefix = self._plugin_page_prefix(plugin_name)
        removed = 0
        for entry in self._streamlit_pages_dir.iterdir():
            if not entry.name.startswith(prefix):
                continue
            try:
                if entry.is_symlink() or entry.is_file():
                    entry.unlink()
                    removed += 1
            except OSError as exc:
                _logger.warning(
                    "Plugin %s: cannot remove %s: %s", plugin_name, entry, exc
                )
        return removed
