"""Connector Registry — singleton catalog."""

from __future__ import annotations

import logging
from typing import Any

from src.backend.core.connectors.base import (
    AuthModel,
    BaseConnector,
    ConnectorMetadata,
)

logger = logging.getLogger(__name__)

__all__ = ("ConnectorRegistry", "get_connector_registry")


class ConnectorRegistry:
    """In-memory registry всех connector'ов."""

    def __init__(self) -> None:
        self._connectors: dict[str, BaseConnector] = {}

    def register(self, connector: BaseConnector) -> None:
        """Register connector. Overwrites if name exists."""
        meta = connector.metadata()
        if not meta.name:
            raise ValueError("Connector must have non-empty metadata.name")
        if meta.name in self._connectors:
            logger.warning(
                "ConnectorRegistry: overwriting existing connector name=%s",
                meta.name,
            )
        self._connectors[meta.name] = connector
        logger.info(
            "ConnectorRegistry: registered name=%s version=%s category=%s",
            meta.name,
            meta.version,
            meta.category,
        )

    def unregister(self, name: str) -> None:
        """Удалить connector по name."""
        if name in self._connectors:
            del self._connectors[name]

    def get(self, name: str) -> BaseConnector | None:
        """Получить connector по name или None."""
        return self._connectors.get(name)

    def list_all(self) -> list[BaseConnector]:
        """Список всех connector'ов."""
        return list(self._connectors.values())

    def list_metadata(
        self,
        *,
        category: str | None = None,
        auth_model: AuthModel | None = None,
        tag: str | None = None,
    ) -> list[ConnectorMetadata]:
        """Список metadata с фильтрами (для UI catalog)."""
        result = []
        for c in self._connectors.values():
            meta = c.metadata()
            if category is not None and meta.category != category:
                continue
            if auth_model is not None and meta.auth_model != auth_model:
                continue
            if tag is not None and tag not in meta.tags:
                continue
            result.append(meta)
        return result

    def size(self) -> int:
        """Количество зарегистрированных connectors (test-only)."""
        return len(self._connectors)

    def clear(self) -> None:
        """Очистить registry (test-only)."""
        self._connectors.clear()


_registry: ConnectorRegistry | None = None


def get_connector_registry() -> ConnectorRegistry:
    """Module-level singleton."""
    global _registry
    if _registry is None:
        _registry = ConnectorRegistry()
    return _registry


def reset_connector_registry() -> None:
    """Reset singleton (test-only)."""
    global _registry
    _registry = None
