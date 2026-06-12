"""S71 W2 — extracted из ``setup_infra.py`` (orphan file).

S64 W2 — distributed leader election для APScheduler.
TTL=300s — leader-renewal window (lock НЕ auto-extends, eventual
leadership shift при cluster instability; документировано в ADR-0087).

Используется в :func:`perform_infrastructure_operation` startup-фазе
для multi-instance safety (только 1 инстанс становится scheduler leader'ом).
"""

from __future__ import annotations

from src.backend.infrastructure.logging.factory import get_logger

app_logger = get_logger("application")

# S64 W2: distributed leader election для APScheduler.
# TTL=300s — leader-renewal window (lock НЕ auto-extends, eventual
# leadership shift при cluster instability; документировано в ADR-0087).
_SCHEDULER_LEADER_LOCK_TTL_S: int = 300
_SCHEDULER_LEADER_LOCK_KEY: str = "scheduler:leader:v1"
# Module-level state: был ли этот инстанс выбран leader'ом.
# Используется в stop() для symmetric shutdown — non-leader не должен
# вызывать scheduler.stop() (APScheduler бросает SchedulerNotRunningError).
_scheduler_leader_acquired: bool = False


async def _start_scheduler_with_leader_election() -> None:
    """S64 W2 — distributed leader election для APScheduler (multi-instance safe).

    Алгоритм:

    1. ``distributed_lock("scheduler:leader:v1", ttl_seconds=300,
       blocking_timeout=0)`` — non-blocking try-lock.
    2. Если lock acquired → ``await get_scheduler_manager().start()`` →
       этот инстанс становится leader'ом, все cron/interval jobs
       выполняются ТОЛЬКО на нём.
    3. Если lock NOT acquired → log "skip" + return. APScheduler на
       этом инстансе НЕ стартует (no orphan jobs).

    **Trade-off** (задокументировано в ADR-0087):

    * Lock TTL=300s (5 min) — lock НЕ auto-extends. Если leader
      instance живёт > 5 min без касания lock'а, lock expires и
      другой instance может стать leader. Eventual-consistency
      shift при cluster instability. Лучше: leader dies → 5 min
      cron stall → новый leader берёт (acceptable для cron-уровня).
    * Реализация auto-extend (heartbeat task) — S65+, требует
      lifecycle-интеграции (start/stop heartbeat).
    * ``scheduler.max_instances=1`` (per-job) защищает внутри
      одного APScheduler; leader election — между инстансами.

    Сценарии:

    * 1 инстанс в кластере → всегда leader.
    * 2+ инстанса → ровно 1 leader (остальные skip).
    * Leader упал → через ≤5 min другой инстанс возьмёт lock.
    * Redis недоступен → ``RedisLock.acquire()`` возвращает ``True``
      (fail-open, см. infra/clients/storage/redis_lock.py:48) →
      ВСЕ инстансы стартуют scheduler (W2 trade-off, см. G6 в
      аудите S64). Prod fix — добавить fail-closed в RedisLock.
    """
    global _scheduler_leader_acquired
    from src.backend.infrastructure.clients.storage.redis_lock import (
        distributed_lock,
    )

    async with distributed_lock(
        _SCHEDULER_LEADER_LOCK_KEY,
        ttl_seconds=_SCHEDULER_LEADER_LOCK_TTL_S,
        blocking_timeout=0,
    ) as acquired:
        if not acquired:
            app_logger.info(
                "Scheduler leader election: lock NOT acquired — another instance "
                "holds it. Skipping scheduler.start() on this instance.",
                extra={
                    "lock_key": _SCHEDULER_LEADER_LOCK_KEY,
                    "ttl_seconds": _SCHEDULER_LEADER_LOCK_TTL_S,
                },
            )
            return
        _scheduler_leader_acquired = True
        app_logger.info(
            "Scheduler leader election: lock acquired — this instance is "
            "scheduler leader. Starting scheduler.",
            extra={
                "lock_key": _SCHEDULER_LEADER_LOCK_KEY,
                "ttl_seconds": _SCHEDULER_LEADER_LOCK_TTL_S,
            },
        )
        from src.backend.infrastructure.scheduler.scheduler_manager import (
            get_scheduler_manager,
        )

        await get_scheduler_manager().start()


async def _stop_scheduler_if_leader() -> None:
    """S64 W2 — symmetric shutdown: только leader вызывает ``scheduler.stop()``.

    APScheduler бросает :class:`apscheduler.schedulers.SchedulerNotRunningError`
    при попытке ``stop()`` на уже остановленном (или никогда не
    стартовавшем) scheduler'е. Non-leader инстансы никогда не
    стартовали scheduler → должны skip stop.
    """
    global _scheduler_leader_acquired
    if not _scheduler_leader_acquired:
        app_logger.info(
            "Scheduler leader election: this instance was NOT leader — "
            "skipping scheduler.stop()."
        )
        return
    app_logger.info("Scheduler leader election: stopping scheduler (was leader).")
    from src.backend.infrastructure.scheduler.scheduler_manager import (
        get_scheduler_manager,
    )

    await get_scheduler_manager().stop()
    _scheduler_leader_acquired = False


__all__ = (
    "_start_scheduler_with_leader_election",
    "_stop_scheduler_if_leader",
    "_SCHEDULER_LEADER_LOCK_KEY",
    "_SCHEDULER_LEADER_LOCK_TTL_S",
)
