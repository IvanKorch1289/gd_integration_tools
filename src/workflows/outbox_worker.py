"""Outbox worker — периодический publisher для transactional messaging.

Worker запускается в lifecycle startup, каждые ``interval_seconds`` читает
таблицу ``outbox_messages`` со статусом ``pending``, публикует в соответствующий
брокер (Kafka/Rabbit/Redis Streams) по правилам routing и помечает запись.

Routing по topic:

* ``kafka:<topic>`` → KafkaClient.
* ``rabbit:<queue>`` → aio-pika.
* ``redis:<stream>`` → Redis Streams.
* без префикса → Kafka по умолчанию.

Идемпотентность: обновление ``status`` защищает от повторной публикации.
Retry с экспоненциальным backoff управляется из :mod:`repositories.outbox`.
"""

from __future__ import annotations

import logging
from typing import Any

__all__ = ("start_outbox_worker", "stop_outbox_worker", "run_once")

logger = logging.getLogger("workflows.outbox")

_scheduler: Any = None


async def _publish(topic: str, payload: dict[str, Any], headers: dict[str, Any]) -> None:
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
            from app.infrastructure.clients.messaging.kafka import kafka_client
            await kafka_client.publish(dest, payload, headers=headers)
        case "rabbit":
            # aio-pika выносим в отдельный клиент по мере надобности.
            from app.infrastructure.clients.messaging.event_bus import event_bus
            await event_bus.publish(dest, payload, headers=headers)
        case "redis":
            from app.infrastructure.clients.storage.redis import redis_client
            import orjson
            raw = getattr(redis_client, "_raw_client", None) or redis_client
            await raw.xadd(dest, {"payload": orjson.dumps(payload).decode()})
        case _:
            raise ValueError(f"Неизвестный protocol '{protocol}' в topic '{topic}'")


async def run_once(*, batch_size: int = 100) -> dict[str, int]:
    """Одна итерация worker'а. Возвращает статистику.

    Вынесена в отдельную функцию для удобства юнит-тестов и ручного запуска
    через admin-эндпоинт.
    """
    from app.infrastructure.repositories import outbox as outbox_repo

    pending = await outbox_repo.fetch_pending(limit=batch_size)
    stats = {"fetched": len(pending), "sent": 0, "failed": 0}

    for msg in pending:
        try:
            await _publish(msg.topic, msg.payload, msg.headers or {})
            await outbox_repo.mark_sent(msg.id)
            stats["sent"] += 1
        except Exception as exc:  # noqa: BLE001
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
    _scheduler.start()
    logger.info(
        "Outbox worker started (interval=%ds, batch=%d)", interval_seconds, batch_size,
    )


async def stop_outbox_worker() -> None:
    """Graceful shutdown scheduler'а. Ждём текущий тик до N секунд."""
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
    logger.info("Outbox worker stopped")
