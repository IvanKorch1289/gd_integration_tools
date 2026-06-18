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


class ValidationMixin:
    """Plugin validation (inventory collisions, owner records) для PluginLoader. S52 W3 extraction."""

    # State attrs (declared on PluginLoader; mypy needs hint)
    _owners: dict[str, dict[str, str]]
    _loaded: dict[str, "LoadedPlugin"]
    _loaded_failed: list["LoadedPlugin"]
    _loaded_skipped: list["LoadedPlugin"]

    __slots__ = ()

    # --- plugin validation (inventory collision check + owner recording) ---

    def _check_inventory_collisions(self, manifest: PluginManifest) -> None:
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
        return None

    def _record_owners(self, manifest: PluginManifest) -> None:
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
        return None
