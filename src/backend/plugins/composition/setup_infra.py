from asyncio import to_thread
from inspect import isawaitable
from typing import Any, Awaitable, Callable

from src.backend.infrastructure.clients.external.logger import get_graylog_handler
from src.backend.infrastructure.clients.storage.clickhouse import get_clickhouse_client
from src.backend.infrastructure.clients.storage.redis import get_redis_client
from src.backend.infrastructure.clients.storage.s3_pool import get_s3_client
from src.backend.infrastructure.clients.transport.smtp import get_smtp_client
from src.backend.infrastructure.database.database import (
    get_db_initializer,
    get_external_db_registry,
)
from src.backend.infrastructure.decorators.caching import close_caches
from src.backend.infrastructure.external_apis.logging_service import get_log_manager
from src.backend.infrastructure.scheduler.scheduler_manager import get_scheduler_manager

__all__ = ("starting", "ending")


def _get_watcher_manager():
    """Ленивый импорт WatcherManager для избежания циклических зависимостей."""
    from src.backend.entrypoints.filewatcher.watcher_manager import watcher_manager

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
        from src.backend.infrastructure.application.health_aggregator import (
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
            redis_client = get_redis_client()
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
            async with get_db_initializer().get_async_engine().connect() as conn:
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
            is_ok = await get_s3_client().check_bucket_exists()
            return {
                "status": "ok" if is_ok else "degraded",
                "latency_ms": round((time.monotonic() - start) * 1000, 2),
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)[:200]}

    aggregator.register("redis", _redis_health)
    aggregator.register("database", _db_health)
    aggregator.register("s3", _s3_health)
    get_log_manager().application_logger.info(
        "Health checks registered: redis, database, s3"
    )


def _redis_enabled() -> bool:
    """Возвращает ``True``, если интеграция с Redis активна в текущем профиле.

    Используется как guard для startup/shutdown операций — в dev_light
    профиле ``redis.enabled=False`` и попытка подключения к Redis
    блокировала бы запуск (``perform_infrastructure_operation``
    падает на первой ошибке).
    """
    from src.backend.core.config.settings import settings

    return bool(getattr(settings.redis, "enabled", True))


def _s3_enabled() -> bool:
    """Возвращает ``True`` для S3-провайдеров (skip для ``local`` и ``enabled=False``)."""
    from src.backend.core.config.settings import settings

    fs = settings.storage
    return bool(getattr(fs, "enabled", True)) and fs.provider != "local"


def _clickhouse_enabled() -> bool:
    """Возвращает ``True``, если интеграция с ClickHouse активна.

    Управляется ``settings.clickhouse.enabled`` (default ``False``).
    Используется как guard startup/shutdown операций — в dev_light
    профиле ClickHouse выключен и подключение к нему блокировало бы старт.
    """
    from src.backend.core.config.settings import settings

    return bool(getattr(settings.clickhouse, "enabled", False))


async def _init_workflow_audit_sink() -> None:
    """Создаёт :class:`WorkflowAuditSink` + :class:`ClickHouseBulkWriter`.

    Прогоняет миграцию ``0010_workflow_audit.sql`` (idempotent),
    стартует bulk-writer и регистрирует singleton sink. Все шаги
    обёрнуты в ``try/except``: если ClickHouse недоступен — sink
    остаётся ``None``, и :class:`WorkflowFacade` работает в no-op
    режиме (см. docstring facade).
    """
    from pathlib import Path

    from src.backend.infrastructure.clients.storage.clickhouse_bulk_writer import (
        ClickHouseBulkWriter,
    )
    from src.backend.services.audit.workflow_audit_sink import (
        WorkflowAuditSink,
        set_workflow_audit_sink,
    )

    app_logger = get_log_manager().application_logger
    try:
        client = get_clickhouse_client()
        migrations_dir = (
            Path(__file__).resolve().parents[2] / "services" / "audit" / "migrations"
        )
        ddl_path = migrations_dir / "0010_workflow_audit.sql"
        if ddl_path.exists():
            await client.apply_ddl_file(ddl_path)
        writer = ClickHouseBulkWriter(client=client, table="workflow_audit")
        await writer.start()
        sink = WorkflowAuditSink(writer=writer)
        set_workflow_audit_sink(sink)
        app_logger.info("WorkflowAuditSink инициализирован")
    except Exception as exc:  # noqa: BLE001 — best-effort startup
        app_logger.warning("WorkflowAuditSink init skipped: %s", str(exc)[:200])


def _register_default_degradation_features() -> None:
    """Backbone-регистрация типовых features в GracefulDegradationRegistry.

    Real-handler'ы — заглушки ``_unsupported_full/_unsupported_degraded``;
    feature-owner подменяет их явным ``registry.register(...)`` при
    инициализации соответствующего модуля. Эта функция гарантирует, что
    admin-снимок ``/tech/degradation/snapshot`` сразу содержит ожидаемые
    feature-имена и operations dashboard не выглядит пустым.
    """
    from src.backend.core.resilience.graceful_degradation import (
        DegradationFeature,
        get_graceful_degradation_registry,
    )

    registry = get_graceful_degradation_registry()
    app_logger = get_log_manager().application_logger

    async def _unsupported_full(*_: Any, **__: Any) -> None:
        # Заглушка — owner feature'а обязан явно зарегистрировать
        # real-handler через registry.register(...).
        raise NotImplementedError("full_handler не зарегистрирован")

    async def _unsupported_degraded(*_: Any, **__: Any) -> None:
        raise NotImplementedError("degraded_handler не зарегистрирован")

    default_features = (
        "ai.llm_call",
        "rag.retrieval",
        "external.api_call",
        "cache.lookup",
    )
    for name in default_features:
        if registry.is_registered(name):
            continue
        registry.register(
            DegradationFeature(
                name=name,
                full_handler=_unsupported_full,
                degraded_handler=_unsupported_degraded,
            )
        )
    app_logger.info(
        "GracefulDegradationRegistry: %d default features зарегистрированы",
        len(default_features),
    )


