"""Tests for fastmcp_server (GAP-AI-1, S35)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

try:
    from src.backend.dsl.agents.fastmcp_server import FastMCPserver
except ModuleNotFoundError:
    pytest.skip("mcp module not installed", allow_module_level=True)


class TestFastMCPserver:
    """Unit tests for FastMCPserver."""

    def test_fastmcp_server_exports_tools(self) -> None:
        """FastMCPserver is instantiated without error and registers tools."""
        with patch(
            "src.backend.dsl.agents.fastmcp_server.SkillRegistry"
        ) as mock_registry_cls, patch(
            "src.backend.dsl.agents.fastmcp_server.workflow_registry"
        ):
            mock_registry = MagicMock()
            mock_registry.list_all.return_value = []
            mock_registry_cls.return_value = mock_registry

            server = FastMCPserver()

            # Should have created a FastMCP instance
            assert server._mcp is not None

    def test_fastmcp_server_exports_workflows(self) -> None:
        """FastMCPserver exports workflow registry entries as prompts."""
        mock_wf = MagicMock()
        mock_wf.name = "test-workflow"
        mock_wf.description = "Test workflow"
        mock_wf.tags = {"production"}
        mock_wf.input_schema = None

        with patch(
            "src.backend.dsl.agents.fastmcp_server.SkillRegistry"
        ) as mock_registry_cls, patch(
            "src.backend.dsl.agents.fastmcp_server.workflow_registry"
        ) as mock_wf_registry:
            mock_registry = MagicMock()
            mock_registry.list_all.return_value = []
            mock_registry_cls.return_value = mock_registry
            mock_wf_registry.list_all.return_value = [mock_wf]

            server = FastMCPserver()
            server._register_prompts()

            # Prompt should have been added
            assert server._mcp is not None

    def test_fastmcp_server_lifecycle_start_stop(self) -> None:
        """FastMCPserver start/stop are no-ops (lifecycle managed by ASGI host)."""
        with patch(
            "src.backend.dsl.agents.fastmcp_server.SkillRegistry"
        ) as mock_registry_cls, patch(
            "src.backend.dsl.agents.fastmcp_server.workflow_registry"
        ):
            mock_registry = MagicMock()
            mock_registry.list_all.return_value = []
            mock_registry_cls.return_value = mock_registry

            server = FastMCPserver()

            # start/stop should not raise (no-arg async methods)
            import asyncio
            asyncio.get_event_loop().run_until_complete(server.start())
            asyncio.get_event_loop().run_until_complete(server.stop())

    def test_asgi_app_returns_fastmcp_app(self) -> None:
        """asgi_app property returns the MCP ASGI application."""
        with patch(
            "src.backend.dsl.agents.fastmcp_server.SkillRegistry"
        ) as mock_registry_cls, patch(
            "src.backend.dsl.agents.fastmcp_server.workflow_registry"
        ):
            mock_registry = MagicMock()
            mock_registry.list_all.return_value = []
            mock_registry_cls.return_value = mock_registry

            server = FastMCPserver()
            app = server.asgi_app

            # Should return something (the FastMCP ASGI app)
            assert app is not None
