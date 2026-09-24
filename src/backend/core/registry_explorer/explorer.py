"""Registry Explorer — pure-Python unified view (Wave 2 DX #54)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

__all__ = (
    "ActionEntry",
    "ConnectorEntry",
    "RegistryExplorer",
    "RouteEntry",
    "get_registry_explorer",
)


@dataclass(slots=True)
class RouteEntry:
    """Route metadata."""

    id: str
    source: str = ""
    description: str = ""
    owner: str = ""
    timeout_seconds: float = 30.0
    tags: list[str] = field(default_factory=list)
    tenant_id: str = "*"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConnectorEntry:
    """Connector metadata."""

    name: str
    category: str = ""  # "http" | "soap" | "db" | "queue" | "external"
    auth: str = ""  # "api_key" | "bearer" | "oauth2" | ...
    base_url: str = ""
    description: str = ""
    owner: str = ""
    version: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ActionEntry:
    """Action metadata."""

    name: str
    description: str = ""
    params: list[str] = field(default_factory=list)
    side_effect: str = ""  # "read" | "write" | "external" | "idempotent"
    owner: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class RegistryExplorer:
    """Unified registry view для routes/connectors/actions."""

    def __init__(self) -> None:
        self._routes: dict[str, RouteEntry] = {}
        self._connectors: dict[str, ConnectorEntry] = {}
        self._actions: dict[str, ActionEntry] = {}

    # ─── Routes ───────────────────────────────────────────

    def register_route(self, route: RouteEntry) -> None:
        """Добавить/заменить маршрут по ``route.id``."""
        self._routes[route.id] = route

    def find_route(self, route_id: str) -> RouteEntry | None:
        """Найти маршрут по id; ``None`` если отсутствует."""
        return self._routes.get(route_id)

    def list_routes(self) -> list[RouteEntry]:
        """Все зарегистрированные маршруты (порядок вставки)."""
        return list(self._routes.values())

    def list_routes_by_owner(self, owner: str) -> list[RouteEntry]:
        """Маршруты конкретного владельца (точное совпадение)."""
        return [r for r in self._routes.values() if r.owner == owner]

    def list_routes_by_tag(self, tag: str) -> list[RouteEntry]:
        """Маршруты, содержащие ``tag`` в списке тегов."""
        return [r for r in self._routes.values() if tag in r.tags]

    def search_routes(
        self,
        *,
        owner: str | None = None,
        tag: str | None = None,
        tenant_id: str | None = None,
    ) -> list[RouteEntry]:
        """Multi-criteria search."""
        result = list(self._routes.values())
        if owner is not None:
            result = [r for r in result if r.owner == owner]
        if tag is not None:
            result = [r for r in result if tag in r.tags]
        if tenant_id is not None:
            result = [r for r in result if r.tenant_id == tenant_id]
        return result

    def route_count(self) -> int:
        """Количество зарегистрированных маршрутов."""
        return len(self._routes)

    # ─── Connectors ────────────────────────────────────────

    def register_connector(self, connector: ConnectorEntry) -> None:
        """Добавить/заменить коннектор по ``connector.name``."""
        self._connectors[connector.name] = connector

    def find_connector(self, name: str) -> ConnectorEntry | None:
        """Найти коннектор по имени; ``None`` если отсутствует."""
        return self._connectors.get(name)

    def list_connectors(self) -> list[ConnectorEntry]:
        """Все зарегистрированные коннекторы."""
        return list(self._connectors.values())

    def list_connectors_by_category(self, category: str) -> list[ConnectorEntry]:
        """Коннекторы категории (http/soap/db/queue/external)."""
        return [c for c in self._connectors.values() if c.category == category]

    def list_connectors_by_tag(self, tag: str) -> list[ConnectorEntry]:
        """Коннекторы, содержащие ``tag`` в списке тегов."""
        return [c for c in self._connectors.values() if tag in c.tags]

    def connector_count(self) -> int:
        """Количество зарегистрированных коннекторов."""
        return len(self._connectors)

    # ─── Actions ──────────────────────────────────────────

    def register_action(self, action: ActionEntry) -> None:
        """Добавить/заменить action по ``action.name``."""
        self._actions[action.name] = action

    def find_action(self, name: str) -> ActionEntry | None:
        """Найти action по имени; ``None`` если отсутствует."""
        return self._actions.get(name)

    def list_actions(self) -> list[ActionEntry]:
        """Все зарегистрированные actions."""
        return list(self._actions.values())

    def action_count(self) -> int:
        """Количество зарегистрированных actions."""
        return len(self._actions)

    # ─── Bulk / Export ────────────────────────────────────

    def summary(self) -> dict[str, int]:
        """Get counts для UI dashboard."""
        return {
            "routes": self.route_count(),
            "connectors": self.connector_count(),
            "actions": self.action_count(),
        }

    def to_dict(self) -> dict[str, Any]:
        """Full export для UI consumption."""
        return {
            "routes": [
                {
                    "id": r.id,
                    "source": r.source,
                    "description": r.description,
                    "owner": r.owner,
                    "timeout_seconds": r.timeout_seconds,
                    "tags": list(r.tags),
                    "tenant_id": r.tenant_id,
                }
                for r in self._routes.values()
            ],
            "connectors": [
                {
                    "name": c.name,
                    "category": c.category,
                    "auth": c.auth,
                    "base_url": c.base_url,
                    "description": c.description,
                    "owner": c.owner,
                    "version": c.version,
                    "tags": list(c.tags),
                }
                for c in self._connectors.values()
            ],
            "actions": [
                {
                    "name": a.name,
                    "description": a.description,
                    "params": list(a.params),
                    "side_effect": a.side_effect,
                    "owner": a.owner,
                    "tags": list(a.tags),
                }
                for a in self._actions.values()
            ],
            "summary": self.summary(),
        }

    def clear(self) -> None:
        """Полный сброс всех трёх реестров (для тестов/reload)."""
        self._routes.clear()
        self._connectors.clear()
        self._actions.clear()


_explorer: RegistryExplorer | None = None


def get_registry_explorer() -> RegistryExplorer:
    """Singleton-доступ к общему ``RegistryExplorer``."""
    global _explorer
    if _explorer is None:
        _explorer = RegistryExplorer()
    return _explorer


def reset_registry_explorer() -> None:
    """Сбросить singleton (следующий ``get_`` создаст новый)."""
    global _explorer
    _explorer = None
