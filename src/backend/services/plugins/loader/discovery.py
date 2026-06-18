"""ADR-042 (R1.2) — :class:`PluginLoader` для in-tree extensions/<name>/.

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

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.backend.core.interfaces.plugin import BasePlugin
from src.backend.core.logging import get_logger
from src.backend.core.plugin_runtime.dependency_resolver import (
    PluginDependencyCycleError,
    PluginGraphResolver,
)
from src.backend.services.plugins.manifest_toml import PluginManifest

_logger = get_logger("services.plugins.loader")


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
class LoadedPlugin:
    """Метаданные одного загруженного плагина для admin-эндпоинта."""

    name: str
    version: str
    manifest_path: Path
    status: str  # "loaded" | "failed" | "skipped"
    reason: str | None = None
    instance: BasePlugin | None = None
    manifest: PluginManifest | None = None
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


class DiscoveryMixin:
    """Plugin discovery (topo sort, manifest path ordering) для PluginLoader. S52 W3 extraction."""

    __slots__ = ()

    # --- plugin discovery (dependency resolution + manifest path ordering) ---

    def _topo_sort_non_blocked(
        self,
        parsed_manifests: list[PluginManifest],
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
