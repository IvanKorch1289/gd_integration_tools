from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.core.interfaces.plugin import BasePlugin
    from src.backend.services.plugins.manifest_v11 import PluginManifestV11


from dataclasses import dataclass
from typing import Any

from src.backend.core.interfaces.plugin import BasePlugin
from src.backend.core.logging import get_logger
from src.backend.services.plugins.manifest_v11 import PluginManifestV11

_logger = get_logger("services.plugins.loader_v11")


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


@dataclass
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
