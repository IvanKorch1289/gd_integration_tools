"""Протоколы для инфраструктурных клиентов и сервисов.

Wave 6.4: создано для устранения layer-violations в
``services/{io,ops,integrations,execution}/*``, которые ранее напрямую
импортировали ``infrastructure.*``.

Контракты описывают только публичную поверхность, которая нужна
сервисам — дополнительные методы конкретных реализаций намеренно не
включаются в Protocol, чтобы упростить замену backend'а в тестах.

Реализации остаются в ``infrastructure/...``:

* :class:`BrowserClientProtocol` —
  ``infrastructure.clients.transport.browser.BrowserClient``
* :class:`ClickHouseClientProtocol` —
  ``infrastructure.clients.storage.clickhouse.ClickHouseClient``
* :class:`SmtpClientProtocol` —
  ``infrastructure.clients.transport.smtp.SmtpClient``
* :class:`ExpressClientProtocol` —
  ``infrastructure.clients.external.express.ExpressClient``
* :class:`SchedulerManagerProtocol` —
  ``infrastructure.scheduler.scheduler_manager.SchedulerManager``
* :class:`TaskIQBrokerProtocol` —
  ``infrastructure.execution.taskiq_broker.get_invocation_task``
* :class:`ExternalSessionManagerProtocol` —
  ``infrastructure.database.session_manager.DatabaseSessionManager``
* :class:`SignatureBuilderProtocol` —
  ``infrastructure.security.signatures.build_signature_headers``
* :class:`CachingDecoratorProtocol` —
  ``infrastructure.decorators.caching.response_cache``
* :class:`ConnectorConfigStoreProtocol` —
  ``infrastructure.repositories.connector_configs_mongo.MongoConnectorConfigStore``

Все Protocol помечены ``@runtime_checkable``.
"""

from __future__ import annotations

from typing import Any, AsyncContextManager, Callable, Protocol, runtime_checkable

__all__ = (
    "BrowserClientProtocol",
    "ClickHouseClientProtocol",
    "SmtpClientProtocol",
    "ExpressClientProtocol",
    "RedisKeyValueClientProtocol",
    "SchedulerManagerProtocol",
    "TaskIQBrokerProtocol",
    "ExternalSessionManagerProtocol",
    "SignatureBuilderProtocol",
    "CachingDecoratorProtocol",
    "ConnectorConfigStoreProtocol",
)


# ─────────────────────── Web automation (browser) ───────────────────────


@runtime_checkable
class BrowserClientProtocol(Protocol):
    """Контракт async browser-клиента (Playwright-обёртка).

    Реализация: ``infrastructure.clients.transport.browser.BrowserClient``.
    """

    async def navigate(self, url: str) -> dict[str, Any]: ...
    async def click(self, url: str, selector: str) -> dict[str, Any]: ...
    async def fill_form(
        self, url: str, fields: dict[str, str], submit: str | None = None
    ) -> dict[str, Any]: ...
    async def extract_text(self, url: str, selector: str) -> list[str]: ...
    async def extract_table(
        self, url: str, selector: str
    ) -> list[dict[str, str]]: ...
    async def screenshot(self, url: str) -> bytes: ...
    async def run_scenario(
        self, steps: list[dict[str, Any]]
    ) -> list[dict[str, Any]]: ...


# ─────────────────────── ClickHouse analytics ───────────────────────


@runtime_checkable
class ClickHouseClientProtocol(Protocol):
    """Контракт async ClickHouse-клиента для analytics.

    Реализация: ``infrastructure.clients.storage.clickhouse.ClickHouseClient``.
    """

    async def query(
        self, sql: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]: ...
    async def insert(self, table: str, rows: list[dict[str, Any]]) -> int: ...
    async def aggregate(
        self,
        table: str,
        agg_func: str,
        column: str,
        group_by: str | None = None,
        where: str | None = None,
    ) -> list[dict[str, Any]]: ...
    async def ping(self) -> bool: ...


# ─────────────────────── SMTP / Email ───────────────────────


@runtime_checkable
class SmtpClientProtocol(Protocol):
    """Контракт SMTP-клиента для email-уведомлений.

    Реализация: ``infrastructure.clients.transport.smtp.SmtpClient``.
    """

    async def send_email(
        self,
        to: Any,
        subject: str,
        body: str,
        content_type: str = "text/plain",
        **kwargs: Any,
    ) -> Any: ...
    async def test_connection(self) -> bool: ...


# ─────────────────────── eXpress messenger ───────────────────────


