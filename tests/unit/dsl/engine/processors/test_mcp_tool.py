"""Unit-тесты для MCPToolProcessor (S27 W3, S28 W5)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.agent_dsl.mcp_tool import MCPToolProcessor


def _make_exchange(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


class TestMCPToolProcessorInit:
    """Тесты инициализации MCPToolProcessor."""

    def test_required_params(self) -> None:
        """tool_uri и tool_name обязательны."""
        with pytest.raises(ValueError, match="tool_uri обязателен"):
            MCPToolProcessor(tool_uri="", tool_name="test_tool")
        with pytest.raises(ValueError, match="tool_name обязателен"):
            MCPToolProcessor(tool_uri="http://localhost:8000", tool_name="")

    def test_default_values(self) -> None:
        """Проверка default значений."""
        proc = MCPToolProcessor(
            tool_uri="http://localhost:8000/mcp",
            tool_name="db.query",
        )
        assert proc.tool_uri == "http://localhost:8000/mcp"
        assert proc.tool_name == "db.query"
        assert proc.arguments_property == "body"
        assert proc.result_property == "mcp_result"
        assert proc.timeout_s == 30.0
        assert proc.name == "mcp_tool:db.query"

    def test_custom_values(self) -> None:
        """Проверка кастомных значений."""
        proc = MCPToolProcessor(
            tool_uri="http://custom:9000/mcp",
            tool_name="custom_tool",
            arguments_property="body.params",
            result_property="custom_result",
            timeout_s=60.0,
            name="my_mcp",
        )
        assert proc.tool_uri == "http://custom:9000/mcp"
        assert proc.tool_name == "custom_tool"
        assert proc.arguments_property == "body.params"
        assert proc.result_property == "custom_result"
        assert proc.timeout_s == 60.0
        assert proc.name == "my_mcp"

    def test_capability_and_audit(self) -> None:
        """Проверка class variables для capability и audit."""
        assert MCPToolProcessor.required_capability == "mcp.call"
        assert MCPToolProcessor.audit_event == "ai.mcp.tool"


class TestMCPToolProcessorExtractArguments:
    """Тесты метода _extract_arguments."""

    def test_body_as_dict(self) -> None:
        """arguments_property=body возвращает тело как есть."""
        proc = MCPToolProcessor(
            tool_uri="http://localhost:8000",
            tool_name="test",
            arguments_property="body",
        )
        exchange = _make_exchange(body={"query": "SELECT 1", "params": [1]})
        result = proc._extract_arguments(exchange)
        assert result == {"query": "SELECT 1", "params": [1]}

    def test_body_not_dict(self) -> None:
        """arguments_property=body с не-dict телом возвращает None."""
        proc = MCPToolProcessor(
            tool_uri="http://localhost:8000",
            tool_name="test",
            arguments_property="body",
        )
        exchange = _make_exchange(body="not a dict")
        result = proc._extract_arguments(exchange)
        assert result is None

    def test_body_field(self) -> None:
        """arguments_property=body.nested извлекает вложенное поле."""
        proc = MCPToolProcessor(
            tool_uri="http://localhost:8000",
            tool_name="test",
            arguments_property="body.query_params",
        )
        exchange = _make_exchange(
            body={"query_params": {"sql": "SELECT 1", "timeout": 30}}
        )
        result = proc._extract_arguments(exchange)
        assert result == {"sql": "SELECT 1", "timeout": 30}

    def test_body_field_not_dict(self) -> None:
        """arguments_property=body.field где field не dict возвращает None."""
        proc = MCPToolProcessor(
            tool_uri="http://localhost:8000",
            tool_name="test",
            arguments_property="body.field",
        )
        exchange = _make_exchange(body={"field": "just a string"})
        result = proc._extract_arguments(exchange)
        assert result is None

    def test_property_reference(self) -> None:
        """arguments_property=property:name извлекает из exchange properties."""
        proc = MCPToolProcessor(
            tool_uri="http://localhost:8000",
            tool_name="test",
            arguments_property="property:my_args",
        )
        exchange = _make_exchange(body={"some": "data"})
        exchange.set_property("my_args", {"key": "value"})
        result = proc._extract_arguments(exchange)
        assert result == {"key": "value"}

    def test_property_not_dict(self) -> None:
        """arguments_property=property:name где property не dict возвращает None."""
        proc = MCPToolProcessor(
            tool_uri="http://localhost:8000",
            tool_name="test",
            arguments_property="property:my_args",
        )
        exchange = _make_exchange(body={})
        exchange.set_property("my_args", "not a dict")
        result = proc._extract_arguments(exchange)
        assert result is None


class TestMCPToolProcessorToSpec:
    """Тесты сериализации to_spec."""

    def test_default_spec(self) -> None:
        """to_spec с default значениями."""
        proc = MCPToolProcessor(
            tool_uri="http://localhost:8000/mcp",
            tool_name="db.query",
        )
        spec = proc.to_spec()
        assert spec == {
            "mcp_tool": {
                "tool_uri": "http://localhost:8000/mcp",
                "tool_name": "db.query",
            }
        }

    def test_custom_spec(self) -> None:
        """to_spec с кастомными значениями."""
        proc = MCPToolProcessor(
            tool_uri="http://custom:9000/mcp",
            tool_name="custom_tool",
            arguments_property="body.params",
            result_property="custom_result",
            timeout_s=120.0,
        )
        spec = proc.to_spec()
        assert spec == {
            "mcp_tool": {
                "tool_uri": "http://custom:9000/mcp",
                "tool_name": "custom_tool",
                "arguments_property": "body.params",
                "result_property": "custom_result",
                "timeout_s": 120.0,
            }
        }


class TestMCPToolProcessorRun:
    """Тесты асинхронного выполнения _run."""

    @pytest.mark.asyncio
    async def test_run_with_invalid_arguments(self) -> None:
        """При невалидных arguments - exchange.fail()."""
        proc = MCPToolProcessor(
            tool_uri="http://localhost:8000",
            tool_name="test",
            arguments_property="body.params",
        )
        exchange = _make_exchange(body="not a dict")
        context = MagicMock()

        await proc._run(exchange, context)

        assert exchange.error is not None
        assert "arguments" in exchange.error
        assert "не найдены" in exchange.error

    @pytest.mark.asyncio
    @patch("src.backend.dsl.engine.processors.agent_dsl.mcp_tool.Client")
    async def test_run_success(self, mock_client_class: MagicMock) -> None:
        """Успешный вызов MCP tool."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.call_tool = AsyncMock(return_value={"rows": [1, 2, 3]})
        mock_client_class.return_value = mock_client

        proc = MCPToolProcessor(
            tool_uri="http://localhost:8000/mcp",
            tool_name="db.query",
        )
        exchange = _make_exchange(body={"sql": "SELECT 1"})
        context = MagicMock()

        await proc._run(exchange, context)

        assert exchange.get_property("mcp_result") == {"rows": [1, 2, 3]}
        mock_client.call_tool.assert_called_once_with(
            "db.query", arguments={"sql": "SELECT 1"}
        )

    @pytest.mark.asyncio
    @patch("src.backend.dsl.engine.processors.agent_dsl.mcp_tool.Client")
    async def test_run_mcp_error(self, mock_client_class: MagicMock) -> None:
        """Ошибка MCP call - exchange.fail()."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.call_tool = AsyncMock(
            side_effect=ConnectionError("MCP server unreachable")
        )
        mock_client_class.return_value = mock_client

        proc = MCPToolProcessor(
            tool_uri="http://localhost:8000/mcp",
            tool_name="db.query",
        )
        exchange = _make_exchange(body={"sql": "SELECT 1"})
        context = MagicMock()

        await proc._run(exchange, context)

        assert exchange.error is not None
        assert "MCP call failed" in exchange.error


class TestMCPToolProcessorCapabilityScope:
    """Тесты capability scope."""

    def test_capability_scope_returns_tool_name(self) -> None:
        """Scope для mcp.call = tool_name."""
        proc = MCPToolProcessor(
            tool_uri="http://localhost:8000",
            tool_name="database.query",
        )
        exchange = _make_exchange(body={})
        scope = proc._capability_scope(exchange)
        assert scope == "database.query"