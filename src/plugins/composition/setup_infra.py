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
# Третий элемент — guard, возвращающий ``True`` если операцию нужно
# выполнять (для dev_light без Redis/S3 — пропускается). ``None`` ≡ всегда.
OperationItem = tuple[str, OperationCallable, Callable[[], bool] | None]


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


def _redis_enabled() -> bool:
    """Возвращает ``True``, если интеграция с Redis активна в текущем профиле.

    Используется как guard для startup/shutdown операций — в dev_light
    профиле ``redis.enabled=False`` и попытка подключения к Redis
    блокировала бы запуск (``perform_infrastructure_operation``
    падает на первой ошибке).
    """
    from src.core.config.settings import settings

    return bool(getattr(settings.redis, "enabled", True))


def _s3_enabled() -> bool:
    """Возвращает ``True`` для S3-провайдеров (skip для ``local`` и ``enabled=False``)."""
    from src.core.config.settings import settings

    fs = settings.storage
    return bool(getattr(fs, "enabled", True)) and fs.provider != "local"


def _taskiq_enabled() -> bool:
    """Возвращает ``True``, если TaskIQ broker должен стартовать.

    Управляется env-переменной ``TASKIQ_ENABLED`` (default ``true``).
    Полезно отключить для unit-тестов / dev_light без TaskIQ.
    """
    import os

    return os.getenv("TASKIQ_ENABLED", "true").lower() in ("1", "true", "yes")


async def _taskiq_startup() -> None:
    """Стартует TaskIQ broker.

    * ``InMemoryBroker`` — исполняет задачи inline в этом процессе
      (worker не нужен).
    * ``ListQueueBroker(Redis)`` — kiq() пушит в Redis; для исполнения
      нужен **отдельный процесс** worker'а:
      ``taskiq worker src.infrastructure.execution.taskiq_broker:broker``
      (см. ``docs/runbooks/taskiq-worker.md``).

    Также гарантирует регистрацию task ``invoker.run`` (декоратор
    срабатывает при первом ``get_invocation_task()``).
    """
    from src.infrastructure.execution.taskiq_broker import (
        get_broker,
        get_invocation_task,
    )

    broker = get_broker()
    await broker.startup()
    # Зарегистрировать taskiq-task до того, как kicker / worker
    # обратится к ней по имени ``invoker.run``.
    get_invocation_task()


async def _taskiq_shutdown() -> None:
    """Останавливает TaskIQ broker."""
    from src.infrastructure.execution.taskiq_broker import get_broker

    broker = get_broker()
    await broker.shutdown()


starting_operations: list[OperationItem] = [
    ("graylog_client", lambda: to_thread(graylog_handler.connect), None),
    ("redis", redis_client.ensure_connected, _redis_enabled),
    ("db_async_pool_main", db_initializer.initialize_async_pool, None),
    ("db_async_pool_external", external_db_registry.initialize_all_pools, None),
    ("s3_client", s3_client.connect, _s3_enabled),
    ("smtp_pool", smtp_client.initialize_pool, None),
    ("rate_limiter", init_limiter, _redis_enabled),
    ("redis_streams", redis_client.create_initial_streams, _redis_enabled),
    ("scheduler", scheduler_manager.start, None),
    ("taskiq_broker", _taskiq_startup, _taskiq_enabled),
    ("health_aggregator", _register_health_checks, None),  # ARCH-3
]

ending_operations: list[OperationItem] = [
    ("file_watchers", lambda: _get_watcher_manager().stop_all(), None),
    ("scheduler", scheduler_manager.stop, None),
    ("taskiq_broker", _taskiq_shutdown, _taskiq_enabled),
    ("smtp_pool", smtp_client.close_pool, None),
    ("s3_client", s3_client.close, _s3_enabled),
    ("db_async_pool_external", external_db_registry.close_all, None),
    ("db_async_pool_main", db_initializer.close, None),
    ("graylog_client", lambda: to_thread(graylog_handler.close), None),
    ("cache_backends", close_caches, None),
    ("redis", redis_client.close, _redis_enabled),
]


async def perform_infrastructure_operation(components: list[OperationItem]) -> None:
    """
    Последовательно выполняет startup/shutdown операции инфраструктуры.

    Логика:
    - порядок выполнения фиксирован и управляется списком `components`;
    - каждый элемент содержит опциональный guard ``enabled_check``;
      если он возвращает ``False``, операция пропускается с info-логом
      (используется для dev_light, где Redis/S3 отключены);
    - при первой критической ошибке выполнение прерывается;
    - подробности ошибки логируются в app_logger.
    """
    for name, operation, enabled_check in components:
        if enabled_check is not None and not enabled_check():
            app_logger.info(
                "Операция инфраструктуры пропущена (disabled)",
                extra={"operation": name},
            )
            continue
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
