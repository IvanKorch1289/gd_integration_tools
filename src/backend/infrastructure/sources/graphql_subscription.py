"""K3 W5 — :class:`GraphQLSubscriptionSource` — источник данных GraphQL subscriptions.

Подключается к GraphQL endpoint по WebSocket (``graphql-ws`` протокол) и эмитит
каждое событие подписки как :class:`GraphQLEvent`. Использует библиотеку
``gql`` с ``gql.transport.websockets`` (lazy-import — не блокирует старт при
отсутствии зависимости).

Активируется через feature_flag ``graphql_subscription_source`` (default-OFF).

Пример::

    source = GraphQLSubscriptionSource(
        endpoint_url="wss://api.example.com/graphql",
        subscription_query=\"\"\"
            subscription { orderUpdated { id status } }
        \"\"\",
    )
    async for event in source.stream():
        print(event.data, event.timestamp)
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.backend.infrastructure.clients.base_connector import HealthResult
from src.backend.core.security.connector_auth import check_source_capability

if TYPE_CHECKING:
    pass

__all__ = ("GraphQLEvent", "GraphQLSubscriptionSource")


@dataclass
class GraphQLEvent:
    """Событие из GraphQL subscription.

    Args:
        data: Данные события (словарь из ``data``-поля ответа).
        subscription_id: Уникальный идентификатор подписки (UUID).
        timestamp: Unix-время получения события (float, секунды).
    """

    data: dict
    subscription_id: str
    timestamp: float = field(default_factory=time.time)


class GraphQLSubscriptionSource:
    """Источник событий на базе GraphQL WebSocket-подписок.

    Использует ``gql`` + ``gql.transport.websockets.WebsocketsTransport``
    (протокол ``graphql-ws``). Метод :meth:`stream` — async-генератор:
    корректно завершается при ``asyncio.CancelledError``.

    Библиотека ``gql`` импортируется лениво — отсутствие в окружении
    не блокирует загрузку остальных модулей.

    Args:
        endpoint_url: URL WebSocket endpoint GraphQL-сервера
            (``wss://`` или ``ws://``).
        subscription_query: Строка GraphQL-запроса подписки.
        headers: Дополнительные HTTP-заголовки для WebSocket handshake
            (например, ``Authorization``).

    Example::

        source = GraphQLSubscriptionSource(
            endpoint_url="wss://api.example.com/graphql",
            subscription_query=\"\"\"
                subscription Orders {
                    orderUpdated { id status amount }
                }
            \"\"\",
            headers={"Authorization": "Bearer <token>"},
        )
        async for event in source.stream():
            process(event.data)
    """

    def __init__(
        self, endpoint_url: str, subscription_query: str, headers: dict | None = None
    ) -> None:
        self._endpoint_url = endpoint_url
        self._subscription_query = subscription_query
        self._headers = headers or {}
        self._subscription_id: str = str(uuid.uuid4())

    async def health(self, mode: str = "fast") -> HealthResult:
        """Stateless stream source — всегда ok, если модуль импортируется."""
        return HealthResult.ok(latency_ms=0.0, mode=mode, kind="graphql")

    async def stream(self) -> AsyncIterator[GraphQLEvent]:
        """Async-генератор событий из GraphQL subscription.

        Выполняет WebSocket-соединение с GraphQL endpoint и выдаёт
        :class:`GraphQLEvent` на каждое входящее сообщение подписки.
        При разрыве соединения пробрасывает исключение наружу.

        Yields:
            Событие :class:`GraphQLEvent` с данными из ``data``-поля ответа.

        Raises:
            RuntimeError: Если ``gql`` или ``gql.transport.websockets``
                не установлены в окружении.
            PermissionError: Если ``graphql.read`` capability denied.
            Exception: Сетевые ошибки пробрасываются без подавления.
        """
        try:
            import gql
            from gql.transport.websockets import WebsocketsTransport
        except ImportError as exc:
            raise RuntimeError(
                "gql не установлен; добавь 'gql[websockets]' в pyproject.toml."
            ) from exc

        # S172 (Wave S2): capability check на старте stream-сессии.
        if not await check_source_capability(
            "graphql.read",
            action="read",
            principal="anonymous",
            extra_ctx={
                "endpoint_url": self._endpoint_url,
                "subscription_id": self._subscription_id,
            },
        ):
            raise PermissionError(
                f"graphql.read denied for endpoint={self._endpoint_url!r}"
            )

        transport = WebsocketsTransport(url=self._endpoint_url, headers=self._headers)
        async with gql.Client(transport=transport) as session:
            query = gql.gql(self._subscription_query)
            async for result in session.subscribe(query):
                data: dict = result if isinstance(result, dict) else dict(result)
                yield GraphQLEvent(data=data, subscription_id=self._subscription_id)