@runtime_checkable
class ExpressClientProtocol(Protocol):
    """Контракт клиента корпоративного мессенджера eXpress (BotX API).

    Реализация: ``infrastructure.clients.external.express.ExpressClient``.
    """

    async def send_message(self, chat_id: str, text: str) -> dict[str, Any]: ...
    async def send_direct(self, user_huid: str, text: str) -> dict[str, Any]: ...
    async def send_notification(
        self, group_chat_ids: list[str], text: str
    ) -> dict[str, Any]: ...
    async def create_chat(
        self,
        name: str,
        members: list[str],
        description: str = "",
        chat_type: str = "group_chat",
    ) -> dict[str, Any]: ...


# ─────────────────────── Redis (key-value) ───────────────────────


@runtime_checkable
class RedisKeyValueClientProtocol(Protocol):
    """Контракт Redis-клиента для key-value операций (webhook scheduler).

    Описывает поверхность объекта ``redis_client.client`` — `redis.asyncio`-
    клиента (см. ``infrastructure.clients.storage.redis``).
    """

    async def set(
        self, key: str, value: Any, ex: int | None = None, **kwargs: Any
    ) -> Any: ...
    async def get(self, key: str) -> Any: ...
    async def delete(self, *keys: str) -> int: ...
    def scan_iter(self, match: str | None = None, **kwargs: Any) -> Any: ...


# ─────────────────────── Scheduler (APScheduler) ───────────────────────


@runtime_checkable
class SchedulerManagerProtocol(Protocol):
    """Контракт менеджера планировщика (APScheduler-обёртка).

    Минимальная поверхность, которая нужна для DEFERRED-режима Invoker'а:
    публикация одноразовых job через ``scheduler.add_job(...)``.

    Реализация: ``infrastructure.scheduler.scheduler_manager.SchedulerManager``.
    """

    @property
    def scheduler(self) -> Any:
        """Лежащий в основе APScheduler ``AsyncIOScheduler``."""
        ...


# ─────────────────────── TaskIQ broker ───────────────────────


@runtime_checkable
class TaskIQBrokerProtocol(Protocol):
    """Контракт фабрики TaskIQ-task для ASYNC_QUEUE-режима Invoker'а.

    Реализация: ``infrastructure.execution.taskiq_broker.get_invocation_task``
    (callable без аргументов, возвращает ``AsyncTaskiqDecoratedTask``).
    """

    def __call__(self) -> Any:
        """Возвращает декорированный TaskIQ-task с методом ``.kiq(...)``."""
        ...


# ─────────────────────── External database session ───────────────────────


@runtime_checkable
class ExternalSessionManagerProtocol(Protocol):
    """Контракт менеджера сессий внешней БД (read-only / RPC).

    Реализация: ``infrastructure.database.session_manager.DatabaseSessionManager``.
    """

    def create_session(self) -> AsyncContextManager[Any]:
        """Возвращает async context manager с SQLAlchemy ``AsyncSession``."""
        ...


# ─────────────────────── HMAC signatures ───────────────────────


@runtime_checkable
class SignatureBuilderProtocol(Protocol):
    """Контракт генератора HMAC-заголовков для outgoing webhook.

    Реализация: ``infrastructure.security.signatures.build_signature_headers``.
    """

    def __call__(
        self, payload: dict[str, Any] | bytes | str, secret: str
    ) -> dict[str, str]:
        """Возвращает заголовки с HMAC-подписью."""
        ...


# ─────────────────────── Caching decorator ───────────────────────


@runtime_checkable
class CachingDecoratorProtocol(Protocol):
    """Контракт декоратора response cache (memory + redis backend).

    Реализация: ``infrastructure.decorators.caching.response_cache``.
    Используется как декоратор: ``@response_cache``.
    """

    def __call__(self, func: Callable[..., Any]) -> Callable[..., Any]: ...


# ─────────────────────── Connector config store (Mongo) ───────────────────────


@runtime_checkable
class ConnectorConfigStoreProtocol(Protocol):
    """Контракт хранилища ``ConnectorConfig`` (W24 ImportService).

    Реализация: ``infrastructure.repositories.connector_configs_mongo
    .MongoConnectorConfigStore``.
    """

    async def get(self, name: str) -> Any: ...
    async def save(
        self,
        name: str,
        config: dict[str, Any],
        enabled: bool = True,
        user: str | None = None,
    ) -> Any: ...
    async def list_all(self) -> list[Any]: ...
    async def delete(self, name: str) -> bool: ...
