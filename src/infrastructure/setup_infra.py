from asyncio import to_thread
from inspect import isawaitable
from typing import Any, Awaitable, Callable

from app.core.decorators.caching import close_caches
from app.core.decorators.limiting import init_limiter
from app.infrastructure.clients.logger import graylog_handler
from app.infrastructure.clients.redis import redis_client
from app.infrastructure.clients.smtp import smtp_client
from app.infrastructure.clients.storage import s3_client
from app.infrastructure.db.database import db_initializer, external_db_registry
from app.infrastructure.external_apis.logging_service import app_logger
from app.infrastructure.scheduler.scheduler_manager import scheduler_manager

__all__ = ("starting", "ending")


OperationCallable = Callable[[], Any | Awaitable[Any]]
OperationItem = tuple[str, OperationCallable]


starting_operations: list[OperationItem] = [
    ("graylog_client", lambda: to_thread(graylog_handler.connect)),
    ("redis", redis_client.ensure_connected),
    ("db_async_pool_main", db_initializer.initialize_async_pool),
    ("db_async_pool_external", external_db_registry.initialize_all_pools),
    ("s3_client", s3_client.connect),
    ("smtp_pool", smtp_client.initialize_pool),
    ("rate_limiter", init_limiter),
    ("redis_streams", redis_client.create_initial_streams),
    ("scheduler", scheduler_manager.start),
]

ending_operations: list[OperationItem] = [
    ("scheduler", scheduler_manager.stop),
    ("smtp_pool", smtp_client.close_pool),
    ("s3_client", s3_client.close),
    ("db_async_pool_external", external_db_registry.close_all),
    ("db_async_pool_main", db_initializer.close),
    ("graylog_client", lambda: to_thread(graylog_handler.close)),
    ("cache_backends", close_caches),
    ("redis", redis_client.close),
]


async def perform_infrastructure_operation(components: list[OperationItem]) -> None:
    """
    Последовательно выполняет startup/shutdown операции инфраструктуры.

    Логика:
    - порядок выполнения фиксирован и управляется списком `components`;
    - при первой критической ошибке выполнение прерывается;
    - подробности ошибки логируются в app_logger.
    """
    for name, operation in components:
        try:
            result = operation()

            if isawaitable(result):
                await result

            app_logger.info(
                "Операция инфраструктуры выполнена успешно", extra={"operation": name}
            )
        except Exception as exc:
            app_logger.critical(
                "Ошибка при выполнении операции инфраструктуры",
                extra={"operation": name, "error": str(exc)},
                exc_info=True,
            )
            raise


async def starting() -> None:
    """
    Инициализирует инфраструктурные зависимости приложения.
    """
    await perform_infrastructure_operation(starting_operations)


async def ending() -> None:
    """
    Корректно завершает инфраструктурные зависимости приложения.
    """
    await perform_infrastructure_operation(ending_operations)
