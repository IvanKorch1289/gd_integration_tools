"""S60 W3 — health.py part of setup_infra decomp.

Funcs: _get_watcher_manager, _register_health_checks, _sink_registry_check,
_sink_kind_check, _source_kind_check, _make_kind_health.

health check registration (132 LOC main func + helper).

S203 W2+W3: добавлены health-проверки для каждого зарегистрированного
Sink/Source-kind через ``SinkRegistry`` и ``SourceRegistry``. Использует
существующий ``HealthAggregator`` (а не ``HealthFacade`` из
``services/monitoring/`` — последний dead code, никем не вызывается).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.backend.core.interfaces.sink import SinkKind
from src.backend.core.interfaces.source import SourceKind
from src.backend.core.logging import get_logger
from src.backend.infrastructure.clients.base_connector import HealthResult
from src.backend.infrastructure.clients.storage.clickhouse import get_clickhouse_client
from src.backend.infrastructure.clients.storage.redis import get_redis_client
from src.backend.infrastructure.clients.storage.s3_pool import get_s3_client
from src.backend.infrastructure.database.database import get_db_initializer
from src.backend.plugins.composition.setup_infra.pools import _clickhouse_enabled
from src.backend.services.sources.registry import get_sink_registry, get_source_registry

app_logger = get_logger("application")


def _get_watcher_manager():
    """Ленивый импорт WatcherManager для избежания циклических зависимостей."""
    from src.backend.entrypoints.filewatcher.watcher_manager import watcher_manager

    return watcher_manager


async def _register_health_checks() -> None:
    """ARCH-3: Wire HealthAggregator to infrastructure components.

    Registers ping-based health checks for Redis, DB, S3, SMTP,
    ClickHouse, Kafka (TCP probe) and NATS (TCP probe).
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

    # ClickHouse
    async def _clickhouse_health() -> dict[str, Any]:
        import time

        start = time.monotonic()
        try:
            ok = await get_clickhouse_client().ping()
            return {
                "status": "ok" if ok else "degraded",
                "latency_ms": round((time.monotonic() - start) * 1000, 2),
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)[:200]}

    # Kafka — lightweight TCP probe (avoids aiokafka import overhead)
    async def _kafka_health() -> dict[str, Any]:
        import asyncio
        import time

        from src.backend.core.config.services.queue import queue_settings

        if queue_settings.type != "kafka":
            return {"status": "skipped", "reason": "queue.type != kafka"}

        start = time.monotonic()
        host = queue_settings.host
        port = queue_settings.port
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=2.0,
            )
            writer.close()
            await writer.wait_closed()
            return {
                "status": "ok",
                "latency_ms": round((time.monotonic() - start) * 1000, 2),
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)[:200]}

    # NATS — lightweight TCP probe
    async def _nats_health() -> dict[str, Any]:
        import asyncio
        import time

        start = time.monotonic()
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection("localhost", 4222), timeout=2.0,
            )
            writer.close()
            await writer.wait_closed()
            return {
                "status": "ok",
                "latency_ms": round((time.monotonic() - start) * 1000, 2),
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)[:200]}

    aggregator.register("redis", _redis_health)
    aggregator.register("database", _db_health)
    aggregator.register("s3", _s3_health)
    if _clickhouse_enabled():
        aggregator.register("clickhouse", _clickhouse_health)
    aggregator.register("kafka", _kafka_health)
    aggregator.register("nats", _nats_health)

    # Wave 1: auto-include all ConnectorRegistry clients in /health
    aggregator.include_registry(True)

    # S203 W3: register per-kind health checks для всех Sink/Source kinds.
    # Каждая проверка пингует ОДИН зарегистрированный инстанс данного kind
    # (singleton-per-kind). Если ни одного — возвращает ``skipped``.
    _register_sink_source_checks(aggregator)

    app_logger.info(
        "Health checks registered: redis, database, s3, clickhouse, kafka, nats, "
        "+ sink/source per-kind checks",
    )


def _make_kind_health(
    kind_value: str,
    registry_attr: str,
) -> Callable[..., Any]:
    """Создать health-check для одного SinkKind/SourceKind.

    Args:
        kind_value: ``SinkKind.<X>.value`` или ``SourceKind.<X>.value``.
        registry_attr: ``"sink"`` или ``"source"``.

    Returns:
        Async-функция для ``aggregator.register(name, ...)``.
        Семантика возврата: dict с ``status`` (``ok`` / ``failed`` / ``skipped``)
        и ``latency_ms`` — как и остальные проверки в этом файле.

    """

    async def _check() -> dict[str, Any]:
        import time

        start = time.monotonic()
        try:
            if registry_attr == "sink":
                reg = get_sink_registry()
                instances = [s for s in reg.all() if s.kind.value == kind_value]
            else:
                reg = get_source_registry()
                instances = [
                    s for s in reg.all() if s.kind.value == kind_value
                ]

            if not instances:
                return {
                    "status": "skipped",
                    "reason": f"no {registry_attr} of kind={kind_value} registered",
                    "latency_ms": round((time.monotonic() - start) * 1000, 2),
                }

            # Пингуем только первый зарегистрированный (singleton-per-kind).
            # Все инстансы одного kind обычно шарят один backend.
            target = instances[0]
            result = await target.health(mode="fast")
            latency_ms = round((time.monotonic() - start) * 1000, 2)

            # HealthResult → dict (нормализация через _result_to_dict).
            if isinstance(result, HealthResult):
                status = result.status
                error = result.error
            elif isinstance(result, dict):
                status = result.get("status", "ok")
                error = result.get("error")
            else:
                status = "ok"
                error = None

            return {
                "status": status,
                "latency_ms": latency_ms,
                "error": error,
            }
        except Exception as exc:
            return {
                "status": "error",
                "error": str(exc)[:200],
                "latency_ms": round((time.monotonic() - start) * 1000, 2),
            }

    return _check


def _register_sink_source_checks(aggregator: Any) -> None:
    """S203 W3: зарегистрировать per-kind health checks для всех sink/source kinds.

    Не падает, если ни одного инстанса не зарегистрировано — для каждого kind
    добавляется ``skipped``-проверка, чтобы /health сразу показывал
    полную матрицу доступных connector'ов.
    """
    for kind in SinkKind:
        if kind == SinkKind.SMS:
            # SMS ещё не реализован — пропускаем чтобы не плодить ошибки в /health.
            continue
        name = f"sink_{kind.value}"
        aggregator.register(name, _make_kind_health(kind.value, "sink"))

    for kind in SourceKind:
        name = f"source_{kind.value}"
        aggregator.register(name, _make_kind_health(kind.value, "source"))
