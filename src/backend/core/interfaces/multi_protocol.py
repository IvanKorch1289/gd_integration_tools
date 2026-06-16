"""Протоколы для entrypoints/* — Wave 6.5b.

Этот файл аналогичен ``integrations.py`` (W6.4), но описывает контракты,
требуемые в ``entrypoints/{cdc,email,express,graphql,grpc,mcp,scheduler,
stream,streamlit,webhook,websocket}/*``.

Реализации остаются в ``infrastructure/...``; entrypoints получают
объекты через ленивые провайдеры из ``core/di/providers.py``.

Все Protocol помечены ``@runtime_checkable``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

__all__ = (
    "CDCClientProtocol",
    "ExpressBotClientProtocol",
    "ExpressMetricsRecorderProtocol",
    "HealthCheckServiceProtocol",
    "LoggerProtocol",
    "MongoExpressDialogStoreProtocol",
    "MongoExpressSessionStoreProtocol",
    "RateLimiterProtocol",  # S159 W2: added (test import contract)
    "RedisSetProtocol",
    "SLOTrackerProtocol",
    "StreamClientProtocol",
    "VaultRefresherProtocol",
)


@runtime_checkable
class RedisHashProtocol(Protocol):
    """Контракт shared HASH-структуры (multi-instance webhook subs etc.)."""

    async def set(self, field: str, value: Any) -> None:
        """Выполнить операцию set."""
        ...

    async def get(self, field: str) -> Any:
        """Выполнить операцию get."""
        ...

    async def delete(self, field: str) -> bool:
        """Выполнить операцию delete."""
        ...

    async def all(self) -> dict[str, Any]:
        """Выполнить операцию all."""
        ...


@runtime_checkable
class RedisSetProtocol(Protocol):
    """Контракт shared SET-структуры (group membership)."""

    async def add(self, *members: str) -> int:
        """Выполнить операцию add."""
        ...

    async def remove(self, *members: str) -> int:
        """Выполнить операцию remove."""
        ...

    async def members(self) -> set[str]:
        """Выполнить операцию members."""
        ...

    async def contains(self, member: str) -> bool:
        """Выполнить операцию contains."""
        ...


@runtime_checkable
class RedisCursorProtocol(Protocol):
    """Контракт CAS-cursor (CDC last_check etc.)."""

    async def get(self) -> Any:
        """Выполнить операцию get."""
        ...

    async def set(self, value: Any) -> bool:
        """Выполнить операцию set."""
        ...


@runtime_checkable
class RedisPubSubProtocol(Protocol):
    """Контракт cross-instance pub/sub (WS broadcast, cache invalidation)."""

    async def publish(self, message: Any) -> int:
        """Выполнить операцию publish."""
        ...

    def subscribe(self) -> AsyncIterator[Any]:
        """Выполнить операцию subscribe."""
        ...


@runtime_checkable
class CDCClientProtocol(Protocol):
    """Контракт CDC-клиента для управления подписками на изменения внешних БД.

    Реализация: ``infrastructure.clients.external.cdc.CDCClient``.
    """

    async def subscribe(
        self, *, profile: str, tables: list[str], target_action: str | None = None
    ) -> str:
        """Выполнить операцию subscribe."""
        ...

    async def unsubscribe(self, subscription_id: str) -> bool:
        """Выполнить операцию unsubscribe."""
        ...

    def list_subscriptions(self) -> list[dict[str, Any]]:
        """Получить список subscriptions."""
        ...


@runtime_checkable
class VaultRefresherProtocol(Protocol):
    """Контракт получения секретов из Vault (по ссылке вида ``vault:<path>#<key>``).

    Реализация: ``infrastructure.application.vault_refresher.VaultSecretRefresher``.
    """

    async def resolve(self, ref: str) -> str:
        """Выполнить операцию resolve."""
        ...


@runtime_checkable
class LoggerProtocol(Protocol):
    """Минимальная поверхность structured-логгера.

    Реализация: разные ``logger`` из
    ``infrastructure.external_apis.logging_service``
    (``app_logger``, ``stream_logger``, ``grpc_logger`` и т.д.).
    """

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Выполнить операцию info."""
        ...

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Выполнить операцию warning."""
        ...

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Выполнить операцию error."""
        ...

    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Выполнить операцию critical."""
        ...

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Выполнить операцию exception."""
        ...


@runtime_checkable
class MongoExpressDialogStoreProtocol(Protocol):
    """Контракт Mongo-стора Express-диалогов.

    Реализация: ``infrastructure.repositories.express_dialogs_mongo
    .MongoExpressDialogStore``.
    """

    async def append_message(
        self,
        *,
        session_id: str,
        role: str,
        body: str,
        bot_id: str | None = None,
        group_chat_id: str | None = None,
        user_huid: str | None = None,
        sync_id: str | None = None,
    ) -> None:
        """Выполнить операцию append message."""
        ...


@runtime_checkable
class MongoExpressSessionStoreProtocol(Protocol):
    """Контракт Mongo-стора Express-сессий.

    Реализация: ``infrastructure.repositories.express_sessions_mongo
    .MongoExpressSessionStore``.
    """

    async def ping(self, session_id: str) -> Any:
        """Выполнить операцию ping."""
        ...


@runtime_checkable
class ExpressMetricsRecorderProtocol(Protocol):
    """Callable для записи метрики приёма команды Express.

    Реализация: ``infrastructure.observability.metrics.record_express_command_received``.
    """

    def __call__(self, bot: str, command: str) -> None:
        """Выполнить операцию   call  ."""
        ...


@runtime_checkable
class StreamClientProtocol(Protocol):
    """Контракт FastStream-клиента (Redis + RabbitMQ роутеры).

    Минимальная поверхность, которая нужна subscriber-модулям.
    Реализация: ``infrastructure.clients.messaging.stream.StreamClient``.
    """

    @property
    def redis_router(self) -> Any:
        """Выполнить операцию redis router."""
        ...

    @property
    def rabbit_router(self) -> Any:
        """Выполнить операцию rabbit router."""
        ...


@runtime_checkable
class ExpressBotClientProtocol(Protocol):
    """Контракт ExpressBotClient для отправки сообщений в BotX API.

    Реализация: ``infrastructure.clients.external.express_bot.ExpressBotClient``.
    """

    async def send_message(self, message: Any, sync: bool = False) -> str:
        """Выполнить операцию send message."""
        ...


@runtime_checkable
class HealthCheckServiceProtocol(Protocol):
    """Контракт health-check сервиса (ad-hoc check всех зависимостей).

    Реализация: ``infrastructure.monitoring.health_check.HealthCheckService``
    (singleton-фабрика ``get_healthcheck_service``).
    """

    async def check_all_services(self) -> dict[str, Any]:
        """Проверить all services."""
        ...


@runtime_checkable
class SLOTrackerProtocol(Protocol):
    """Контракт SLO-tracker'а для DSL-маршрутов (Latency P50/P95/P99).

    Реализация: ``infrastructure.application.slo_tracker.SLOTracker``.
    """

    def get_report(self) -> dict[str, Any]:
        """Получить report."""
        ...



@runtime_checkable
class RateLimiterProtocol(Protocol):
    """Контракт rate-limiter'а (S159 W2: test import contract).

    Methods:
        check: Проверить rate-limit для identifier по policy.
    """

    async def check(self, identifier: str, policy: Any) -> dict[str, Any]:
        """Проверить rate-limit, вернуть dict с метаданными (allowed, remaining, etc.)."""
        ...
