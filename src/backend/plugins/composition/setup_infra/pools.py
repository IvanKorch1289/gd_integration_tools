from __future__ import annotations

"""S60 W3 — pools.py part of setup_infra decomp.

Funcs: _register_pools_in_unified_manager, _warmup_connection_pools, _redis_enabled, _s3_enabled, _clickhouse_enabled.

connection pool registration + backend enablement checks.
"""

from typing import Any

from src.backend.infrastructure.clients.storage.clickhouse import get_clickhouse_client
from src.backend.infrastructure.clients.storage.redis import get_redis_client
from src.backend.infrastructure.clients.storage.s3_pool import get_s3_client
from src.backend.infrastructure.database.database import get_db_initializer
from src.backend.infrastructure.logging.factory import get_logger

app_logger = get_logger("application")


async def _register_pools_in_unified_manager() -> None:
    """S37.2: Register connection pools in UnifiedPoolManager.

    Provides centralised metrics and health-check aggregation for
    all backend pools.
    """
    try:
        from src.backend.infrastructure.clients.unified_pool_manager import (
            get_unified_pool_manager,
        )
    except ImportError:
        return

    manager = get_unified_pool_manager()

    # DB main
    try:
        db_engine = get_db_initializer().get_async_engine()
        pool = getattr(db_engine, "pool", None)
        if pool is not None:
            from sqlalchemy import text

            async def _ping_db() -> None:
                async with db_engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))

            manager.register(
                "db_main",
                pool,
                ping_fn=_ping_db,
                kind="sqlalchemy",
                max_size=getattr(pool, "size", lambda: 0)()
                if callable(getattr(pool, "size", None))
                else 0,
            )
    except Exception as exc:
        app_logger.debug("UnifiedPoolManager db_main skipped: %s", exc)

    # Redis
    if _redis_enabled():
        try:
            redis_client = await get_redis_client().get_client("cache")

            async def _ping_redis() -> None:
                await redis_client.ping()

            manager.register(
                "redis_cache", redis_client, ping_fn=_ping_redis, kind="redis"
            )
        except Exception as exc:
            app_logger.debug("UnifiedPoolManager redis skipped: %s", exc)

    # S3
    if _s3_enabled():
        try:
            s3_client = get_s3_client()

            async def _ping_s3() -> None:
                await s3_client.check_bucket_exists()

            manager.register("s3_main", s3_client, ping_fn=_ping_s3, kind="s3")
        except Exception as exc:
            app_logger.debug("UnifiedPoolManager s3 skipped: %s", exc)

    # ClickHouse
    if _clickhouse_enabled():
        try:
            ch_client = get_clickhouse_client()

            async def _ping_ch() -> None:
                await ch_client.ping()

            manager.register(
                "clickhouse_main", ch_client, ping_fn=_ping_ch, kind="clickhouse"
            )
        except Exception as exc:
            app_logger.debug("UnifiedPoolManager clickhouse skipped: %s", exc)

    # S80 W2: LiteLLM Gateway (FINAL_REPORT_V2 P1 #6).
    # LiteLLM SDK manages connections internally (no native pool),
    # so we register as LOGICAL pool with custom ping (model list
    # query as liveness check).
    try:
        from src.backend.core.config.features import feature_flags
        if feature_flags.ai_gateway_enabled:
            from src.backend.services.ai.gateway.client import (
                get_litellm_gateway,
            )
            from src.backend.services.ai.gateway.pool_registration import (
                register_litellm_pool,
            )
            gateway = get_litellm_gateway()
            register_litellm_pool(gateway, name="litellm_main", idle_timeout=60.0)
    except Exception as exc:
        app_logger.debug("UnifiedPoolManager litellm skipped: %s", exc)

    app_logger.info("UnifiedPoolManager registered %d pools", len(manager.list_pools()))


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
        except Exception as _:
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
