"""Unit tests for Credit MCP namespace (ADR-0070)."""

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


class TestRegisterCreditTools:
    def test_filters_by_prefix(
        self, fake_mcp: FakeMcp, mock_registry: MagicMock
    ) -> None:
        from src.backend.entrypoints.mcp.namespaces.credit_mcp import (
            register_credit_tools,
        )

        mock_registry.list_actions.return_value = [
            "credit.score",
            "credit.apply",
            "other.action",
        ]
        with patch(
            "src.backend.entrypoints.mcp.namespaces.credit_mcp._register_credit_tool"
        ) as mock_register:
            register_credit_tools(fake_mcp)
        assert mock_register.call_count == 2
        called_names = [call.args[1] for call in mock_register.call_args_list]
        assert "credit.score" in called_names
        assert "credit.apply" in called_names
        assert "other.action" not in called_names

    def test_empty_list(self, fake_mcp: FakeMcp, mock_registry: MagicMock) -> None:
        from src.backend.entrypoints.mcp.namespaces.credit_mcp import (
            register_credit_tools,
        )

        mock_registry.list_actions.return_value = []
        with patch(
            "src.backend.entrypoints.mcp.namespaces.credit_mcp._register_credit_tool"
        ) as mock_register:
            register_credit_tools(fake_mcp)
        assert mock_register.call_count == 0


class TestRegisterCreditTool:
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
        from src.backend.entrypoints.mcp.namespaces.credit_mcp import (
            _register_credit_tool,
        )

        _register_credit_tool(fake_mcp, "credit.score")

        assert "credit_score" in fake_mcp.tools
        mock_registry.dispatch = AsyncMock(return_value={"score": 800})
        result = await fake_mcp.tools["credit_score"](payload='{"id": "123"}')
        assert "800" in result
        call_args = mock_registry.dispatch.call_args
        assert call_args[0][0].meta.source == "mcp"

    @pytest.mark.asyncio
    @patch(
        "src.backend.entrypoints.mcp.mcp_server._action_input_schema_json",
        return_value=None,
    )
    @patch(
        "src.backend.entrypoints.mcp.mcp_server._check_mcp_tool_authz",
        return_value="unauthorized",
    )
    async def test_auth_denied(
        self, _mock_authz: Any, _mock_schema: Any, fake_mcp: FakeMcp
    ) -> None:
        from src.backend.entrypoints.mcp.namespaces.credit_mcp import (
            _register_credit_tool,
        )

        _register_credit_tool(fake_mcp, "credit.score")

        result = await fake_mcp.tools["credit_score"]()
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
        from src.backend.entrypoints.mcp.namespaces.credit_mcp import (
            _register_credit_tool,
        )

        _register_credit_tool(fake_mcp, "credit.score")

        mock_registry.dispatch = AsyncMock(return_value={"score": 0})
        result = await fake_mcp.tools["credit_score"](payload="not-json")
        assert "0" in result
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
        from src.backend.entrypoints.mcp.namespaces.credit_mcp import (
            _register_credit_tool,
        )

        _register_credit_tool(fake_mcp, "credit.score")

        mock_registry.dispatch = AsyncMock(side_effect=Exception("err"))
        result = await fake_mcp.tools["credit_score"](payload="{}")
        assert "err" in result

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
        from src.backend.entrypoints.mcp.namespaces.credit_mcp import (
            _register_credit_tool,
        )

        _register_credit_tool(fake_mcp, "credit.score")

        mock_registry.dispatch = AsyncMock(return_value=None)
        result = await fake_mcp.tools["credit_score"](payload="{}")
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
        from src.backend.entrypoints.mcp.namespaces.credit_mcp import (
            _register_credit_tool,
        )

        _register_credit_tool(fake_mcp, "credit.score")

        class FakeModel:
            def model_dump(self, mode: str = "json") -> dict[str, Any]:
                return {"credit": 750}

        mock_registry.dispatch = AsyncMock(return_value=FakeModel())
        result = await fake_mcp.tools["credit_score"](payload="{}")
        assert '"credit":750' in result
