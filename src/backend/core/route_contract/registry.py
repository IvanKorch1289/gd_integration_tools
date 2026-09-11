"""Route Contract Registry — register/lookup contracts (Wave 1 P0 #25)."""

from __future__ import annotations

import logging
from typing import Any

from src.backend.core.route_contract.contract import RouteContract

logger = logging.getLogger(__name__)

__all__ = ("RouteContractRegistry", "get_route_contract_registry")


class RouteContractRegistry:
    """In-memory registry для RouteContract'ов."""

    def __init__(self) -> None:
        self._contracts: dict[str, RouteContract] = {}

    def register(self, contract: RouteContract) -> None:
        """Register contract. Overwrites existing route_id."""
        if contract.route_id in self._contracts:
            logger.warning(
                "RouteContractRegistry: overwriting existing route_id=%s",
                contract.route_id,
            )
        self._contracts[contract.route_id] = contract

    def unregister(self, route_id: str) -> None:
        if route_id in self._contracts:
            del self._contracts[route_id]

    def get(self, route_id: str) -> RouteContract | None:
        return self._contracts.get(route_id)

    def list_all(self) -> list[RouteContract]:
        return list(self._contracts.values())

    def list_by_owner(self, owner: str) -> list[RouteContract]:
        return [c for c in self._contracts.values() if c.owner == owner]

    def list_by_tag(self, tag: str) -> list[RouteContract]:
        return [c for c in self._contracts.values() if tag in c.tags]

    def size(self) -> int:
        return len(self._contracts)

    def clear(self) -> None:
        self._contracts.clear()


_registry: RouteContractRegistry | None = None


def get_route_contract_registry() -> RouteContractRegistry:
    global _registry
    if _registry is None:
        _registry = RouteContractRegistry()
    return _registry


def reset_route_contract_registry() -> None:
    global _registry
    _registry = None
