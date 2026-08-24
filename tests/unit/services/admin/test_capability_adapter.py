"""S44 W7: unit tests for services/admin/_capability_adapter.py.

Per-agent-41 (W5 multi-agent analytics): bounded test for smallest 0%-
covered service. tests FacadeCapabilityAdapter: delegates check() and
check_tenant() to underlying CapabilityFacade instance.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from src.backend.services.admin._capability_adapter import FacadeCapabilityAdapter


class TestFacadeCapabilityAdapter:
    """Adapter: CapabilityFacade → CapabilityGatewayProtocol."""

    def test_init_stores_facade(self) -> None:
        """__init__ stores facade reference for proxy calls."""
        facade = MagicMock()
        adapter = FacadeCapabilityAdapter(facade=facade)
        assert adapter._facade is facade  # type: ignore[attr-defined]

    def test_check_delegates_to_facade(self) -> None:
        """check() proxies capability args to facade.check()."""
        facade = MagicMock()
        adapter = FacadeCapabilityAdapter(facade=facade)
        adapter.check(plugin="my_plugin", capability="read", scope="dev")
        facade.check.assert_called_once_with("my_plugin", "read", "dev")

    def test_check_propagates_facade_exception(self) -> None:
        """check() does not swallow facade exceptions."""
        facade = MagicMock()
        facade.check.side_effect = RuntimeError("denied")
        adapter = FacadeCapabilityAdapter(facade=facade)
        try:
            adapter.check(plugin="x", capability="y")
        except RuntimeError as exc:
            assert str(exc) == "denied"
        else:
            raise AssertionError("expected RuntimeError to propagate")

    def test_check_tenant_delegates_to_facade(self) -> None:
        """check_tenant() proxies capability, tenant, principal, scope."""
        facade = MagicMock()
        facade.check_tenant.return_value = True
        adapter = FacadeCapabilityAdapter(facade=facade)
        result = adapter.check_tenant(
            capability="read",
            tenant="tenant_a",
            principal="user_1",
            scope="prod",
        )
        assert result is True
        facade.check_tenant.assert_called_once_with(
            "read", "tenant_a", principal_id="user_1", scope="prod"
        )

    def test_check_tenant_returns_facade_decision(self) -> None:
        """check_tenant() returns facade.check_tenant() result."""
        facade = MagicMock()
        facade.check_tenant.return_value = False
        adapter = FacadeCapabilityAdapter(facade=facade)
        assert adapter.check_tenant("c", "t") is False

    def test_check_tenant_with_optional_none_args(self) -> None:
        """check_tenant() defaults principal=None and scope=None."""
        facade = MagicMock()
        facade.check_tenant.return_value = True
        adapter = FacadeCapabilityAdapter(facade=facade)
        adapter.check_tenant(capability="c", tenant="t")
        facade.check_tenant.assert_called_once_with(
            "c", "t", principal_id=None, scope=None
        )


def _accepts_any_facade(facade: Any) -> None:
    """Type-level: FacadeCapabilityAdapter accepts any (Any) facade.

    Runtime check: store and use adapter with a real (non-MagicMock)
    facade object. The adapter should not constrain facade type.
    """
    adapter = FacadeCapabilityAdapter(facade=facade)
    # Use adapter._facade to verify reference identity (no copy)
    assert adapter._facade is facade  # type: ignore[attr-defined]


def test_adapter_accepts_arbitrary_facade() -> None:
    """Type signature `facade: Any` allows any facade object."""

    class FakeFacade:
        def check(self, plugin: str, capability: str, scope: str | None = None) -> None:
            pass

        def check_tenant(
            self,
            capability: str,
            tenant: str,
            principal_id: str | None = None,
            scope: str | None = None,
        ) -> bool:
            return True

    _accepts_any_facade(FakeFacade())
