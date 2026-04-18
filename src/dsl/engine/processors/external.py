from typing import Any

from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange, ExchangeStatus
from app.dsl.engine.processors.base import BaseProcessor

__all__ = ("MCPToolProcessor", "AgentGraphProcessor", "CDCProcessor")


class MCPToolProcessor(BaseProcessor):
    """Вызывает внешний MCP tool из DSL pipeline."""

    def __init__(self, tool_uri: str, tool_name: str, *, result_property: str = "mcp_result", name: str | None = None) -> None:
        super().__init__(name=name or f"mcp_tool:{tool_name}")
        self.tool_uri = tool_uri
        self.tool_name = tool_name
        self.result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        payload = body if isinstance(body, dict) else {}
        try:
            from fastmcp import Client
            async with Client(self.tool_uri) as client:
                result = await client.call_tool(self.tool_name, arguments=payload)
                exchange.set_property(self.result_property, result)
                exchange.set_out(body=result, headers=dict(exchange.in_message.headers))
        except ImportError:
            exchange.set_error("fastmcp не установлен")
            exchange.stop()
        except Exception as exc:
            exchange.set_error(f"MCP tool error: {exc}")
            exchange.stop()


class AgentGraphProcessor(BaseProcessor):
    """Запускает LangGraph-агента внутри DSL pipeline."""

    def __init__(self, graph_name: str, tools: list[str], *, name: str | None = None) -> None:
        super().__init__(name=name or f"agent_graph:{graph_name}")
        self.graph_name = graph_name
        self.tools = tools

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        prompt = body if isinstance(body, str) else str(body)
        try:
            from app.services.ai_graph import build_and_run_agent
            result = await build_and_run_agent(prompt=prompt, tool_actions=self.tools)
            exchange.set_out(body=result, headers=dict(exchange.in_message.headers))
        except ImportError:
            exchange.set_error("langgraph не установлен")
            exchange.stop()
        except Exception as exc:
            exchange.set_error(f"Agent graph error: {exc}")
            exchange.stop()


class CDCProcessor(BaseProcessor):
    """Реагирует на CDC-события и маршрутизирует через DSL."""

    def __init__(self, profile: str, tables: list[str], target_action: str, *, name: str | None = None) -> None:
        super().__init__(name=name or f"cdc:{profile}")
        self.profile = profile
        self.tables = tables
        self.target_action = target_action
        self._subscribed = False

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        if not self._subscribed:
            from app.infrastructure.clients.cdc import get_cdc_client
            client = get_cdc_client()
            sub_id = await client.subscribe(profile=self.profile, tables=self.tables, target_action=self.target_action)
            self._subscribed = True
            exchange.set_property("cdc_subscription_id", sub_id)
        exchange.set_out(
            body={"status": "cdc_active", "profile": self.profile, "tables": self.tables},
            headers=dict(exchange.in_message.headers),
        )
