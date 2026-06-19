"""S168 W13 P2-7: moved from src/backend/workflows/outbox_worker.py to
src/backend/infrastructure/workflow/outbox_worker.py per master prompt v8 P2-7.

Outbox worker — периодический publisher для transactional messaging.

Worker запускается в lifecycle startup, каждые ``interval_seconds`` читает
таблицу ``outbox_messages`` со статусом ``pending``, публикует в соответствующий
брокер (Kafka/Rabbit/Redis Streams) по правилам routing и помечает запись.

Routing по topic (все через FastStream ``StreamClient``):

* ``kafka:<topic>`` → ``publish_to_kafka``.
* ``rabbit:<queue>`` → ``publish_to_rabbit``.
* ``redis:<stream>`` → ``publish_to_redis``.
* без префикса → Kafka по умолчанию.

Идемпотентность: обновление ``status`` защищает от повторной публикации.
Retry с экспоненциальным backoff управляется из :mod:`repositories.outbox`.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger

__all__ = (
    "start_outbox_worker",
    "stop_outbox_worker",
    "run_once",
    "sweep_stuck_once",  # S72 W3, TD-S64-W1 sweeper
)

logger = get_logger("workflows.outbox")

_scheduler: Any = None


async def _publish(
    topic: str, payload: dict[str, Any], headers: dict[str, Any]
) -> None:
    """Публикует payload в брокер по префиксу topic.

    Raises:
        Exception: Любая ошибка пробрасывается вызывающему (_run_once), чтобы
        тот обновил retry_count.
    """
    if ":" in topic:
        protocol, dest = topic.split(":", 1)
    else:
        protocol, dest = "kafka", topic

    match protocol:
        case "kafka":
            from src.backend.infrastructure.clients.messaging.stream import (
                get_stream_client,
            )

            await get_stream_client().publish_to_kafka(
                topic=dest, message=payload, headers=headers
            )
        case "rabbit":
            from src.backend.infrastructure.clients.messaging.stream import (
                get_stream_client,
            )

            await get_stream_client().publish_to_rabbit(queue=dest, message=payload)
        case "redis":
            from src.backend.infrastructure.clients.messaging.stream import (
                get_stream_client,
            )

            await get_stream_client().publish_to_redis(
                stream=dest, message=payload, headers=headers
            )
        case _:
            raise ValueError(f"Неизвестный protocol '{protocol}' в topic '{topic}'")


async def run_once(*, batch_size: int = 100) -> dict[str, int]:
    """Одна итерация worker'а. Возвращает статистику.

    Вынесена в отдельную функцию для удобства юнит-тестов и ручного запуска
    через admin-эндпоинт.
    """
    from src.backend.infrastructure.repositories import outbox as outbox_repo

    pending = await outbox_repo.fetch_pending(limit=batch_size)
    stats = {"fetched": len(pending), "sent": 0, "failed": 0}

    for msg in pending:
        try:
            await _publish(msg.topic, msg.payload, msg.headers or {})
            await outbox_repo.mark_sent(msg.id)
            stats["sent"] += 1
        except Exception as exc:
            logger.warning("Outbox publish failed (id=%s): %s", msg.id, exc)
            await outbox_repo.mark_failed(msg.id, str(exc))
            stats["failed"] += 1
    return stats


def start_outbox_worker(*, interval_seconds: int = 5, batch_size: int = 100) -> None:
    """Запускает APScheduler job, тикающий каждые ``interval_seconds``.

    Идемпотентна — повторный вызов не создаёт второй job.
    """
    global _scheduler
    if _scheduler is not None:
        return
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
    except ImportError:
        logger.error("APScheduler не установлен, outbox worker выключен")
        return

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        run_once,
        trigger="interval",
        seconds=interval_seconds,
        kwargs={"batch_size": batch_size},
        id="outbox_worker",
        max_instances=1,  # защита от перекрытий при зависшем запуске
        coalesce=True,
    )
    # S72 W3 (TD-S64-W1) — sweeper job для reset stuck 'processing' rows.
    # Runs каждые 60s, threshold=lease_seconds (300s) — rows с expired
    # claimed_until reset'аются обратно в pending. Multi-leader
    # protection на стороне caller'а (S71 W3 leader election).
    _scheduler.add_job(
        sweep_stuck_once,
        trigger="interval",
        seconds=60,
        kwargs={"threshold_seconds": 300, "limit": 1000},
        id="outbox_sweeper",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info(
        "Outbox worker started (interval=%ds, batch=%d, sweeper=60s/300s)",
        interval_seconds,
        batch_size,
    )


async def stop_outbox_worker() -> None:
    """Graceful shutdown scheduler'а. Ждём текущий тик до N секунд."""
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
    logger.info("Outbox worker stopped")


async def sweep_stuck_once(*, threshold_seconds: int = 300, limit: int = 1000) -> int:
    """S72 W3 (TD-S64-W1) — одна итерация sweeper job'а.

    Wraps :func:`outbox_repo.reset_stuck_processing` для periodic
    invocation из APScheduler. Возвращает count reset rows (для
    logging / Prometheus gauge).

    **Зачем нужен sweeper**:
    Если worker claim'нул row (``status='processing'``,
    ``claimed_until=now+lease``) и умер между claim и
    ``mark_sent``/``mark_failed`` → row остаётся ``processing``
    навсегда, не обрабатывается другими worker'ами. Sweeper
    reset'нёт row обратно в ``pending`` после
    ``threshold_seconds`` (= lease TTL) — другой worker может
    пере-забрать.

    **Multi-leader protection**: sweeper SHOULD run ТОЛЬКО на
    1 инстансе (иначе дублирующие resets + overhead). Achieved
    via S71 W3 leader election — sweeper registration guard'ится
    на стороне caller'а (см. ``setup_infra/scheduler_leader.py``).
    Default ``threshold_seconds=300`` синхронизирован с
    ``claim_pending.lease_seconds`` default.
    """
    from src.backend.infrastructure.repositories import outbox as outbox_repo

    reset_count = await outbox_repo.reset_stuck_processing(
        threshold_seconds=threshold_seconds, limit=limit
    )
    if reset_count > 0:
        logger.info(
            "Outbox sweeper: reset %d stuck 'processing' rows (threshold=%ds)",
            reset_count,
            threshold_seconds,
        )
    return reset_count
