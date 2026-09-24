"""BackfillService — materialize пропущенных запусков (ADR-0346, Option A+C).

Материализует тики расписания за окно как run-history строки и (при
``catchup=True``) исполняет их через ``run_pending``. Лимит окна — защита
от runaway-backfill при первом старте с catchup.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from apscheduler.triggers.base import BaseTrigger

from src.backend.services.scheduler.run_history import (
    STATUS_MISSED,
    STATUS_PENDING,
    RunHistoryStore,
)

DEFAULT_MAX_WINDOW_DAYS = 31
_DEFAULT_MAX_TICKS = 1000


@dataclass(slots=True)
class BackfillReport:
    """Итог materialize-фазы (без исполнения)."""

    ticks_in_window: int
    materialized: int
    skipped_existing: int
    status: str  # "pending" (catchup) | "missed" (учёт)


def compute_missed_ticks(
    trigger: BaseTrigger,
    date_from: datetime,
    date_to: datetime,
    *,
    max_ticks: int = _DEFAULT_MAX_TICKS,
) -> list[datetime]:
    """Перечислить тики расписания в интервале [date_from, date_to].

    Args:
        trigger: APScheduler-триггер (cron/interval/date).
        date_from: начало окна (inclusive по первому fire после).
        date_to: конец окна (inclusive).
        max_ticks: защита от бесконечных интервалов (default 1000).

    Returns:
        Хронологический список тиков. Пустой, если окно не содержит огней.

    Raises:
        ValueError: если тиков больше ``max_ticks``.
    """
    first = trigger.get_next_fire_time(None, date_from)
    if first is None or first > date_to:
        return []
    ticks = [first]
    while True:
        if len(ticks) > max_ticks:
            raise ValueError(
                f"Интервал {date_from}..{date_to} даёт > {max_ticks} тиков — "
                f"сузьте окно (защита от runaway-backfill)"
            )
        nxt = trigger.get_next_fire_time(ticks[-1], date_to)
        if nxt is None or nxt > date_to:
            break
        ticks.append(nxt)
    return ticks


class BackfillService:
    """Materialize + исполнение пропущенных запусков (ADR-0346)."""

    def __init__(
        self,
        store: RunHistoryStore,
        *,
        max_window_days: int = DEFAULT_MAX_WINDOW_DAYS,
    ) -> None:
        """Инициализация.

        Args:
            store: хранилище run-history.
            max_window_days: максимум окна backfill (защита от runaway).
        """
        self._store = store
        self._max_window = timedelta(days=max_window_days)

    async def materialize_window(
        self,
        *,
        job_id: str,
        trigger: BaseTrigger,
        date_from: datetime,
        date_to: datetime,
        tenant_id: str | None = None,
        catchup: bool = True,
    ) -> BackfillReport:
        """Материализовать тики окна как run-history строки.

        Args:
            job_id: идентификатор job'а.
            trigger: APScheduler-триггер job'а.
            date_from/date_to: окно (date_to >= date_from).
            tenant_id: тенант-владелец job'а.
            catchup: True → тики до ``now`` materialize как ``pending``
                (будут исполнены ``run_pending``); False → ``missed``
                (только учёт, исполнение не планируется).

        Returns:
            BackfillReport с числами по окну.
        """
        if date_to < date_from:
            raise ValueError("date_to < date_from")
        if date_to - date_from > self._max_window:
            raise ValueError(
                f"Окно больше {self._max_window.days} дней — сузьте "
                f"(max_window_days={self._max_window.days})"
            )

        ticks = compute_missed_ticks(trigger, date_from, date_to)
        now = datetime.now(tz=date_from.tzinfo or date_to.tzinfo)
        materialize_status = STATUS_PENDING if catchup else STATUS_MISSED

        created = await self._store.materialize(
            job_id, ticks, status=materialize_status, tenant_id=tenant_id
        )
        return BackfillReport(
            ticks_in_window=len(ticks),
            materialized=created,
            skipped_existing=len(ticks) - created,
            status=materialize_status,
        )

    async def run_catchup(
        self,
        *,
        job_id: str,
        executor: Any,
        limit: int = 100,
    ) -> tuple[int, int]:
        """Исполнить pending-тики (catchup) через executor.

        Args:
            job_id: идентификатор job'а.
            executor: async-коллбэк ``async (scheduled_for) -> None``.
            limit: backpressure на один вызов.

        Returns:
            (done, failed).
        """
        return await self._store.run_pending(job_id, executor, limit=limit)
