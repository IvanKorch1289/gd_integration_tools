from typing import Any

from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange
from app.dsl.engine.processors.base import BaseProcessor, handle_processor_error

__all__ = ("MCPToolProcessor", "AgentGraphProcessor", "CDCProcessor")


class MCPToolProcessor(BaseProcessor):
    """Вызывает внешний MCP tool из DSL pipeline."""

    def __init__(self, tool_uri: str, tool_name: str, *, result_property: str = "mcp_result", name: str | None = None) -> None:
        super().__init__(name=name or f"mcp_tool:{tool_name}")
        self.tool_uri = tool_uri
        self.tool_name = tool_name
        self.result_property = result_property

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from fastmcp import Client
        async with Client(self.tool_uri) as client:
            result = await client.call_tool(self.tool_name, arguments=exchange.in_message.body if isinstance(exchange.in_message.body, dict) else {})
            exchange.set_property(self.result_property, result)
            exchange.set_out(body=result, headers=dict(exchange.in_message.headers))


class AgentGraphProcessor(BaseProcessor):
    """Запускает LangGraph-агента внутри DSL pipeline."""

    def __init__(self, graph_name: str, tools: list[str], *, name: str | None = None) -> None:
        super().__init__(name=name or f"agent_graph:{graph_name}")
        self.graph_name = graph_name
        self.tools = tools

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from app.services.ai_graph import build_and_run_agent
        body = exchange.in_message.body
        prompt = body if isinstance(body, str) else str(body)
        result = await build_and_run_agent(prompt=prompt, tool_actions=self.tools)
        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))


class CDCProcessor(BaseProcessor):
    """Реагирует на CDC-события и маршрутизирует через DSL.

    Поддерживает 3 стратегии: polling (любая БД), listen_notify (PostgreSQL),
    logminer (Oracle). Параметры:
    - profile: имя профиля внешней БД
    - tables: список отслеживаемых таблиц
    - target_action: action для диспетчеризации событий
    - strategy: "polling" | "listen_notify" | "logminer"
    - interval: интервал опроса для polling (сек)
    - timestamp_column: столбец для polling (default: updated_at)
    - batch_size: макс. событий за итерацию
    - channel: LISTEN-канал для listen_notify
    """

    def __init__(
        self,
        profile: str,
        tables: list[str],
        target_action: str,
        *,
        strategy: str = "polling",
        interval: float = 5.0,
        timestamp_column: str = "updated_at",
        batch_size: int = 100,
        channel: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"cdc:{profile}:{strategy}")
        self.profile = profile
        self.tables = tables
        self.target_action = target_action
        self.strategy = strategy
        self.interval = interval
        self.timestamp_column = timestamp_column
        self.batch_size = batch_size
        self.channel = channel
        self._subscribed = False

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        if not self._subscribed:
            from app.infrastructure.clients.cdc import get_cdc_client
            client = get_cdc_client()
            sub_id = await client.subscribe(
                profile=self.profile,
                tables=self.tables,
                target_action=self.target_action,
                strategy=self.strategy,
                interval=self.interval,
                timestamp_column=self.timestamp_column,
                batch_size=self.batch_size,
                channel=self.channel,
            )
            self._subscribed = True
            exchange.set_property("cdc_subscription_id", sub_id)
        exchange.set_out(
            body={
                "status": "cdc_active",
                "profile": self.profile,
                "tables": self.tables,
                "strategy": self.strategy,
            },
            headers=dict(exchange.in_message.headers),
        )
