"""S198: CapabilityGatewayProtocol adapter поверх CapabilityFacade.

Заменяет direct ``CapabilityGate()`` создания в admin/api.py.
Использует существующий ``CapabilityFacade`` singleton.
"""
from __future__ import annotations

from typing import Any, Protocol


class _CapCheckProtocol(Protocol):
    """Minimal protocol matching CapabilityGatewayProtocol.check()."""


class FacadeCapabilityAdapter:
    """Adapt CapabilityFacade → CapabilityGatewayProtocol."""

    def __init__(self, facade: Any) -> None:
        self._facade = facade

    def check(
        self,
        plugin: str,
        capability: str,
        scope: str | None = None,
    ) -> None:
        """Proxy к CapabilityFacade.check с raise on deny."""
        self._facade.check(plugin, capability, scope)

    def check_tenant(
        self,
        capability: str,
        tenant: str,
        principal: str | None = None,
        scope: str | None = None,
    ) -> bool:
        """Proxy к CapabilityFacade.check_tenant."""
        return self._facade.check_tenant(
            capability, tenant, principal_id=principal, scope=scope
        )
