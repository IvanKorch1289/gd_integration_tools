"""ActionHandlerRegistry lookup & middleware methods (cycle 61).

Coverage of public methods that existing test_action_registry.py doesn't cover:
- get_metadata (lookup by action name)
- list_metadata (with and without transport filter)
- register_middleware + list_middleware (middleware chain)
- is_registered (registration check)
- list_actions (sorted action names)
- clear (full registry reset)

These methods are used by Gateway (Phase C) and various entrypoint
adapters, so the regression coverage is real value.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class TestActionHandlerRegistryLookup:
    """Lookup + middleware methods — round 61 test contract."""

    @pytest.fixture
    def registry(self):
        """Fresh ActionHandlerRegistry per test (no global state leak)."""
        from src.backend.dsl.commands.action_registry import (
            ActionHandlerRegistry,
            ActionHandlerSpec,
        )

        # Verify both imports work (used in tests below).
        assert ActionHandlerRegistry is not None
        assert ActionHandlerSpec is not None
        return ActionHandlerRegistry()

    @pytest.fixture
    def sample_handler(self):
        """Simple sync handler used for registration tests."""

        def handler(x: int) -> int:
            return x * 2

        return handler

    def test_get_metadata_returns_none_for_unregistered(
        self, registry
    ) -> None:
        """get_metadata returns None for unregistered action."""
        from src.backend.core.interfaces.action_dispatcher import (
            ActionMetadata,
        )

        metadata = ActionMetadata(
            action="nonexistent",
            input_model=None,
            output_model=None,
        )
        # Even with metadata in dict, get_metadata for unknown action returns None.
        assert registry.get_metadata("nonexistent") is None

    def test_register_with_metadata_then_get_metadata(
        self, registry, sample_handler
    ) -> None:
        """register_with_metadata stores metadata, get_metadata retrieves it."""
        from src.backend.core.interfaces.action_dispatcher import (
            ActionMetadata,
        )
        from src.backend.dsl.commands.action_registry import (
            ActionHandlerSpec,
        )

        metadata = ActionMetadata(
            action="test.cycle61",
            input_model=None,
            output_model=None,
            transports=("http", "grpc"),
        )
        # handler must be ActionHandlerSpec or None (per API contract).
        spec = ActionHandlerSpec(
            action="test.cycle61",
            service_getter=sample_handler,
            service_method="run",
            payload_model=None,
        )
        registry.register_with_metadata(
            action="test.cycle61", handler=spec, metadata=metadata
        )

        retrieved = registry.get_metadata("test.cycle61")
        assert retrieved is metadata, (
            "register_with_metadata + get_metadata should round-trip"
        )
        assert retrieved.action == "test.cycle61"
        assert "http" in retrieved.transports

    def test_register_with_metadata_action_mismatch_raises(
        self, registry, sample_handler
    ) -> None:
        """ValueError when metadata.action != action argument (cycle 133 invariant)."""
        from src.backend.core.interfaces.action_dispatcher import (
            ActionMetadata,
        )
        from src.backend.dsl.commands.action_registry import (
            ActionHandlerSpec,
        )

        metadata = ActionMetadata(
            action="different.name",
            input_model=None,
            output_model=None,
        )
        spec = ActionHandlerSpec(
            action="other.name",
            service_getter=sample_handler,
            service_method="run",
            payload_model=None,
        )
        with pytest.raises(ValueError, match="metadata.action"):
            registry.register_with_metadata(
                action="other.name", handler=spec, metadata=metadata
            )

    def test_list_metadata_sorted_by_action(
        self, registry, sample_handler
    ) -> None:
        """list_metadata returns sorted by action name."""
        from src.backend.core.interfaces.action_dispatcher import (
            ActionMetadata,
        )
        from src.backend.dsl.commands.action_registry import (
            ActionHandlerSpec,
        )

        for name in ("z.last", "a.first", "m.middle"):
            md = ActionMetadata(action=name, input_model=None, output_model=None)
            spec = ActionHandlerSpec(
                action=name,
                service_getter=sample_handler,
                service_method="run",
                payload_model=None,
            )
            registry.register_with_metadata(
                action=name, handler=spec, metadata=md
            )

        all_md = registry.list_metadata()
        names = [m.action for m in all_md]
        assert names == ["a.first", "m.middle", "z.last"], (
            f"list_metadata should be sorted, got {names}"
        )

    def test_list_metadata_filtered_by_transport(
        self, registry, sample_handler
    ) -> None:
        """list_metadata(transport=X) filters by transport membership."""
        from src.backend.core.interfaces.action_dispatcher import (
            ActionMetadata,
        )
        from src.backend.dsl.commands.action_registry import (
            ActionHandlerSpec,
        )

        # Register actions with different transports.
        for name, transports in [
            ("a.http_only", ("http",)),
            ("b.grpc_only", ("grpc",)),
            ("c.both", ("http", "grpc")),
            ("d.mqtt", ("mqtt",)),
        ]:
            md = ActionMetadata(
                action=name, input_model=None, output_model=None, transports=transports
            )
            spec = ActionHandlerSpec(
                action=name,
                service_getter=sample_handler,
                service_method="run",
                payload_model=None,
            )
            registry.register_with_metadata(
                action=name, handler=spec, metadata=md
            )

        http_only = registry.list_metadata(transport="http")
        http_names = sorted(m.action for m in http_only)
        assert http_names == ["a.http_only", "c.both"], (
            f"Expected ['a.http_only', 'c.both'], got {http_names}"
        )

        mqtt_only = registry.list_metadata(transport="mqtt")
        assert [m.action for m in mqtt_only] == ["d.mqtt"]

        # No matches → empty tuple.
        assert registry.list_metadata(transport="unknown") == ()

    def test_register_middleware_then_list_middleware(
        self, registry
    ) -> None:
        """register_middleware + list_middleware сохраняет порядок регистрации."""
        from src.backend.core.interfaces.action_dispatcher import (
            ActionMiddleware,
        )

        class M1(ActionMiddleware):
            async def process(self, command, call_next):
                return await call_next(command)

        class M2(ActionMiddleware):
            async def process(self, command, call_next):
                return await call_next(command)

        m1, m2 = M1(), M2()
        registry.register_middleware(m1)
        registry.register_middleware(m2)

        chain = registry.list_middleware()
        assert chain == (m1, m2), (
            f"Middleware chain order must be insertion order, got {chain}"
        )

    def test_is_registered_true_for_registered(
        self, registry, sample_handler
    ) -> None:
        """is_registered returns True after register(), False otherwise."""
        registry.register(
            action="test.cycle61",
            service_getter=lambda: None,
            service_method="run",
            payload_model=None,
        )

        assert registry.is_registered("test.cycle61") is True
        assert registry.is_registered("never.registered") is False

    def test_list_actions_returns_sorted(
        self, registry
    ) -> None:
        """list_actions возвращает sorted tuple of action names."""
        for name in ("z", "a", "m"):
            registry.register(
                action=name,
                service_getter=lambda: None,
                service_method="m",
                payload_model=None,
            )

        assert registry.list_actions() == ("a", "m", "z")

    def test_clear_resets_registry(
        self, registry, sample_handler
    ) -> None:
        """clear() removes handlers, metadata, middleware."""
        from src.backend.core.interfaces.action_dispatcher import (
            ActionMetadata,
        )
        from src.backend.dsl.commands.action_registry import (
            ActionHandlerSpec,
        )

        registry.register(
            action="test.a",
            service_getter=lambda: None,
            service_method="m",
            payload_model=None,
        )
        spec = ActionHandlerSpec(
            action="test.b",
            service_getter=sample_handler,
            service_method="m",
            payload_model=None,
        )
        registry.register_with_metadata(
            action="test.b",
            handler=spec,
            metadata=ActionMetadata(action="test.b", input_model=None, output_model=None),
        )

        assert len(registry.list_actions()) == 2
        assert len(registry.list_metadata()) == 2

        registry.clear()

        assert registry.list_actions() == ()
        assert registry.list_metadata() == ()
        assert registry.list_middleware() == ()
        # After clear, action is no longer registered.
        assert registry.is_registered("test.a") is False

    def test_register_with_metadata_only_without_handler(
        self, registry
    ) -> None:
        """register_with_metadata with handler=None — metadata-only registration.

        Use case: action handler registered separately via :meth:`register`,
        but metadata registered earlier for documentation/discovery.
        """
        from src.backend.core.interfaces.action_dispatcher import (
            ActionMetadata,
        )

        metadata = ActionMetadata(
            action="metadata_only",
            input_model=None,
            output_model=None,
        )
        # handler=None — no handler stored, but metadata stored.
        registry.register_with_metadata(
            action="metadata_only", handler=None, metadata=metadata
        )

        assert registry.get_metadata("metadata_only") is metadata
        # is_registered returns False because no handler stored.
        assert registry.is_registered("metadata_only") is False
