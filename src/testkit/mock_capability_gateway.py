"""MockCapabilityGateway — mock implementation of CapabilityGatewayProtocol.

:class:`MockCapabilityGateway` implements :class:`CapabilityGatewayProtocol`
for use in unit tests. It allows setting up expected capabilities declaratively
and tracking check/declare calls for assertions.

Этот модуль — часть ``src/testkit/`` public API (K5 S19 W3).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from src.backend.core.interfaces.capability_gateway import CapabilityGatewayProtocol

__all__ = ("MockCapabilityGateway",)


@dataclass
class CapabilityCheck:
    """Record of a single capability check."""

    plugin: str
    capability: str
    scope: str | None
    outcome: str  # "granted" or "denied"


@dataclass
class MockCapabilityGateway:
    """Mock :class:`CapabilityGatewayProtocol` для unit-тестов.

    Features:
        * Declarative setup: use ``declare(plugin, capabilities)`` to set up
          expected capabilities.
        * Tracking: ``checks`` records every ``check()`` call.
        * Configurable: ``deny_unknown`` controls behavior for undeclared
          plugin/capability pairs.
        * ``check`` raises :class:`CapabilityDeniedError` by default when
          capability is not declared or scope doesn't match.

    Example:
        >>> gateway = MockCapabilityGateway()
        >>> gateway.declare("my-plugin", [CapabilityRef(name="db.read")])
        >>> gateway.check("my-plugin", "db.read", None)  # OK
        >>> assert len(gateway.checks) == 1
    """

    _declarations: dict[str, dict[str, str | None]] = field(default_factory=dict)
    checks: list[CapabilityCheck] = field(default_factory=list)
    deny_unknown: bool = True  # If False, unknown capabilities are auto-granted

    def check(
        self, plugin: str, capability: str, scope: str | None = None
    ) -> None:
        """Проверить capability; raise CapabilityDeniedError если не разрешена.

        Args:
            plugin: имя плагина.
            capability: имя capability.
            scope: запрошенный scope.

        Raises:
            CapabilityDeniedError: если capability не задекларирована
                или scope не покрывается.
        """
        from src.backend.core.security.capabilities.errors import CapabilityDeniedError

        declared = self._declarations.get(plugin, {}).get(capability)
        if declared is None:
            self.checks.append(CapabilityCheck(plugin, capability, scope, "denied"))
            if self.deny_unknown:
                raise CapabilityDeniedError(
                    plugin=plugin,
                    capability=capability,
                    requested_scope=scope,
                    declared_scope=None,
                )
            return

        # Scope None means any scope is OK
        if declared is not None and scope is not None and declared != scope:
            self.checks.append(CapabilityCheck(plugin, capability, scope, "denied"))
            if self.deny_unknown:
                raise CapabilityDeniedError(
                    plugin=plugin,
                    capability=capability,
                    requested_scope=scope,
                    declared_scope=declared,
                )
            return

        self.checks.append(CapabilityCheck(plugin, capability, scope, "granted"))

    def declare(self, plugin: str, capabilities: Iterable[object]) -> None:
        """Задекларировать capabilities для плагина.

        Args:
            plugin: имя плагина.
            capabilities: iterable of CapabilityRef objects (or objects
                with ``.name`` and optional ``.scope`` attributes).
        """
        bucket = self._declarations.setdefault(plugin, {})
        for cap in capabilities:
            name: str
            scope: str | None
            if hasattr(cap, "name"):
                name = cap.name  # type: ignore[attr-defined]
                scope = getattr(cap, "scope", None)
            elif isinstance(cap, str):
                name = cap
                scope = None
            else:
                name = str(cap)
                scope = None
            bucket[name] = scope

    def list_allocated(self, plugin: str) -> tuple[str, ...]:
        """Вернуть имена задекларированных capabilities для плагина."""
        return tuple(self._declarations.get(plugin, {}).keys())

    def reset(self) -> None:
        """Очистить все declarations и check history."""
        self._declarations.clear()
        self.checks.clear()

    def assert_checked(
        self,
        plugin: str,
        capability: str,
        *,
        scope: str | None = None,
        times: int = 1,
    ) -> None:
        """Assert that capability was checked specific number of times.

        Args:
            plugin: имя плагина.
            capability: имя capability.
            scope: опционально проверенный scope.
            times: ожидаемое количество вызовов.

        Raises:
            AssertionError: если количество не совпадает.
        """
        matching = [
            c for c in self.checks
            if c.plugin == plugin and c.capability == capability and c.scope == scope
        ]
        actual = len(matching)
        if actual != times:
            raise AssertionError(
                f"Expected {plugin}/{capability} (scope={scope!r}) "
                f"to be checked {times} time(s), got {actual}"
            )

    def assert_granted(
        self,
        plugin: str,
        capability: str,
        *,
        scope: str | None = None,
    ) -> None:
        """Assert that capability check resulted in 'granted'."""
        matching = [
            c for c in self.checks
            if c.plugin == plugin
            and c.capability == capability
            and c.scope == scope
            and c.outcome == "granted"
        ]
        if not matching:
            raise AssertionError(
                f"Expected {plugin}/{capability} (scope={scope!r}) "
                f"to be granted, but was not"
            )

    def assert_denied(
        self,
        plugin: str,
        capability: str,
        *,
        scope: str | None = None,
    ) -> None:
        """Assert that capability check resulted in 'denied'."""
        matching = [
            c for c in self.checks
            if c.plugin == plugin
            and c.capability == capability
            and c.scope == scope
            and c.outcome == "denied"
        ]
        if not matching:
            raise AssertionError(
                f"Expected {plugin}/{capability} (scope={scope!r}) "
                f"to be denied, but was not"
            )
