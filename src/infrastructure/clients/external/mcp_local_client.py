"""MCP Local Client — подключение к MCP-серверам во внутреннем контуре."""

from __future__ import annotations

import logging
from typing import Any

__all__ = ("LocalMCPClient",)

logger = logging.getLogger(__name__)


class LocalMCPClient:
    """Клиент для MCP-серверов, запущенных локально (stdio, SSE)."""

    def __init__(self) -> None:
        self._session: Any = None
        self._transport: Any = None

    async def connect_stdio(self, command: list[str]) -> None:
        """Подключение через stdio (subprocess)."""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(command=command[0], args=command[1:])
        self._transport = stdio_client(server_params)
        read, write = await self._transport.__aenter__()
        self._session = ClientSession(read, write)
        await self._session.__aenter__()
        await self._session.initialize()
        logger.info("MCP stdio connected: %s", " ".join(command))

    async def connect_sse(self, url: str) -> None:
        """Подключение через SSE (HTTP, внутренняя сеть)."""
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        self._transport = sse_client(url)
        read, write = await self._transport.__aenter__()
        self._session = ClientSession(read, write)
        await self._session.__aenter__()
        await self._session.initialize()
        logger.info("MCP SSE connected: %s", url)

    async def close(self) -> None:
        """Закрывает соединение."""
        if self._session:
            await self._session.__aexit__(None, None, None)
            self._session = None
        if self._transport:
            await self._transport.__aexit__(None, None, None)
            self._transport = None

    async def list_tools(self) -> list[dict[str, Any]]:
        """Получает список tools от MCP-сервера."""
        if not self._session:
            raise RuntimeError("MCP client not connected")

        result = await self._session.list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.inputSchema,
            }
            for tool in result.tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Вызывает tool на MCP-сервере."""
        if not self._session:
            raise RuntimeError("MCP client not connected")

        result = await self._session.call_tool(name, arguments or {})
        return result

    async def list_resources(self) -> list[dict[str, Any]]:
        """Получает список ресурсов."""
        if not self._session:
            raise RuntimeError("MCP client not connected")

        result = await self._session.list_resources()
        return [
            {
                "uri": str(r.uri),
                "name": r.name,
                "description": getattr(r, "description", None),
                "mimeType": getattr(r, "mimeType", None),
            }
            for r in result.resources
        ]

    async def read_resource(self, uri: str) -> Any:
        """Читает ресурс по URI."""
        if not self._session:
            raise RuntimeError("MCP client not connected")
        return await self._session.read_resource(uri)
