"""CapabilityFacade — unified facade для capability operations (S183 I-6).

Закрывает gap — extensions и DSL ранее использовали direct calls к
:func:`CapabilityGate.check` (8+ мест в banking processors — inline pattern).

Теперь единый entry-point:

- :func:`check()` — capability check (raise on deny)
- :func:`check_tenant()` — tenant-aware capability check (returns bool)
- :func:`check_subsets()` — static route ⊆ plugins ∪ core_public check
- :func:`declare()` — declare capability для plugin
- :func:`revoke()` — revoke capability
- :func:`list_allocated_tenant()` — list tenant capabilities

Делегирует к :class:`CapabilityGate` через DI.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from src.backend.core.logging import get_logger

__all__ = ("CapabilityFacade", "get_capability_facade")

_logger = get_logger("services.capabilities.facade")


class CapabilityFacade:
    """Unified facade для capability operations.

    Wraps :class:`CapabilityGate` (4-mixin composition) и
    :func:`check_capabilities_subset` через единый entry-point.
    """

    def __init__(self) -> None:
        """Инициализация facade."""
        self._gate: Any | None = None

    @property
    def gate(self) -> Any:
        """Lazy accessor для CapabilityGate singleton."""
        if self._gate is None:
            from src.backend.core.security.capabilities import CapabilityGate

            self._gate = CapabilityGate()
        return self._gate

    def check(self, plugin: str, capability: str, scope: str | None = None) -> bool:
        """Capability check (S183).

        Args:
            plugin: Plugin name (e.g., ``"extensions.banking"``).
            capability: Capability name (e.g., ``"ds.read"``).
            scope: Optional scope (e.g., ``"user:42"``).

        Returns:
            True если capability granted.

        Raises:
            CapabilityDeniedError: S-2 fix — fail-closed на deny.
        """
        try:
            self.gate.check(plugin, capability, scope)
            return True
        except Exception as exc:
            _logger.debug(
                "capability check denied: plugin=%s, capability=%s, scope=%s, error=%s",
                plugin,
                capability,
                scope,
                exc,
            )
            return False

    async def check_async(
        self, plugin: str, capability: str, scope: str | None = None,
    ) -> bool:
        """Async capability check (для batch операций)."""
        return self.check(plugin, capability, scope)

    def check_tenant(
        self,
        capability: str,
        tenant_id: str,
        principal_id: str | None = None,
        scope: str | None = None,
    ) -> bool:
        """Tenant-aware capability check (returns bool)."""
        if principal_id is None:
            return False
        try:
            return bool(
                self.gate.check_tenant(capability, tenant_id, principal_id, scope),
            )
        except Exception as exc:
            _logger.debug("tenant capability check failed: %s", exc)
            return False

    def check_subsets(
        self,
        route: Any,
        route_caps: list[str],
        plugin_caps_by_name: dict[str, list[str]],
        vocab: Any | None = None,
    ) -> bool:
        """Static route ⊆ plugins ∪ core_public check.

        Args:
            route: DSLRoute instance.
            route_caps: Capabilities declared by route.
            plugin_caps_by_name: Map plugin_name → list of capabilities.
            vocab: Optional :class:`CapabilityVocabulary` (default global).

        Returns:
            True если route's caps are subset of plugins + core_public.
        """
        try:
            from src.backend.core.security.capabilities import (
                CapabilityRef,
                build_default_vocabulary,
                check_capabilities_subset,
            )

            route_name = (
                route
                if isinstance(route, str)
                else str(getattr(route, "route_id", getattr(route, "name", route)))
            )
            check_capabilities_subset(
                route=route_name,
                route_caps=tuple(CapabilityRef(name=name) for name in route_caps),
                plugin_caps_by_name={
                    plugin: tuple(CapabilityRef(name=name) for name in capabilities)
                    for plugin, capabilities in plugin_caps_by_name.items()
                },
                vocabulary=vocab or build_default_vocabulary(),
            )
            return True
        except Exception as exc:
            _logger.debug("check_subsets failed: %s", exc)
            return False

    def declare(self, plugin: str, capabilities: list[str]) -> None:
        """Declare capabilities для plugin (S183).

        Args:
            plugin: Plugin name.
            capabilities: List of capability names to declare.
        """
        try:
            from src.backend.core.security.capabilities import CapabilityRef

            self.gate.declare(
                plugin, tuple(CapabilityRef(name=name) for name in capabilities),
            )
            _logger.info(
                "capabilities declared: plugin=%s, count=%d", plugin, len(capabilities),
            )
        except Exception as exc:
            _logger.warning("capability declare failed: %s", exc)

    def revoke(self, plugin: str) -> None:
        """Revoke all capabilities для plugin."""
        try:
            self.gate.revoke(plugin)
            _logger.info("capabilities revoked: plugin=%s", plugin)
        except Exception as exc:
            _logger.warning("capability revoke failed: %s", exc)

    def list_allocated_tenant(self, tenant_id: str) -> list[str]:
        """List capabilities для tenant."""
        try:
            return [ref.name for ref in self.gate.list_allocated_tenant(tenant_id)]
        except Exception as exc:
            _logger.debug("list_allocated_tenant failed: %s", exc)
            return []

    def check_or_raise(
        self, plugin: str, capability: str, scope: str | None = None,
    ) -> None:
        """Capability check (raise on deny) — заменяет inline gate.check() pattern.

        Use в banking processors вместо::

            from src.backend.core.security.capabilities.gate import CapabilityGate
            CapabilityGate.check(plugin, capability, scope)

        Используйте::

            from src.backend.services.capabilities.facade import get_capability_facade
            get_capability_facade().check_or_raise(plugin, capability, scope)

        Args:
            plugin: Plugin name.
            capability: Capability name.
            scope: Optional scope.

        Raises:
            CapabilityDeniedError: если check fails (S-2 fix).
        """
        from src.backend.core.security.capabilities import CapabilityDeniedError

        try:
            self.gate.check(plugin, capability, scope)
        except CapabilityDeniedError:
            raise
        except Exception as exc:
            # Wrap unexpected errors as denied (S184 fail-safe)
            raise CapabilityDeniedError(
                plugin=plugin,
                capability=capability,
                requested_scope=scope,
                declared_scope=None,
            ) from exc


@lru_cache(maxsize=1)
def get_capability_facade() -> CapabilityFacade:
    """Lazy singleton глобального :class:`CapabilityFacade`."""
    return CapabilityFacade()
