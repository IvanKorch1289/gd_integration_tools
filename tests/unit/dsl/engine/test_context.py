"""Tests for src.backend.dsl.engine.context."""

from __future__ import annotations

import logging

import pytest

from src.backend.dsl.engine.context import ExecutionContext


@pytest.mark.unit
class TestExecutionContext:
    """Tests for ExecutionContext dataclass."""

    def test_default_values(self) -> None:
        ctx = ExecutionContext()
        assert ctx.route_id == ""
        assert ctx.state == {}
        assert ctx.logger is None

    def test_get_existing_key(self) -> None:
        ctx = ExecutionContext()
        ctx.set("key", "value")
        assert ctx.get("key") == "value"

    def test_get_missing_key_with_default(self) -> None:
        ctx = ExecutionContext()
        assert ctx.get("missing", "default") == "default"

    def test_get_missing_key_none_default(self) -> None:
        ctx = ExecutionContext()
        assert ctx.get("missing") is None

    def test_set_overwrites(self) -> None:
        ctx = ExecutionContext()
        ctx.set("key", "first")
        ctx.set("key", "second")
        assert ctx.get("key") == "second"

    def test_state_isolation(self) -> None:
        ctx1 = ExecutionContext()
        ctx2 = ExecutionContext()
        ctx1.set("a", 1)
        assert "a" not in ctx2.state

    def test_route_id_field(self) -> None:
        ctx = ExecutionContext(route_id="route-42")
        assert ctx.route_id == "route-42"

    def test_logger_field(self) -> None:
        logger = logging.getLogger("test")
        ctx = ExecutionContext(logger=logger)
        assert ctx.logger is logger

    def test_slots_no_dict(self) -> None:
        ctx = ExecutionContext()
        assert not hasattr(ctx, "__dict__")
