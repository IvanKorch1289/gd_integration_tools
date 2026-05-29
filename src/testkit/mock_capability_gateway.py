"""MockCapabilityGateway — configurable test double for CapabilityGatewayProtocol.

K5 S19 W3 (S-L10-1). Implements :class:`CapabilityGatewayProtocol
<src.backend.core.interfaces.capability_gateway.CapabilityGatewayProtocol>`
with programmable behavior for unit tests.

Unlike :class:`CapabilityGate <src.backend.core.security.capabilities.gate.CapabilityGate>`
which uses the real capability vocabulary and scope-matching logic,
``MockCapabilityGateway`` allows tests to:

* Declare arbitrary capabilities without a vocabulary.
* Configure per-plugin per-capability allow/deny behavior.
* Record ``check()`` calls for assertion without depending on the
  real authorization chain.

Example::

    from src.testkit import MockCapabilityGateway, assert_audit_event

    gateway = MockCapabilityGateway()
    gateway.declare("my_plugin", ["db.read", "db.write"])
    gateway.add_check_result("my_plugin", "db.read", allowed=True)
    gateway.add_check_result("my_plugin", "db.write", allowed=False)

    # check() does not raise when allowed=True
    gateway.check("my_plugin", "db.read", scope="users")

    # check() raises CapabilityDeniedError when allowed=False
    with pytest.raises(CapabilityDeniedError):
        gateway.check("my_plugin", "db.write", scope="users")

    # Inspect calls for custom assertions
    assert gateway.check_calls == [
        ("my_plugin", "db.read", "users"),
    ]
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

__all__ = ("MockCapabilityGateway", "CapabilityDeniedError")


class CapabilityDeniedError(PermissionError):
    """Raised by :meth:`MockCapabilityGateway.check` when configured to deny."""


@dataclass(slots=True)
class _CheckCall:
    """Records a single ``check()`` invocation for later inspection."""

    plugin: str
    capability: str
    scope: str | None


class MockCapabilityGateway:
    """Configurable mock for :class:`CapabilityGatewayProtocol`.

    Attributes:
        check_calls: List of all ``(plugin, capability, scope)`` tuples
            passed to :meth:`check` since construction or the last
            :meth:`reset_calls` call.
    """

    def __init__(self, *, default_allowed: bool = True) -> None:
        """Initialize the mock.

        Args:
            default_allowed: If ``True`` (default), any capability check
                that hasn't been explicitly configured via
                :meth:`add_check_result` will be allowed. Set to ``False``
                to require explicit configuration for all expected checks.
        """
        self._declared: dict[str, tuple[str, ...]] = {}
        self._check_results: dict[tuple[str, str], bool] = {}
        self._default_allowed = default_allowed
        self._calls: list[_CheckCall] = []

    # ─── CapabilityGatewayProtocol ─────────────────────────────────────────────

    def check(self, plugin: str, capability: str, scope: str | None = None) -> None:
        """Check capability; raises ``CapabilityDeniedError`` if configured to deny.

        Records the call in :attr:`check_calls` for test inspection.
        """
        self._calls.append(
            _CheckCall(plugin=plugin, capability=capability, scope=scope)
        )
        key = (plugin, capability)
        allowed = self._check_results.get(key, self._default_allowed)
        if not allowed:
            raise CapabilityDeniedError(
                f"MockCapabilityGateway: {plugin}/{capability} denied (scope={scope!r})"
            )

    def declare(self, plugin: str, capabilities: Iterable[object]) -> None:
        """Declare ``capabilities`` for ``plugin``.

        ``capabilities`` can be strings (``"db.read"``) or
        :class:`CapabilityRef <src.backend.core.security.capabilities.types.CapabilityRef>`
        objects; only the names are stored.
        """
        names: list[str] = []
        for cap in capabilities:
            if hasattr(cap, "name"):
                # Assume CapabilityRef or similar duck-typed object
                names.append(str(cap.name))
            else:
                names.append(str(cap))
        self._declared[plugin] = tuple(names)

    def list_allocated(self, plugin: str) -> tuple[str, ...]:
        """Return the tuple of capability names declared for ``plugin``."""
        return self._declared.get(plugin, ())

    # ─── Test helpers ─────────────────────────────────────────────────────────

    def add_check_result(self, plugin: str, capability: str, *, allowed: bool) -> None:
        """Configure the result for a specific ``plugin``/``capability`` check.

        Args:
            plugin: Plugin identifier.
            capability: Capability name.
            allowed: If ``True``, ``check()`` will pass; if ``False``,
                ``check()`` will raise ``CapabilityDeniedError``.
        """
        self._check_results[(plugin, capability)] = allowed

    @property
    def check_calls(self) -> list[tuple[str, str, str | None]]:
        """Return logged check calls as ``[(plugin, capability, scope), ...]``."""
        return [(c.plugin, c.capability, c.scope) for c in self._calls]

    def reset_calls(self) -> None:
        """Clear :attr:`check_calls` between test assertions."""
        self._calls.clear()
