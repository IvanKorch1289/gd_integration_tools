"""Unit tests for BaseEntrypoint and dispatch_action."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.entrypoints.base import BaseEntrypoint, dispatch_action


@pytest.mark.asyncio
async def test_dispatch_action_success() -> None:
    with patch("src.backend.entrypoints.base.action_handler_registry") as mock_reg:
        mock_reg.dispatch = AsyncMock(return_value={"ok": True})
        result = await dispatch_action(
            action="orders.create",
            payload={"x": 1},
            source="rest",
            correlation_id="abc",
            tenant_id="t1",
        )
        assert result == {"ok": True}
        call_args = mock_reg.dispatch.call_args[0][0]
        assert call_args.action == "orders.create"
        assert call_args.meta.source == "rest"
        assert call_args.payload == {"x": 1}


@pytest.mark.asyncio
async def test_dispatch_action_generates_correlation_id() -> None:
    with patch("src.backend.entrypoints.base.action_handler_registry") as mock_reg:
        mock_reg.dispatch = AsyncMock(return_value={})
        await dispatch_action(action="test", source="grpc")
        call_args = mock_reg.dispatch.call_args[0][0]
        assert call_args.action == "test"
        assert call_args.meta.source == "grpc"


@pytest.mark.asyncio
async def test_dispatch_action_propagates_error() -> None:
    with patch("src.backend.entrypoints.base.action_handler_registry") as mock_reg:
        mock_reg.dispatch = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(RuntimeError, match="boom"):
            await dispatch_action(action="test", source="rest")


@pytest.mark.asyncio
async def test_dispatch_action_extra_meta() -> None:
    with patch("src.backend.entrypoints.base.action_handler_registry") as mock_reg:
        mock_reg.dispatch = AsyncMock(return_value={})
        await dispatch_action(
            action="test", source="rest", extra_meta={"custom": "val"}
        )
        call_args = mock_reg.dispatch.call_args[0][0]
        assert call_args.action == "test"


class DummyEntrypoint(BaseEntrypoint):
    protocol = "dummy"

    async def handle(self, *args: Any, **kwargs: Any) -> Any:
        return "handled"


@pytest.mark.asyncio
async def test_base_entrypoint_dispatch() -> None:
    ep = DummyEntrypoint()
    with patch("src.backend.entrypoints.base.action_handler_registry") as mock_reg:
        mock_reg.dispatch = AsyncMock(return_value={"result": 1})
        result = await ep.dispatch(action="test")
        assert result == {"result": 1}
        call_args = mock_reg.dispatch.call_args[0][0]
        assert call_args.meta.source == "dummy"


def test_base_entrypoint_serialize_result() -> None:
    ep = DummyEntrypoint()
    assert ep.serialize_result({"x": 1}) == {"x": 1}


def test_base_entrypoint_format_error() -> None:
    ep = DummyEntrypoint()
    err = ep.format_error(ValueError("bad"))
    assert err["error"] == "ValueError"
    assert err["message"] == "bad"
    assert err["protocol"] == "dummy"
