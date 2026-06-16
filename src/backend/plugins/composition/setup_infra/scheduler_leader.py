"""S71 W2 — extracted из ``setup_infra.py`` (orphan file).

S64 W2 — distributed leader election для APScheduler.
S71 W3 — TD-S64-W2 closure: lock auto-extend через background heartbeat.

Используется в :func:`perform_infrastructure_operation` startup-фазе
для multi-instance safety (только 1 инстанс становится scheduler leader'ом).
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.backend.core.logging import get_logger

app_logger = get_logger("application")

# S64 W2: distributed leader election для APScheduler.
# TTL=300s (5 min) — leader-renewal window.
# S71 W3: TTL auto-extends every TTL/5=60s через background heartbeat task
# (TD-S64-W2 closure). Если leader dies → heartbeat dies → TTL expires
# через ≤60s → другой instance берёт lock (best-case 60s downtime,
# worst-case 5 min if lock acquired, no refresh).
_SCHEDULER_LEADER_LOCK_TTL_S: int = 300
_SCHEDULER_LEADER_LOCK_KEY: str = "scheduler:leader:v1"
# Heartbeat interval = TTL / 5. 5 renewals per TTL window — если 1
# heartbeat fail, остальные 4 успеют.
_SCHEDULER_LEADER_HEARTBEAT_S: float = _SCHEDULER_LEADER_LOCK_TTL_S / 5

# Module-level state: был ли этот инстанс выбран leader'ом.
# Используется в stop() для symmetric shutdown — non-leader не должен
# вызывать scheduler.stop() (APScheduler бросает SchedulerNotRunningError).
_scheduler_leader_acquired: bool = False
_scheduler_heartbeat_task: asyncio.Task[None] | None = None
_scheduler_lock_handle: Any = None  # RedisLock instance для extend()


async def _start_scheduler_with_leader_election() -> None:
    """S64 W2 — distributed leader election для APScheduler (multi-instance safe).

    S71 W3 update: lock удерживается **на всё время работы scheduler'а**
    (не только на время ``start()``) — manual ``acquire()`` + background
    ``extend()`` heartbeat. ``distributed_lock`` context manager НЕ
    подходит (release при выходе из ``async with``).

    Алгоритм:

    1. ``RedisLock.acquire(blocking_timeout=0)`` — non-blocking try-lock.
    2. Если lock acquired → ``await get_scheduler_manager().start()`` →
       стартует background ``_scheduler_heartbeat_loop()`` (extend каждые
       60s) → этот инстанс становится leader'ом, все cron/interval jobs
       выполняются ТОЛЬКО на нём.
    3. Если lock NOT acquired → log "skip" + return. APScheduler на
       этом инстансе НЕ стартует (no orphan jobs).

    **Auto-extend гарантии** (S71 W3):

    * Heartbeat interval = TTL/5 = 60s. Lock TTL = 300s.
    * До 4 consecutive heartbeat failures tolerated (последняя renewal
      была < 60s назад, остаётся ~240s в окне TTL).
    * Если leader dies → heartbeat dies → ≤60s до TTL expiry → другой
      instance берёт lock через ``_scheduler_heartbeat_loop()`` recovery
      в ``_stop_scheduler_if_leader()``.
    * Trade-off: race window ≤60s между leader death и detection
      (acceptable для cron-уровня, не для in-flight requests).

    **Backward compat** (S64 W2 design): если Redis недоступен,
    ``RedisLock.acquire()`` возвращает ``True`` (fail-open, см.
    infra/clients/storage/redis_lock.py:48) → ВСЕ инстансы стартуют
    scheduler. Prod fix (S65+) — fail-closed в RedisLock.
    """
    global _scheduler_leader_acquired, _scheduler_heartbeat_task
    global _scheduler_lock_handle

    from src.backend.infrastructure.clients.storage.redis_lock import RedisLock

    lock = RedisLock(
        _SCHEDULER_LEADER_LOCK_KEY, ttl_seconds=_SCHEDULER_LEADER_LOCK_TTL_S
    )
    acquired = await lock.acquire(blocking_timeout=0)
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
    _scheduler_lock_handle = lock
    app_logger.info(
        "Scheduler leader election: lock acquired — this instance is "
        "scheduler leader. Starting scheduler + heartbeat.",
        extra={
            "lock_key": _SCHEDULER_LEADER_LOCK_KEY,
            "ttl_seconds": _SCHEDULER_LEADER_LOCK_TTL_S,
            "heartbeat_seconds": _SCHEDULER_LEADER_HEARTBEAT_S,
        },
    )
    from src.backend.infrastructure.scheduler.scheduler_manager import (
        get_scheduler_manager,
    )

    # S71 W3: start heartbeat BEFORE scheduler, чтобы lock не expired
    # до того, как scheduler начнёт работать.
    _scheduler_heartbeat_task = asyncio.create_task(
        _scheduler_heartbeat_loop(), name="scheduler-leader-heartbeat"
    )
    await get_scheduler_manager().start()


async def _scheduler_heartbeat_loop() -> None:
    """S71 W3 — background task, renews leader lock каждые TTL/5 секунд.

    Lifecycle: создаётся в :func:`_start_scheduler_with_leader_election`
    (только если этот инстанс — leader), отменяется в
    :func:`_stop_scheduler_if_leader`.

    На каждой итерации:
    1. ``asyncio.sleep(heartbeat_seconds)`` — пауза 60s.
    2. ``lock.extend(additional_seconds=ttl)`` — Redis ``PEXPIRE`` на
       тот же TTL (300s). Если возвращает ``False`` (lock уже не наш) →
       log error + cancel scheduler (через ``_scheduler_leader_acquired = False``
      , который ``_stop_scheduler_if_leader`` подхватит при shutdown).
    """
    app_logger.info(
        "Scheduler heartbeat loop started (interval=%.1fs, ttl=%ds)",
        _SCHEDULER_LEADER_HEARTBEAT_S,
        _SCHEDULER_LEADER_LOCK_TTL_S,
    )
    try:
        while True:
            await asyncio.sleep(_SCHEDULER_LEADER_HEARTBEAT_S)
            if _scheduler_lock_handle is None:
                app_logger.warning("Scheduler heartbeat: lock handle is None, stopping")
                break
            try:
                extended = await _scheduler_lock_handle.extend(
                    additional_seconds=_SCHEDULER_LEADER_LOCK_TTL_S
                )
                if not extended:
                    app_logger.error(
                        "Scheduler heartbeat: extend returned False — lock "
                        "NO LONGER owned by this instance! Shutting down "
                        "scheduler to avoid duplicate cron execution."
                    )
                    # Mark leader status как потерянный, чтобы
                    # _stop_scheduler_if_leader сразу понял.
                    global _scheduler_leader_acquired
                    _scheduler_leader_acquired = False
                    break
                app_logger.debug("Scheduler heartbeat: lock extended OK")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                # Transient Redis error — log + retry next tick.
                # До 4 consecutive failures tolerated.
                app_logger.warning(
                    "Scheduler heartbeat: extend failed (will retry): %s", exc
                )
    except asyncio.CancelledError:
        app_logger.info("Scheduler heartbeat loop cancelled (shutdown)")
        raise


async def _stop_scheduler_if_leader() -> None:
    """S64 W2 — symmetric shutdown: только leader вызывает ``scheduler.stop()``.

    APScheduler бросает :class:`apscheduler.schedulers.SchedulerNotRunningError`
    при попытке ``stop()`` на уже остановленном (или никогда не
    стартовавшем) scheduler'е. Non-leader инстансы никогда не
    стартовали scheduler → должны skip stop.

    S71 W3 update: отменяет heartbeat task и release'ит lock (если был
    acquired). Lock release — best-effort, не raise на shutdown.
    """
    global _scheduler_leader_acquired, _scheduler_heartbeat_task
    global _scheduler_lock_handle

    # 1. Cancel heartbeat first (stop renewing lock).
    if _scheduler_heartbeat_task is not None and not _scheduler_heartbeat_task.done():
        _scheduler_heartbeat_task.cancel()
        try:
            await _scheduler_heartbeat_task
        except asyncio.CancelledError:
            pass
    _scheduler_heartbeat_task = None

    # 2. If not leader, nothing more to do.
    if not _scheduler_leader_acquired:
        app_logger.info(
            "Scheduler leader election: this instance was NOT leader — "
            "skipping scheduler.stop()."
        )
        _scheduler_lock_handle = None
        return

    # 3. Leader path: stop scheduler + release lock.
    app_logger.info("Scheduler leader election: stopping scheduler (was leader).")
    from src.backend.infrastructure.scheduler.scheduler_manager import (
        get_scheduler_manager,
    )

    try:
        await get_scheduler_manager().stop()
    except Exception as exc:  # noqa: BLE001
        app_logger.warning("scheduler.stop() raised (continuing): %s", exc)
    _scheduler_leader_acquired = False

    # 4. Release lock (best-effort).
    if _scheduler_lock_handle is not None:
        try:
            await _scheduler_lock_handle.release()
        except Exception as exc:  # noqa: BLE001
            app_logger.warning("lock release failed (best-effort): %s", exc)
        _scheduler_lock_handle = None


__all__ = (
    "_start_scheduler_with_leader_election",
    "_stop_scheduler_if_leader",
    "_scheduler_heartbeat_loop",
    "_SCHEDULER_LEADER_LOCK_KEY",
    "_SCHEDULER_LEADER_LOCK_TTL_S",
    "_SCHEDULER_LEADER_HEARTBEAT_S",
)
