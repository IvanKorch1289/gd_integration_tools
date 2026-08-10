"""External-integration processors (CDC only).

D-AUDIT-04 fix (cycle 1): удалены дубликаты MCPToolProcessor и AgentGraphProcessor,
которые shadoowed canonical классы в agent_dsl/mcp_tool.py и agent_dsl/agent_graph.py.

Удалены:
- MCPToolProcessor (был на file:// attack surface — нет protocol validation)
- AgentGraphProcessor (нарушал layer boundary: dsl → services.ai.ai_graph)

Оставлен:
- CDCProcessor (canonical, нет дубля)
"""

from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

__all__ = ("CDCProcessor",)


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
        """Метод process (см. signature)."""
        if not self._subscribed:
            from src.backend.infrastructure.clients.external.cdc import get_cdc_client

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
