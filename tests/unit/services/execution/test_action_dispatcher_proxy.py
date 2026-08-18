"""TDD characterization для services/execution/action_dispatcher.py lazy proxy (Sprint 226)."""

from __future__ import annotations

import pytest


class TestActionDispatcherDSLExportsIdentity:
    """ActionHandlerRegistry + action_handler_registry identity preserved."""

    def test_action_handler_registry_identity(self) -> None:
        from src.backend.services.execution.action_dispatcher import (
            action_handler_registry,
        )
        from src.backend.dsl.commands.action_registry import (
            action_handler_registry as _orig,
        )

        assert action_handler_registry is _orig

    def test_action_handler_registry_class_identity(self) -> None:
        from src.backend.services.execution.action_dispatcher import (
            ActionHandlerRegistry,
        )
        from src.backend.dsl.commands.action_registry import (
            ActionHandlerRegistry as _orig,
        )

        assert ActionHandlerRegistry is _orig


class TestActionDispatcherClass:
    """DefaultActionDispatcher still works after refactor."""

    def test_default_action_dispatcher_class_exists(self) -> None:
        from src.backend.services.execution.action_dispatcher import (
            DefaultActionDispatcher,
        )

        assert DefaultActionDispatcher is not None

    def test_default_action_dispatcher_with_default_registry(self) -> None:
        """Default registry (action_handler_registry) accessible via lazy proxy."""
        from src.backend.services.execution.action_dispatcher import (
            DefaultActionDispatcher,
        )

        dispatcher = DefaultActionDispatcher()
        # Should NOT raise (registry was accessible via __getattr__)
        assert dispatcher is not None

    def test_get_action_dispatcher_callable(self) -> None:
        from src.backend.services.execution.action_dispatcher import (
            get_action_dispatcher,
        )

        assert callable(get_action_dispatcher)


class TestActionDispatcherUnknownAttribute:
    """Unknown attribute raises AttributeError."""

    def test_unknown_raises(self) -> None:
        from src.backend.services.execution import action_dispatcher

        with pytest.raises(AttributeError):
            _ = action_dispatcher.__getattr__("nonexistent_xyz")
