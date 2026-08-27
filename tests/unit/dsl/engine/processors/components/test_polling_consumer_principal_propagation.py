"""P0 regression test (Cycle 34, production-grade plan).

``PollingConsumerProcessor.process`` пробрасывает principal/permissions из
ExecutionContext в ActionCommandSchema.meta (parity с cycle 24 fix
для DispatchActionProcessor).

Pre-fix: PollingConsumerProcessor создавал ActionCommandSchema без
principal/permissions → Tier-1/2 actions с permission checks теряли
auth context.

Запуск::

    .venv/bin/python -m pytest \\
      tests/unit/dsl/engine/processors/components/test_polling_consumer_principal_propagation.py -v
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.core.types.invocation_command import ActionCommandSchema
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.processors.components.pollingconsumerprocessor import (
    PollingConsumerProcessor,
)


@pytest.fixture
def mock_action_registry(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch ActionHandlerRegistry.dispatch на уровне класса."""
    from src.backend.dsl.commands.action_registry import ActionHandlerRegistry

    captured: dict[str, Any] = {}

    async def fake_dispatch(self: Any, command: ActionCommandSchema) -> dict:
        captured["command"] = command
        return ["result"]

    monkeypatch.setattr(ActionHandlerRegistry, "dispatch", fake_dispatch)
    return captured  # type: ignore[return-value]


class TestPollingConsumerPrincipalPropagation:
    """Cycle 34: PollingConsumerProcessor пробрасывает principal/permissions."""

    @pytest.mark.asyncio
    async def test_propagates_principal_from_context(
        self, mock_action_registry: dict[str, Any]
    ) -> None:
        """``context.principal='alice'`` → ``cmd.meta.principal='alice'``."""
        proc = PollingConsumerProcessor(
            source_action="test.action",
            payload={"k": "v"},
        )
        exchange = MagicMock()
        exchange.in_message.headers = {}

        context = ExecutionContext(
            route_id="test_route",
            principal="alice",
            permissions=("read:orders",),
        )

        await proc.process(exchange, context)

        cmd: ActionCommandSchema = mock_action_registry["command"]
        assert cmd.meta.principal == "alice", (
            f"Expected principal='alice', got {cmd.meta.principal!r}"
        )
        assert "read:orders" in cmd.meta.permissions, (
            f"Expected permissions contain 'read:orders', got {cmd.meta.permissions!r}"
        )

    @pytest.mark.asyncio
    async def test_anonymous_context_fails_closed(
        self, mock_action_registry: dict[str, Any]
    ) -> None:
        """``context.principal=''`` → ``cmd.meta.principal=''`` (anonymous)."""
        proc = PollingConsumerProcessor(source_action="test.action")
        exchange = MagicMock()
        exchange.in_message.headers = {}

        context = ExecutionContext(route_id="test_route")  # default principal=""

        await proc.process(exchange, context)

        cmd: ActionCommandSchema = mock_action_registry["command"]
        assert cmd.meta.principal == ""
        assert cmd.meta.permissions == []