async def _close_workflow_audit_sink() -> None:
    """Graceful shutdown sink: финальный flush + остановка writer'а."""
    from src.backend.services.audit.workflow_audit_sink import (
        get_workflow_audit_sink,
        reset_workflow_audit_sink,
    )

    sink = get_workflow_audit_sink()
    if sink is None:
        return
    try:
        await sink.aclose()
    finally:
        reset_workflow_audit_sink()


async def _warmup_connection_pools() -> None:
    """Pre-spin connection pools после initialize-фазы (S9 K2 W3, wired S10).

    Запускается после ``db_async_pool_main``/``db_async_pool_external``/
    ``redis``/``clickhouse_client`` — все пулы уже подключены, но физических
    соединений ещё нет. :class:`PoolWarmup` параллельно открывает
    ``min_connections`` соединений для каждого доступного backend, что
    устраняет cold-start latency первого запроса.

    Никогда не raise: :class:`PoolWarmup` поглощает per-pool exceptions
    и возвращает их в ``WarmupResult.failed_pools``. Hard-timeout 5s
    защищает от зависшего backend.
    """
    from src.backend.infrastructure.database.pool_warmup import PoolWarmup

    initializer = get_db_initializer()
    pg_engine = getattr(initializer, "async_engine", None)
    pg_replica_engine = getattr(initializer, "replica_engine", None)

    redis_cache_client: Any = None
    if _redis_enabled():
        try:
            redis_cache_client = await get_redis_client().get_client("cache")
        except Exception as _:  # noqa: BLE001 — warmup best-effort
            redis_cache_client = None

    clickhouse_client: Any = None
    if _clickhouse_enabled():
        clickhouse_client = get_clickhouse_client()

    if (
        pg_engine is None
        and pg_replica_engine is None
        and redis_cache_client is None
        and clickhouse_client is None
    ):
        # dev_light: все backends отключены — warmup нечего делать.
        return

    await PoolWarmup(
        pg_engine=pg_engine,
        pg_replica_engine=pg_replica_engine,
        redis_client=redis_cache_client,
        clickhouse_client=clickhouse_client,
        min_connections=3,
        timeout_seconds=5.0,
    ).warmup()


# Wave 6.1: операции обёрнуты в lambda — singletons резолвятся лениво,
# при первом исполнении операции, а не на module-level import.
starting_operations: list[OperationItem] = [
    ("graylog_client", lambda: to_thread(get_graylog_handler().connect), None),
    ("redis", lambda: get_redis_client().ensure_connected(), _redis_enabled),
    ("db_async_pool_main", lambda: get_db_initializer().initialize_async_pool(), None),
    (
        "db_async_pool_external",
        lambda: get_external_db_registry().initialize_all_pools(),
        None,
    ),
    ("s3_client", lambda: get_s3_client().connect(), _s3_enabled),
    (
        "clickhouse_client",
        lambda: get_clickhouse_client().connect(),
        _clickhouse_enabled,
    ),
    ("workflow_audit_sink", _init_workflow_audit_sink, _clickhouse_enabled),
    ("pool_warmup", _warmup_connection_pools, None),
    ("smtp_pool", lambda: get_smtp_client().initialize_pool(), None),
    (
        "redis_streams",
        lambda: get_redis_client().create_initial_streams(),
        _redis_enabled,
    ),
    ("scheduler", lambda: get_scheduler_manager().start(), None),
    ("health_aggregator", _register_health_checks, None),  # ARCH-3
    ("degradation_registry_bootstrap", _register_default_degradation_features, None),
]

ending_operations: list[OperationItem] = [
    ("file_watchers", lambda: _get_watcher_manager().stop_all(), None),
    ("scheduler", lambda: get_scheduler_manager().stop(), None),
    ("smtp_pool", lambda: get_smtp_client().close_pool(), None),
    ("workflow_audit_sink", _close_workflow_audit_sink, _clickhouse_enabled),
    (
        "clickhouse_client",
        lambda: get_clickhouse_client().aclose(),
        _clickhouse_enabled,
    ),
    ("s3_client", lambda: get_s3_client().close(), _s3_enabled),
    ("db_async_pool_external", lambda: get_external_db_registry().close_all(), None),
    ("db_async_pool_main", lambda: get_db_initializer().close(), None),
    ("graylog_client", lambda: to_thread(get_graylog_handler().close), None),
    ("cache_backends", close_caches, None),
    ("redis", lambda: get_redis_client().close(), _redis_enabled),
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
    app_logger = get_log_manager().application_logger
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
