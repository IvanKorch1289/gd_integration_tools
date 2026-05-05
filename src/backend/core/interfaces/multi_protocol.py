"""Протоколы для entrypoints/* — Wave 6.5b.

Этот файл аналогичен ``integrations.py`` (W6.4), но описывает контракты,
требуемые в ``entrypoints/{cdc,email,express,graphql,grpc,mcp,scheduler,
stream,streamlit,webhook,websocket}/*``.

Реализации остаются в ``infrastructure/...``; entrypoints получают
объекты через ленивые провайдеры из ``core/di/providers.py``.

Все Protocol помечены ``@runtime_checkable``.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Protocol, runtime_checkable

__all__ = (
    "RateLimiterProtocol",
    "RedisHashProtocol",
    "RedisSetProtocol",
    "RedisCursorProtocol",
    "RedisPubSubProtocol",
    "CDCClientProtocol",
    "VaultRefresherProtocol",
    "LoggerProtocol",
    "MongoExpressDialogStoreProtocol",
    "MongoExpressSessionStoreProtocol",
    "ExpressMetricsRecorderProtocol",
    "StreamClientProtocol",
    "ExpressBotClientProtocol",
    "HealthCheckServiceProtocol",
    "SLOTrackerProtocol",
)


# ─────────────────────── Rate limiter ───────────────────────


@runtime_checkable
class RateLimiterProtocol(Protocol):
    """Контракт rate-limiter'а для webhook/inbound endpoints.

    Реализация: ``infrastructure.resilience.unified_rate_limiter
    .RedisRateLimiter`` (singleton ``get_rate_limiter()``).
    """

    async def check(self, identifier: str, policy: Any) -> dict[str, Any]: ...


# ─────────────────────── Redis coordinator primitives ───────────────────────


@runtime_checkable
class RedisHashProtocol(Protocol):
    """Контракт shared HASH-структуры (multi-instance webhook subs etc.)."""

    async def set(self, field: str, value: Any) -> None: ...
    async def get(self, field: str) -> Any: ...
    async def delete(self, field: str) -> bool: ...
    async def all(self) -> dict[str, Any]: ...


@runtime_checkable
class RedisSetProtocol(Protocol):
    """Контракт shared SET-структуры (group membership)."""

    async def add(self, *members: str) -> int: ...
    async def remove(self, *members: str) -> int: ...
    async def members(self) -> set[str]: ...
    async def contains(self, member: str) -> bool: ...


@runtime_checkable
class RedisCursorProtocol(Protocol):
    """Контракт CAS-cursor (CDC last_check etc.)."""

    async def get(self) -> Any: ...
    async def set(self, value: Any) -> bool: ...


@runtime_checkable
class RedisPubSubProtocol(Protocol):
    """Контракт cross-instance pub/sub (WS broadcast, cache invalidation)."""

    async def publish(self, message: Any) -> int: ...
    def subscribe(self) -> AsyncIterator[Any]: ...


# ─────────────────────── CDC client ───────────────────────


@runtime_checkable
class CDCClientProtocol(Protocol):
    """Контракт CDC-клиента для управления подписками на изменения внешних БД.

    Реализация: ``infrastructure.clients.external.cdc.CDCClient``.
    """

    async def subscribe(
        self, *, profile: str, tables: list[str], target_action: str | None = None
    ) -> str: ...
    async def unsubscribe(self, subscription_id: str) -> bool: ...
    def list_subscriptions(self) -> list[dict[str, Any]]: ...


# ─────────────────────── Vault refresher ───────────────────────


@runtime_checkable
class VaultRefresherProtocol(Protocol):
    """Контракт получения секретов из Vault (по ссылке вида ``vault:<path>#<key>``).

    Реализация: ``infrastructure.application.vault_refresher.VaultSecretRefresher``.
    """

    async def resolve(self, ref: str) -> str: ...


# ─────────────────────── Logging service ───────────────────────


@runtime_checkable
class LoggerProtocol(Protocol):
    """Минимальная поверхность structured-логгера.

    Реализация: разные ``logger`` из
    ``infrastructure.external_apis.logging_service``
    (``app_logger``, ``stream_logger``, ``grpc_logger`` и т.д.).
    """

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None: ...
    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None: ...
    def error(self, msg: str, *args: Any, **kwargs: Any) -> None: ...
    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None: ...


# ─────────────────────── Express Mongo stores ───────────────────────


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
    ) -> None: ...


@runtime_checkable
class MongoExpressSessionStoreProtocol(Protocol):
    """Контракт Mongo-стора Express-сессий.

    Реализация: ``infrastructure.repositories.express_sessions_mongo
    .MongoExpressSessionStore``.
    """

    async def ping(self, session_id: str) -> Any: ...


# ─────────────────────── Express metrics recorder ───────────────────────


@runtime_checkable
class ExpressMetricsRecorderProtocol(Protocol):
    """Callable для записи метрики приёма команды Express.

    Реализация: ``infrastructure.observability.metrics.record_express_command_received``.
    """

    def __call__(self, bot: str, command: str) -> None: ...


# ─────────────────────── FastStream client ───────────────────────


@runtime_checkable
class StreamClientProtocol(Protocol):
    """Контракт FastStream-клиента (Redis + RabbitMQ роутеры).

    Минимальная поверхность, которая нужна subscriber-модулям.
    Реализация: ``infrastructure.clients.messaging.stream.StreamClient``.
    """

    @property
    def redis_router(self) -> Any: ...
    @property
    def rabbit_router(self) -> Any: ...


# ─────────────────────── Express BotX client ───────────────────────


@runtime_checkable
class ExpressBotClientProtocol(Protocol):
    """Контракт ExpressBotClient для отправки сообщений в BotX API.

    Реализация: ``infrastructure.clients.external.express_bot.ExpressBotClient``.
    """

    async def send_message(self, message: Any, sync: bool = False) -> str: ...


# ─────────────────────── Health-check service ───────────────────────


@runtime_checkable
class HealthCheckServiceProtocol(Protocol):
    """Контракт health-check сервиса (ad-hoc check всех зависимостей).

    Реализация: ``infrastructure.monitoring.health_check.HealthCheckService``
    (singleton-фабрика ``get_healthcheck_service``).
    """

    async def check_all_services(self) -> dict[str, Any]: ...


# ─────────────────────── SLO tracker ───────────────────────


@runtime_checkable
class SLOTrackerProtocol(Protocol):
    """Контракт SLO-tracker'а для DSL-маршрутов (Latency P50/P95/P99).

    Реализация: ``infrastructure.application.slo_tracker.SLOTracker``.
    """

    def get_report(self) -> dict[str, Any]: ...
