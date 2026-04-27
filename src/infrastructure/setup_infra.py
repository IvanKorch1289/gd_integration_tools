from asyncio import to_thread
from inspect import isawaitable
from typing import Any, Awaitable, Callable

from src.infrastructure.clients.external.logger import graylog_handler
from src.infrastructure.clients.storage.redis import redis_client
from src.infrastructure.clients.storage.s3_pool import s3_client
from src.infrastructure.clients.transport.smtp import smtp_client
from src.infrastructure.database.database import db_initializer, external_db_registry
from src.infrastructure.decorators.caching import close_caches
from src.infrastructure.decorators.limiting import init_limiter
from src.infrastructure.external_apis.logging_service import app_logger
from src.infrastructure.scheduler.scheduler_manager import scheduler_manager

__all__ = ("starting", "ending")


def _get_watcher_manager():
    """Ленивый импорт WatcherManager для избежания циклических зависимостей."""
    from src.entrypoints.filewatcher.watcher_manager import watcher_manager

    return watcher_manager


OperationCallable = Callable[[], Any | Awaitable[Any]]
OperationItem = tuple[str, OperationCallable]


async def _register_health_checks() -> None:
    """ARCH-3: Wire HealthAggregator to infrastructure components.

    Regisers ping-based health checks for Redis, DB, S3, SMTP.
    Aggregator exposes unified /health endpoint for K8s probes.
    """
    try:
        from src.infrastructure.application.health_aggregator import (
            get_health_aggregator,
        )
    except ImportError:
        return

    aggregator = get_health_aggregator()

    # Redis
    async def _redis_health() -> dict[str, Any]:
        import time

        start = time.monotonic()
        try:
            raw = getattr(redis_client, "_raw_client", None) or redis_client
            await raw.ping()
            return {
                "status": "ok",
                "latency_ms": round((time.monotonic() - start) * 1000, 2),
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)[:200]}

    # DB main
    async def _db_health() -> dict[str, Any]:
        import time

        from sqlalchemy import text

        start = time.monotonic()
        try:
            async with db_initializer.get_async_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
            return {
                "status": "ok",
                "latency_ms": round((time.monotonic() - start) * 1000, 2),
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)[:200]}

    # S3
    async def _s3_health() -> dict[str, Any]:
        import time

        start = time.monotonic()
        try:
            is_ok = await s3_client.check_bucket_exists()
            return {
                "status": "ok" if is_ok else "degraded",
                "latency_ms": round((time.monotonic() - start) * 1000, 2),
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)[:200]}

    aggregator.register("redis", _redis_health)
    aggregator.register("database", _db_health)
    aggregator.register("s3", _s3_health)
    app_logger.info("Health checks registered: redis, database, s3")


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
    ("health_aggregator", _register_health_checks),  # ARCH-3
]

ending_operations: list[OperationItem] = [
    ("file_watchers", lambda: _get_watcher_manager().stop_all()),
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
