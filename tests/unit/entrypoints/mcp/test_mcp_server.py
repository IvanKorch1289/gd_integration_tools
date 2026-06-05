# ruff: noqa: S101
"""Smoke tests for MCP server (entrypoints/mcp/mcp_server.py)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.backend.entrypoints.mcp.mcp_server import _action_input_schema_json

# ── _action_input_schema_json ───────────────────────────────────────


def test_action_input_schema_json_returns_none_for_unknown_action() -> None:
    """For an action not in registry, returns None."""
    mock_registry = MagicMock()
    mock_registry.get_metadata.return_value = None
    with patch(
        "src.backend.dsl.commands.registry.action_handler_registry", mock_registry
    ):
        result = _action_input_schema_json("nonexistent_action_xyz")
    assert result is None


def test_action_input_schema_json_handles_exception() -> None:
    """If introspection fails, returns None (no exception raised)."""
    mock_registry = MagicMock()
    mock_metadata = MagicMock()
    mock_metadata.input_model = MagicMock()
    mock_metadata.input_model.model_json_schema.side_effect = RuntimeError("boom")
    mock_registry.get_metadata.return_value = mock_metadata
    with patch(
        "src.backend.dsl.commands.registry.action_handler_registry", mock_registry
    ):
        result = _action_input_schema_json("some_action")
    assert result is None


# ── Module-level exports ────────────────────────────────────────────


def test_module_exports_create_and_register() -> None:
    import importlib

    import src.backend.entrypoints.mcp.mcp_server as mcp_server

    # Re-import with sys.path verification
    mcp_mod = importlib.import_module("src.backend.entrypoints.mcp.mcp_server")
    assert hasattr(mcp_mod, "create_mcp_server")
    assert hasattr(mcp_mod, "register_mcp_tools")
    assert mcp_server is mcp_mod


def test_module_logger_exists() -> None:
    import src.backend.entrypoints.mcp.mcp_server as mcp_server

    assert mcp_server.logger is not None


# ── create_mcp_server: skip complex setup, mark as xfail ────────────


@pytest.mark.xfail(
    reason="create_mcp_server requires full FastMCP runtime + all sub-registrars; covered by integration tests",
    strict=False,
)
def test_create_mcp_server() -> None:
    from src.backend.entrypoints.mcp import mcp_server

    server = mcp_server.create_mcp_server()
    assert server is not None
