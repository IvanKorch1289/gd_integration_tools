"""P0 regression test (Cycle 24, production-grade plan).

``DispatchActionProcessor.process`` пробрасывает principal/permissions из
ExecutionContext в ActionCommandSchema.meta.

Pre-fix (REVIEW_2026-08-27 W-1): DSL-routed actions получали anonymous
principal/permissions → Tier-1/2 actions с permission checks теряли
auth context.

Post-fix: context.principal/context.permissions → cmd.meta.principal /
cmd.meta.permissions (parity с SOAP ActionHandler path, cycle 5 fix).

Cycle 57: refactored to use shared ``captured_action_command`` fixture
(cycle 45) вместо inline monkeypatch — убрано ~10 LOC boilerplate.

Запуск::

    .venv/bin/python -m pytest \\
      tests/unit/dsl/engine/processors/test_dispatch_action_principal_propagation.py -v
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.core.types.invocation_command import ActionCommandSchema
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.processors.core import DispatchActionProcessor


def _make_exchange(body: dict[str, Any] | None = None) -> MagicMock:
    """Helper: build mock Exchange с body + headers."""
    exchange = MagicMock()
    exchange.in_message.body = body if body is not None else {}
    exchange.in_message.headers = {}
    return exchange


class TestDispatchActionPrincipalPropagation:
    """Cycle 24: DSL DispatchAction пробрасывает principal/permissions."""

    @pytest.mark.asyncio
    async def test_propagates_principal_from_context(
        self, captured_action_command: dict[str, Any]
    ) -> None:
        """``context.principal='alice'`` → ``cmd.meta.principal='alice'``."""
        proc = DispatchActionProcessor(action="test.action")
        exchange = _make_exchange({"key": "value"})

        context = ExecutionContext(
            route_id="test_route", principal="alice", permissions=("read:orders",)
        )

        await proc.process(exchange, context)

        cmd: ActionCommandSchema = captured_action_command["command"]
        assert cmd.meta.principal == "alice", (
            f"Expected meta.principal='alice', got {cmd.meta.principal!r}"
        )
        assert "read:orders" in cmd.meta.permissions, (
            f"Expected permissions to contain 'read:orders', got {cmd.meta.permissions!r}"
        )

    @pytest.mark.asyncio
    async def test_anonymous_context_fails_closed(
        self, captured_action_command: dict[str, Any]
    ) -> None:
        """``context.principal=''`` → ``cmd.meta.principal=''`` (anonymous, fail-closed)."""
        proc = DispatchActionProcessor(action="test.action")
        exchange = _make_exchange()

        context = ExecutionContext(route_id="test_route")  # default principal=""

        await proc.process(exchange, context)

        cmd: ActionCommandSchema = captured_action_command["command"]
        assert cmd.meta.principal == "", (
            "Empty context.principal → empty cmd.meta.principal (fail-closed)"
        )
        assert cmd.meta.permissions == [], (
            "Empty context.permissions → empty cmd.meta.permissions"
        )


class TestDispatchActionBackwardsCompat:
    """Backward-compat: pre-fix callers (passing principal='') сохраняют поведение."""

    @pytest.mark.asyncio
    async def test_default_principal_empty(
        self, captured_action_command: dict[str, Any]
    ) -> None:
        """No kwargs to DispatchActionProcessor → principal='' по default."""
        proc = DispatchActionProcessor(action="test.action")
        exchange = _make_exchange()

        context = ExecutionContext(route_id="test_route")

        await proc.process(exchange, context)

        cmd: ActionCommandSchema = captured_action_command["command"]
        assert cmd.meta.principal == ""
        assert cmd.meta.permissions == []
