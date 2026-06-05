"""Unit tests for workflow_tools module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from src.backend.entrypoints.mcp.workflow_tools import (
    _sanitize_tool_name,
    _tool_description,
    register_workflow_tools,
    _trigger_and_maybe_wait,
)
from src.backend.workflows.registry import WorkflowDescriptor


class TestSanitizeToolName:
    """Tests for _sanitize_tool_name."""

    def test_simple(self) -> None:
        assert _sanitize_tool_name("orders.create") == "workflow_orders_create"

    def test_dashes(self) -> None:
        assert _sanitize_tool_name("orders.get-by-id") == "workflow_orders_get_by_id"

    def test_slashes(self) -> None:
        assert _sanitize_tool_name("orders/get") == "workflow_orders_get"


class TestToolDescription:
    """Tests for _tool_description."""

    def test_with_description_and_tags(self) -> None:
        desc = WorkflowDescriptor(
            name="wf1", description="Do thing", tags={"a", "b"}, route_id="r1"
        )
        result = _tool_description(desc)
        assert "Do thing" in result
        assert "a" in result
        assert "b" in result

    def test_without_description(self) -> None:
        desc = WorkflowDescriptor(name="wf1", description="", tags=set(), route_id="r1")
        result = _tool_description(desc)
        assert "wf1" in result


class TestRegisterWorkflowTools:
    """Tests for register_workflow_tools."""

    def test_registers_tools(self) -> None:
        mock_mcp = MagicMock()
        desc = WorkflowDescriptor(name="wf1", description="", tags=set(), route_id="r1")
        with patch(
            "src.backend.entrypoints.mcp.workflow_tools.workflow_registry.list_all",
            return_value=[desc],
        ):
            with patch(
                "src.backend.entrypoints.mcp.workflow_tools.workflow_registry.get_route_id",
                return_value="r1",
            ):
                register_workflow_tools(mock_mcp)
        assert mock_mcp.tool.call_count >= 1

    def test_skips_missing_route_id(self) -> None:
        mock_mcp = MagicMock()
        desc = WorkflowDescriptor(name="wf1", description="", tags=set(), route_id="r1")
        with patch(
            "src.backend.entrypoints.mcp.workflow_tools.workflow_registry.list_all",
            return_value=[desc],
        ):
            with patch(
                "src.backend.entrypoints.mcp.workflow_tools.workflow_registry.get_route_id",
                return_value=None,
            ):
                register_workflow_tools(mock_mcp)
        mock_mcp.tool.assert_not_called()


class TestTriggerAndMaybeWait:
    """Tests for _trigger_and_maybe_wait."""

    @pytest.mark.asyncio
    async def test_no_wait_returns_pending(self) -> None:
        mock_store_cls = MagicMock()
        mock_store = AsyncMock()
        mock_store.create.return_value = UUID("12345678-1234-5678-1234-567812345678")
        mock_store_cls.return_value = mock_store

        mock_status = MagicMock()
        mock_status.pending.value = "pending"

        with patch(
            "src.backend.entrypoints.mcp.workflow_tools.get_workflow_state_store_provider",
            return_value=mock_store_cls,
        ):
            with patch(
                "src.backend.entrypoints.mcp.workflow_tools.get_workflow_status_enum_provider",
                return_value=mock_status,
            ):
                with patch(
                    "src.backend.entrypoints.mcp.workflow_tools.action_handler_registry.is_registered",
                    return_value=False,
                ):
                    result = await _trigger_and_maybe_wait(
                        workflow_name="wf1",
                        route_id="r1",
                        payload={},
                        wait=False,
                        timeout_s=300,
                    )
        assert result["status"] == "pending"
        assert "workflow_id" in result

    @pytest.mark.asyncio
    async def test_wait_until_succeeded(self) -> None:
        mock_store_cls = MagicMock()
        mock_store = AsyncMock()
        mock_store.create.return_value = UUID("12345678-1234-5678-1234-567812345678")
        mock_row = MagicMock()
        mock_row.status = MagicMock()
        mock_row.status.value = "succeeded"
        mock_row.snapshot_state = {"exchange_snapshot": {"ok": True}}
        mock_row.finished_at = None
        mock_store.get.return_value = mock_row
        mock_store_cls.return_value = mock_store

        mock_status = MagicMock()
        mock_status.pending = MagicMock(value="pending")
        mock_status.succeeded = MagicMock(value="succeeded")
        mock_status.failed = MagicMock(value="failed")
        mock_status.cancelled = MagicMock(value="cancelled")

        with patch(
            "src.backend.entrypoints.mcp.workflow_tools.get_workflow_state_store_provider",
            return_value=mock_store_cls,
        ):
            with patch(
                "src.backend.entrypoints.mcp.workflow_tools.get_workflow_status_enum_provider",
                return_value=mock_status,
            ):
                with patch(
                    "src.backend.entrypoints.mcp.workflow_tools.action_handler_registry.is_registered",
                    return_value=False,
                ):
                    with patch(
                        "src.backend.entrypoints.mcp.workflow_tools.asyncio.sleep",
                        AsyncMock(),
                    ):
                        result = await _trigger_and_maybe_wait(
                            workflow_name="wf1",
                            route_id="r1",
                            payload={},
                            wait=True,
                            timeout_s=300,
                        )
        assert result["status"] == "succeeded"
        assert result["result"] == {"ok": True}
