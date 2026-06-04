"""Unit tests for tools/cli.py (GAP-DX-1 S35 Typer CLI).

Tests verify the CLI commands are properly structured and call the
expected admin REST API endpoints.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

TOOL_PATH = Path("tools/cli.py")


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    """Run CLI command and return result."""
    return subprocess.run(
        [sys.executable, str(TOOL_PATH), *args],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


# ─── CLI Structure Tests ──────────────────────────────────────────────────────


def test_cli_file_exists() -> None:
    """cli.py exists."""
    assert TOOL_PATH.exists(), f"{TOOL_PATH} not found"


def test_cli_help_command() -> None:
    """CLI responds to --help."""
    result = _run_cli("--help")
    assert result.returncode == 0, f"Help failed: {result.stderr}"
    assert (
        "gd-cli" in result.stdout.lower()
        or "gd_integration_tools" in result.stdout.lower()
    )


def test_cli_route_subcommand_exists() -> None:
    """route subcommand is registered."""
    result = _run_cli("route", "--help")
    assert result.returncode == 0, f"Route help failed: {result.stderr}"
    assert "list" in result.stdout.lower()


def test_cli_workflow_subcommand_exists() -> None:
    """workflow subcommand is registered."""
    result = _run_cli("workflow", "--help")
    assert result.returncode == 0, f"Workflow help failed: {result.stderr}"
    assert "list" in result.stdout.lower()


def test_cli_cache_subcommand_exists() -> None:
    """cache subcommand is registered."""
    result = _run_cli("cache", "--help")
    assert result.returncode == 0, f"Cache help failed: {result.stderr}"
    assert "stats" in result.stdout.lower()


def test_cli_agent_subcommand_exists() -> None:
    """agent subcommand is registered."""
    result = _run_cli("agent", "--help")
    assert result.returncode == 0, f"Agent help failed: {result.stderr}"
    assert "list-tools" in result.stdout.lower()


# ─── Mocked HTTP Tests ────────────────────────────────────────────────────────


def test_cli_route_list_command() -> None:
    """route list calls GET /api/v1/admin/routes."""
    mock_response = {
        "total": 2,
        "routes": [
            {"route_id": "credit_check", "enabled": True, "feature_flag": "ff_credit"},
            {
                "route_id": "order_process",
                "enabled": False,
                "feature_flag": "ff_orders",
            },
        ],
    }

    # Import module first
    import tools.cli

    with patch.object(tools.cli, "_get", return_value=mock_response) as mock_get:
        tools.cli.route_list()
        mock_get.assert_called_once_with("/routes")


def test_cli_cache_stats_command() -> None:
    """cache stats calls GET /api/v1/admin/cache/stats."""
    mock_response = {
        "lru": {"hits": 100, "misses": 20},
        "rag": {"hits": 50, "misses": 5},
        "semantic": {"hits": 10, "misses": 2},
    }

    import tools.cli

    with patch.object(tools.cli, "_get", return_value=mock_response) as mock_get:
        tools.cli.cache_stats()
        mock_get.assert_called_once_with("/cache/stats")


def test_cli_workflow_list_command() -> None:
    """workflow list calls GET /api/v1/admin/workflows."""
    mock_response = [
        {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "workflow_name": "credit_check",
            "status": "pending",
            "created_at": "2026-06-01T10:00:00Z",
        },
        {
            "id": "550e8400-e29b-41d4-a716-446655440001",
            "workflow_name": "order_process",
            "status": "running",
            "created_at": "2026-06-01T10:05:00Z",
        },
    ]

    import tools.cli

    with patch.object(tools.cli, "_get", return_value=mock_response) as mock_get:
        tools.cli.workflow_list()
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert call_args[0][0] == "/workflows"


def test_cli_route_start_command() -> None:
    """route start calls POST /api/v1/admin/routes/toggle with enable=true."""
    import tools.cli

    with patch.object(
        tools.cli, "_post", return_value={"status": "success"}
    ) as mock_post:
        tools.cli.route_start("credit_check")
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "/routes/toggle"
        assert call_args[1]["params"]["route_path"] == "credit_check"
        assert call_args[1]["params"]["enable"] == "true"


def test_cli_cache_flush_command() -> None:
    """cache flush calls DELETE /api/v1/admin/cache/invalidate."""
    import tools.cli

    with patch.object(
        tools.cli, "_delete", return_value={"status": "flushed"}
    ) as mock_delete:
        tools.cli.cache_flush()
        mock_delete.assert_called_once_with("/cache/invalidate")


def test_cli_agent_list_tools_command() -> None:
    """agent list-tools calls GET /api/v1/admin/actions."""
    mock_response = {
        "actions": [
            {
                "name": "get_order",
                "namespace": "orders",
                "description": "Get order by ID",
                "tier": "core",
            }
        ]
    }

    import tools.cli

    with patch.object(tools.cli, "_get", return_value=mock_response) as mock_get:
        tools.cli.agent_list_tools()
        mock_get.assert_called_once_with("/actions")
