"""MCPToolProcessor — DSL-вызов MCP tool через FastMCP (S27 W3, S28 W5).

Декларативный вызов внешнего MCP tool из DSL pipeline. Использует
:class:`fastmcp.Client` для соединения с MCP-сервером по ``tool_uri``.

YAML контракт::

    steps:
      - mcp_tool:
          tool_uri: http://localhost:8000/mcp
          tool_name: database.query
          arguments_property: body.query_params
          result_property: mcp_result

Python контракт::

    builder.mcp_tool(
        tool_uri="http://localhost:8000/mcp",
        tool_name="database.query",
        arguments_property="body.query_params",
        result_property="mcp_result",
    )

Capability ``mcp.call`` обязательна.

При недоступности MCP-сервера (connection error, timeout) —
``exchange.fail()`` с описанием ошибки.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.agent_dsl._base import BaseAIProcessor

Client: Any = None
try:
    from fastmcp import Client
except ImportError:
    pass

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("MCPToolProcessor",)

_logger = get_logger(__name__)


class MCPToolProcessor(BaseAIProcessor):
    """Вызов MCP tool через FastMCP Client.

    Args:
        tool_uri: URI MCP-сервера (``http://host:port/mcp`` или
            ``file:///path/to/server.py``).
        tool_name: Имя вызываемого tool'а в MCP-сервере.
        arguments_property: Опц. путь к аргументам вызова
            (``body`` / ``body.<key>`` / ``property:<name>``).
            Default ``body`` — все тело сообщения как dict.
        result_property: Свойство exchange для записи результата.
            Default ``mcp_result``.
        timeout_s: Timeout на вызов в секундах. Default ``30``.
        name: Имя процессора.
    """

    required_capability: ClassVar[str | None] = "mcp.call"
    audit_event: ClassVar[str | None] = "ai.mcp.tool"

    def __init__(
        self,
        *,
        tool_uri: str,
        tool_name: str,
        arguments_property: str = "body",
        result_property: str = "mcp_result",
        timeout_s: float = 30.0,
        name: str | None = None,
    ) -> None:
        if not tool_uri:
            raise ValueError("MCPToolProcessor: tool_uri обязателен")
        if not tool_name:
            raise ValueError("MCPToolProcessor: tool_name обязателен")
        super().__init__(name=name or f"mcp_tool:{tool_name}")
        self.tool_uri = tool_uri
        self.tool_name = tool_name
        self.arguments_property = arguments_property
        self.result_property = result_property
        self.timeout_s = timeout_s
        self._client: Any = None
        self._client_connected: bool = False

    def _capability_scope(self, exchange: Exchange[Any]) -> str | None:
        """Scope для ``mcp.call`` = tool_name ( resource-level )."""
        del exchange
        return self.tool_name

    async def _run(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        _ = context  # Зарезервировано для майбутнього use (correlation, tenant_id)

        arguments = self._extract_arguments(exchange)
        if arguments is None:
            exchange.fail(
                f"{self.name}: arguments из '{self.arguments_property}' "
                f"не найдены или не являются dict"
            )
            return

        try:
            result = await self._call_mcp_tool(arguments)
        except Exception as exc:
            exchange.fail(f"{self.name}: MCP call failed: {exc}")
            return

        exchange.set_property(self.result_property, result)
        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))

    def _extract_arguments(self, exchange: Exchange[Any]) -> dict[str, Any] | None:
        """Достать arguments для tool call через dot-path.

        Returns:
            dict с аргументами или None если path невалиден.
        """
        path = self.arguments_property
        if path == "body":
            body = exchange.in_message.body
            return body if isinstance(body, dict) else None
        if path.startswith("body."):
            key = path[len("body.") :]
            body = exchange.in_message.body
            if not isinstance(body, dict):
                return None
            cursor: Any = body
            for part in key.split("."):
                if not isinstance(cursor, dict):
                    return None
                cursor = cursor.get(part)
            return cursor if isinstance(cursor, dict) else None
        if path.startswith("property:"):
            key = path[len("property:") :]
            value = exchange.get_property(key)
            return value if isinstance(value, dict) else None
        return None

    def _get_client(self) -> Any:
        """Lazy-инициализация FastMCP Client с connection pooling."""
        if self._client is None:
            self._client = Client(self.tool_uri, timeout=self.timeout_s)
        return self._client

    async def _ensure_connected(self) -> Any:
        """Убедиться, что Client подключён (ленивое подключение)."""
        client = self._get_client()
        if not self._client_connected:
            await client.__aenter__()
            self._client_connected = True
        return client

    async def _call_mcp_tool(self, arguments: dict[str, Any]) -> Any:
        """Выполняет actual MCP tool call через FastMCP Client."""
        if Client is None:
            raise ImportError("fastmcp not installed: pip install fastmcp")

        client = await self._ensure_connected()
        return await client.call_tool(
            self.tool_name, arguments=arguments, timeout=self.timeout_s
        )

    async def close(self) -> None:
        """Закрыть соединение с MCP-сервером (cleanup)."""
        if self._client is not None and self._client_connected:
            await self._client.close()
            self._client_connected = False

    def to_spec(self) -> dict[str, Any]:
        """Round-trip сериализация для YAML."""
        spec: dict[str, Any] = {"tool_uri": self.tool_uri, "tool_name": self.tool_name}
        if self.arguments_property != "body":
            spec["arguments_property"] = self.arguments_property
        if self.result_property != "mcp_result":
            spec["result_property"] = self.result_property
        if self.timeout_s != 30.0:
            spec["timeout_s"] = self.timeout_s
        return {"mcp_tool": spec}
