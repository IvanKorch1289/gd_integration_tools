# ruff: noqa: S101
"""Smoke tests for MCP server (entrypoints/mcp/mcp_server.py)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from src.backend.entrypoints.mcp.mcp_server import (
    _action_input_schema_json,
    _check_mcp_tool_authz,
)

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


# === Unit tests (Wave 41 coverage push) ===


# ── _check_mcp_tool_authz: dispatch policy for MCP tool calls ─────────


@pytest.mark.unit
def test_check_mcp_tool_authz_disabled_allows_all() -> None:
    """When tool_authz_enabled=False → passthrough (None, no deny)."""
    fake_settings = MagicMock()
    fake_settings.tool_authz_enabled = False
    fake_settings.tool_allowlist = []
    fake_settings.tool_public_namespaces = []
    with patch(
        "src.backend.core.config.ai_2026.mcp_settings", fake_settings, create=True
    ):
        result = _check_mcp_tool_authz("any.random.action")
    assert result is None


@pytest.mark.unit
def test_check_mcp_tool_authz_allowlist_passes() -> None:
    """Action in tool_allowlist is permitted (None) when authz enabled."""
    fake_settings = MagicMock()
    fake_settings.tool_authz_enabled = True
    fake_settings.tool_allowlist = ["orders.get"]
    fake_settings.tool_public_namespaces = []
    with patch(
        "src.backend.core.config.ai_2026.mcp_settings", fake_settings, create=True
    ):
        result = _check_mcp_tool_authz("orders.get")
    assert result is None


@pytest.mark.unit
def test_check_mcp_tool_authz_denies_unknown_action() -> None:
    """Unknown action (not in allowlist, no public namespace) → deny reason."""
    fake_settings = MagicMock()
    fake_settings.tool_authz_enabled = True
    fake_settings.tool_allowlist = []
    fake_settings.tool_public_namespaces = []
    with patch(
        "src.backend.core.config.ai_2026.mcp_settings", fake_settings, create=True
    ):
        result = _check_mcp_tool_authz("forbidden.deep.action")
    # Any non-None string means denied; the specific reason varies by
    # capability-check path, so just check it's a denial string.
    assert isinstance(result, str)
    assert len(result) > 0


# ── Property test: _action_input_schema_json — unknown action → None ────


@given(action_name=st.text(min_size=1, max_size=80))
@hyp_settings(max_examples=50)
@pytest.mark.unit
def test_action_input_schema_json_unknown_action_returns_none_property(
    action_name: str,
) -> None:
    """For any random action_name, when registry.get_metadata → None,
    _action_input_schema_json must return None (no exception, no schema)."""
    mock_registry = MagicMock()
    mock_registry.get_metadata.return_value = None
    with patch(
        "src.backend.dsl.commands.registry.action_handler_registry", mock_registry
    ):
        result = _action_input_schema_json(action_name)
    assert result is None
