"""P0 regression test (Cycle 38, production-grade plan).

``action_dispatcher._terminal_handler`` пробрасывает principal/permissions
из DispatchContext в ActionCommandSchema.meta (parity с cycle 24/34/35).

Pre-fix: ActionCommandSchema создавался без principal/permissions → Tier-1/2
action handlers получали anonymous principal для всех middleware-chain paths.

Запуск::

    .venv/bin/python -m pytest \\
      tests/unit/services/execution/test_action_dispatcher_principal.py -v
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.interfaces.action_dispatcher import DispatchContext
from src.backend.core.types.invocation_command import ActionCommandSchema
from src.backend.services.execution.action_dispatcher import DefaultActionDispatcher


class TestDispatchContextPrincipal:
    """Cycle 38: DispatchContext.principal + permissions defaults."""

    def test_default_principal_empty(self) -> None:
        """``DispatchContext()`` → principal='', permissions=()."""
        ctx = DispatchContext()
        assert ctx.principal == "", "Default principal должен быть пустым"
        assert ctx.permissions == (), "Default permissions должен быть пустым"

    def test_with_principal(self) -> None:
        """``DispatchContext(principal='alice', permissions=(...))``."""
        ctx = DispatchContext(
            principal="alice",
            permissions=("read:orders", "write:orders"),
        )
        assert ctx.principal == "alice"
        assert ctx.permissions == ("read:orders", "write:orders")


class TestActionDispatcherPrincipalPropagation:
    """Cycle 38: _terminal_handler пробрасывает principal/permissions."""

    @pytest.mark.asyncio
    async def test_terminal_handler_propagates_principal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``_terminal_handler`` пробрасывает principal из context в ActionCommandSchema.meta."""
        captured: dict[str, Any] = {}

        def fake_dispatch_factory() -> Any:
            async def fake_dispatch(command: ActionCommandSchema) -> dict:
                captured["command"] = command
                return {"result": "ok"}
            return fake_dispatch

        # Mock registry
        registry = MagicMock()
        registry.dispatch = AsyncMock(side_effect=fake_dispatch_factory())
        # Use real dispatcher with mocked registry
        dispatcher = DefaultActionDispatcher.__new__(DefaultActionDispatcher)
        dispatcher._registry = registry

        ctx = DispatchContext(
            principal="dave",
            permissions=("admin",),
        )

        # _terminal_handler — bound method, call via dispatcher instance
        bound_method = DefaultActionDispatcher._terminal_handler
        await bound_method(
            dispatcher,
            action="test.action",
            payload={"k": "v"},
            context=ctx,
        )

        cmd: ActionCommandSchema = captured["command"]
        assert cmd.meta.principal == "dave", (
            f"Expected meta.principal='dave', got {cmd.meta.principal!r}"
        )
        assert "admin" in cmd.meta.permissions, (
            f"Expected permissions contain 'admin', got {cmd.meta.permissions!r}"
        )
