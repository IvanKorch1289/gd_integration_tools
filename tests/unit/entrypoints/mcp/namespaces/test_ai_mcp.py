"""Unit tests for AI MCP namespace (ADR-0070)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class FakeMcp:
    """Fake FastMCP that captures registered tools."""

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


class TestRegisterAiTools:
    def test_filters_by_prefix(
        self, fake_mcp: FakeMcp, mock_registry: MagicMock
    ) -> None:
        from src.backend.entrypoints.mcp.namespaces.ai_mcp import register_ai_tools

        mock_registry.list_actions.return_value = [
            "ai.predict",
            "ml.train",
            "rag.query",
            "embed.vectorize",
            "other.action",
        ]
        with patch(
            "src.backend.entrypoints.mcp.namespaces.ai_mcp._register_ai_tool"
        ) as mock_register:
            register_ai_tools(fake_mcp)
        assert mock_register.call_count == 4
        called_names = [call.args[1] for call in mock_register.call_args_list]
        assert "ai.predict" in called_names
        assert "ml.train" in called_names
        assert "rag.query" in called_names
        assert "embed.vectorize" in called_names
        assert "other.action" not in called_names

    def test_empty_list(self, fake_mcp: FakeMcp, mock_registry: MagicMock) -> None:
        from src.backend.entrypoints.mcp.namespaces.ai_mcp import register_ai_tools

        mock_registry.list_actions.return_value = []
        with patch(
            "src.backend.entrypoints.mcp.namespaces.ai_mcp._register_ai_tool"
        ) as mock_register:
            register_ai_tools(fake_mcp)
        assert mock_register.call_count == 0


class TestRegisterAiTool:
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
        from src.backend.entrypoints.mcp.namespaces.ai_mcp import _register_ai_tool

        _register_ai_tool(fake_mcp, "ai.predict")

        assert "ai_predict" in fake_mcp.tools
        mock_registry.dispatch = AsyncMock(return_value={"result": "ok"})
        result = await fake_mcp.tools["ai_predict"](payload='{"key": "value"}')
        assert "ok" in result

    @pytest.mark.asyncio
    @patch(
        "src.backend.entrypoints.mcp.mcp_server._action_input_schema_json",
        return_value=None,
    )
    @patch(
        "src.backend.entrypoints.mcp.mcp_server._check_mcp_tool_authz",
        return_value="not_allowed",
    )
    async def test_auth_denied(
        self, _mock_authz: Any, _mock_schema: Any, fake_mcp: FakeMcp
    ) -> None:
        from src.backend.entrypoints.mcp.namespaces.ai_mcp import _register_ai_tool

        _register_ai_tool(fake_mcp, "ai.predict")

        result = await fake_mcp.tools["ai_predict"]()
        assert "mcp.tool.denied" in result
        assert "not_allowed" in result

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
        from src.backend.entrypoints.mcp.namespaces.ai_mcp import _register_ai_tool

        _register_ai_tool(fake_mcp, "ai.predict")

        mock_registry.dispatch = AsyncMock(return_value={"result": "ok"})
        result = await fake_mcp.tools["ai_predict"](payload="not-json")
        assert "ok" in result
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
        from src.backend.entrypoints.mcp.namespaces.ai_mcp import _register_ai_tool

        _register_ai_tool(fake_mcp, "ai.predict")

        mock_registry.dispatch = AsyncMock(side_effect=RuntimeError("boom"))
        result = await fake_mcp.tools["ai_predict"](payload="{}")
        assert "boom" in result

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
        from src.backend.entrypoints.mcp.namespaces.ai_mcp import _register_ai_tool

        _register_ai_tool(fake_mcp, "ai.predict")

        mock_registry.dispatch = AsyncMock(return_value=None)
        result = await fake_mcp.tools["ai_predict"](payload="{}")
        assert "action_returned_null" in result

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
        from src.backend.entrypoints.mcp.namespaces.ai_mcp import _register_ai_tool

        _register_ai_tool(fake_mcp, "ai.predict")

        class FakeModel:
            def model_dump(self, mode: str = "json") -> dict[str, Any]:
                return {"model": True}

        mock_registry.dispatch = AsyncMock(return_value=FakeModel())
        result = await fake_mcp.tools["ai_predict"](payload="{}")
        assert '"model":true' in result

    @pytest.mark.asyncio
    @patch(
        "src.backend.entrypoints.mcp.mcp_server._action_input_schema_json",
        return_value=None,
    )
    @patch(
        "src.backend.entrypoints.mcp.mcp_server._check_mcp_tool_authz",
        return_value=None,
    )
    async def test_empty_payload(
        self,
        _mock_authz: Any,
        _mock_schema: Any,
        fake_mcp: FakeMcp,
        mock_registry: MagicMock,
    ) -> None:
        from src.backend.entrypoints.mcp.namespaces.ai_mcp import _register_ai_tool

        _register_ai_tool(fake_mcp, "ai.predict")

        mock_registry.dispatch = AsyncMock(return_value={"result": "ok"})
        result = await fake_mcp.tools["ai_predict"](payload="")
        assert "ok" in result
        call_args = mock_registry.dispatch.call_args
        assert call_args[0][0].payload == {}

    @patch(
        "src.backend.entrypoints.mcp.mcp_server._action_input_schema_json",
        return_value={"type": "object"},
    )
    @patch("inspect.signature")
    def test_input_schema_kwarg(
        self, mock_sig: Any, _mock_schema: Any, fake_mcp: FakeMcp
    ) -> None:
        from src.backend.entrypoints.mcp.namespaces.ai_mcp import _register_ai_tool

        sig = MagicMock()
        sig.parameters = {"input_schema": MagicMock()}
        mock_sig.return_value = sig
        fake_mcp.tool = MagicMock(return_value=lambda fn: fn)
        _register_ai_tool(fake_mcp, "ai.predict")

        kwargs = fake_mcp.tool.call_args.kwargs
        assert kwargs["input_schema"] == {"type": "object"}

    @patch(
        "src.backend.entrypoints.mcp.mcp_server._action_input_schema_json",
        return_value={"type": "object"},
    )
    @patch("inspect.signature")
    def test_input_schema_kwarg_camelcase(
        self, mock_sig: Any, _mock_schema: Any, fake_mcp: FakeMcp
    ) -> None:
        from src.backend.entrypoints.mcp.namespaces.ai_mcp import _register_ai_tool

        sig = MagicMock()
        sig.parameters = {"inputSchema": MagicMock()}
        mock_sig.return_value = sig
        fake_mcp.tool = MagicMock(return_value=lambda fn: fn)
        _register_ai_tool(fake_mcp, "ai.predict")

        kwargs = fake_mcp.tool.call_args.kwargs
        assert kwargs["inputSchema"] == {"type": "object"}
