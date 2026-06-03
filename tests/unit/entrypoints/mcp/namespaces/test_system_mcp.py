"""Unit tests for System MCP namespace (ADR-0070)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class FakeMcp:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self, **kwargs: Any) -> Any:
        def decorator(fn: Any) -> Any:
            self.tools[kwargs["name"]] = fn
            return fn

        return decorator


@pytest.fixture
def fake_mcp() -> FakeMcp:
    return FakeMcp()


@pytest.fixture
def mock_registry() -> MagicMock:
    reg = MagicMock()
    reg.dispatch = AsyncMock()
    return reg


@pytest.fixture(autouse=True)
def patch_registry(mock_registry: MagicMock) -> Any:
    with patch(
        "src.backend.dsl.commands.registry.action_handler_registry", mock_registry
    ):
        yield


class TestRegisterSystemTools:
    def test_filters_by_prefix(
        self, fake_mcp: FakeMcp, mock_registry: MagicMock
    ) -> None:
        from src.backend.entrypoints.mcp.namespaces.system_mcp import (
            register_system_tools,
        )

        mock_registry.list_actions.return_value = [
            "system.health",
            "tech.metrics",
            "admin.users",
            "health.check",
            "other.action",
        ]
        with patch(
            "src.backend.entrypoints.mcp.namespaces.system_mcp._register_system_tool"
        ) as mock_register:
            register_system_tools(fake_mcp)
        assert mock_register.call_count == 4
        called_names = [call.args[1] for call in mock_register.call_args_list]
        for name in ("system.health", "tech.metrics", "admin.users", "health.check"):
            assert name in called_names
        assert "other.action" not in called_names

    def test_empty_list(self, fake_mcp: FakeMcp, mock_registry: MagicMock) -> None:
        from src.backend.entrypoints.mcp.namespaces.system_mcp import (
            register_system_tools,
        )

        mock_registry.list_actions.return_value = []
        with patch(
            "src.backend.entrypoints.mcp.namespaces.system_mcp._register_system_tool"
        ) as mock_register:
            register_system_tools(fake_mcp)
        assert mock_register.call_count == 0


class TestRegisterSystemTool:
    @pytest.mark.asyncio
    @patch(
        "src.backend.entrypoints.mcp.mcp_server._action_input_schema_json",
        return_value=None,
    )
    @patch(
        "src.backend.entrypoints.mcp.mcp_server._check_mcp_tool_authz",
        return_value=None,
    )
    async def test_happy_path(
        self,
        _mock_authz: Any,
        _mock_schema: Any,
        fake_mcp: FakeMcp,
        mock_registry: MagicMock,
    ) -> None:
        from src.backend.entrypoints.mcp.namespaces.system_mcp import (
            _register_system_tool,
        )

        _register_system_tool(fake_mcp, "system.health")

        assert "system_health" in fake_mcp.tools
        mock_registry.dispatch = AsyncMock(return_value={"status": "up"})
        result = await fake_mcp.tools["system_health"](payload='{"detail": true}')
        assert "up" in result
        call_args = mock_registry.dispatch.call_args
        assert call_args[0][0].meta.source == "mcp"

    @pytest.mark.asyncio
    @patch(
        "src.backend.entrypoints.mcp.mcp_server._action_input_schema_json",
        return_value=None,
    )
    @patch(
        "src.backend.entrypoints.mcp.mcp_server._check_mcp_tool_authz",
        return_value="forbidden",
    )
    async def test_auth_denied(
        self, _mock_authz: Any, _mock_schema: Any, fake_mcp: FakeMcp
    ) -> None:
        from src.backend.entrypoints.mcp.namespaces.system_mcp import (
            _register_system_tool,
        )

        _register_system_tool(fake_mcp, "system.health")

        result = await fake_mcp.tools["system_health"]()
        assert "mcp.tool.denied" in result

    @pytest.mark.asyncio
    @patch(
        "src.backend.entrypoints.mcp.mcp_server._action_input_schema_json",
        return_value=None,
    )
    @patch(
        "src.backend.entrypoints.mcp.mcp_server._check_mcp_tool_authz",
        return_value=None,
    )
    async def test_invalid_json_payload(
        self,
        _mock_authz: Any,
        _mock_schema: Any,
        fake_mcp: FakeMcp,
        mock_registry: MagicMock,
    ) -> None:
        from src.backend.entrypoints.mcp.namespaces.system_mcp import (
            _register_system_tool,
        )

        _register_system_tool(fake_mcp, "system.health")

        mock_registry.dispatch = AsyncMock(return_value={"status": "up"})
        result = await fake_mcp.tools["system_health"](payload="not-json")
        assert "up" in result
        call_args = mock_registry.dispatch.call_args
        assert call_args[0][0].payload == {"raw": "not-json"}

    @pytest.mark.asyncio
    @patch(
        "src.backend.entrypoints.mcp.mcp_server._action_input_schema_json",
        return_value=None,
    )
    @patch(
        "src.backend.entrypoints.mcp.mcp_server._check_mcp_tool_authz",
        return_value=None,
    )
    async def test_dispatch_raises(
        self,
        _mock_authz: Any,
        _mock_schema: Any,
        fake_mcp: FakeMcp,
        mock_registry: MagicMock,
    ) -> None:
        from src.backend.entrypoints.mcp.namespaces.system_mcp import (
            _register_system_tool,
        )

        _register_system_tool(fake_mcp, "system.health")

        mock_registry.dispatch = AsyncMock(side_effect=RuntimeError("crash"))
        result = await fake_mcp.tools["system_health"](payload="{}")
        assert "crash" in result

    @pytest.mark.asyncio
    @patch(
        "src.backend.entrypoints.mcp.mcp_server._action_input_schema_json",
        return_value=None,
    )
    @patch(
        "src.backend.entrypoints.mcp.mcp_server._check_mcp_tool_authz",
        return_value=None,
    )
    async def test_null_result(
        self,
        _mock_authz: Any,
        _mock_schema: Any,
        fake_mcp: FakeMcp,
        mock_registry: MagicMock,
    ) -> None:
        from src.backend.entrypoints.mcp.namespaces.system_mcp import (
            _register_system_tool,
        )

        _register_system_tool(fake_mcp, "system.health")

        mock_registry.dispatch = AsyncMock(return_value=None)
        result = await fake_mcp.tools["system_health"](payload="{}")
        assert result == "null"

    @pytest.mark.asyncio
    @patch(
        "src.backend.entrypoints.mcp.mcp_server._action_input_schema_json",
        return_value=None,
    )
    @patch(
        "src.backend.entrypoints.mcp.mcp_server._check_mcp_tool_authz",
        return_value=None,
    )
    async def test_result_with_model_dump(
        self,
        _mock_authz: Any,
        _mock_schema: Any,
        fake_mcp: FakeMcp,
        mock_registry: MagicMock,
    ) -> None:
        from src.backend.entrypoints.mcp.namespaces.system_mcp import (
            _register_system_tool,
        )

        _register_system_tool(fake_mcp, "system.health")

        class FakeModel:
            def model_dump(self, mode: str = "json") -> dict[str, Any]:
                return {"healthy": True}

        mock_registry.dispatch = AsyncMock(return_value=FakeModel())
        result = await fake_mcp.tools["system_health"](payload="{}")
        assert '"healthy":true' in result
