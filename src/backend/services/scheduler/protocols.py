"""Scheduler Protocol abstractions — DI contracts.

v6 / 25.09 audit: «Инъецировать в SchedulerFacade существующий
SchedulerBackend Protocol и новый RunHistoryStoreProtocol; удалить
service locator внутри методов».

Этот модуль — точка расширения для тестов и альтернативных backend'ов
(in-memory mock, Temporal и т.п.). Каждый Protocol соответствует
конкретному public API существующих классов, но объявлен отдельно чтобы:

1. Устранить circular import (SchedulerFacade ↔ RunHistoryStore ↔
   BackfillService) через type-only references;
2. Разрешить подмену через mock без subclassing;
3. Зафиксировать surface contract для последующих refactor'ов
   (например Temporal migration).

Backwards compatibility: concrete classes (``SchedulerManager`` через
``SchedulerBackend`` Protocol из ``core/interfaces/scheduler.py``,
``RunHistoryStore`` из ``run_history.py``) имплементируют соответствующие
Protocol'ы structurally (Python Protocol — duck typing).

Per ADR-0346 + 25.09 P1 fix: facade methods MUST use injected dependencies
instead of service locator (``get_scheduler_manager()``, ``RunHistoryStore(...)``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

__all__ = ("JobRegistrationResult", "RunHistoryStoreProtocol")


@runtime_checkable
class RunHistoryStoreProtocol(Protocol):
    """Контракт хранилища истории запусков scheduler (ADR-0346).

    Используется :class:`SchedulerFacade` для backfill/catchup
    materialization и ``run_pending`` execution loop.

    Mirrors concrete :class:`src.backend.services.scheduler.run_history.RunHistoryStore`
    interface — Protocol structural match (Python duck typing).
    """

    async def materialize(
        self,
        job_id: str,
        ticks: list[datetime],
        *,
        status: str = "missed",
        tenant_id: str | None = None,
    ) -> int:
        """Записать тики в историю (idempotent).

        Returns:
            Число фактически созданных строк (existing skipped).
        """

    async def pending(self, job_id: str, limit: int = 100) -> list[datetime]:
        """Список pending тиков для job'а (старые → новые)."""

    async def last_scheduled(self, job_id: str) -> datetime | None:
        """Время последнего scheduled тика (``None`` если не было)."""

    async def mark(
        self,
        job_id: str,
        scheduled_at: datetime,
        *,
        status: str,
        attempts: int = 1,
        last_error: str | None = None,
    ) -> None:
        """Обновить статус тика (running/done/failed/dead)."""

    async def run_pending(
        self, job_id: str, executor: Any, *, limit: int = 100, attempts: int = 1
    ) -> int:
        """Исполнить pending тики через executor (claim → run → mark).

        Returns:
            Число исполненных тиков.
        """


# Re-export JobRegistrationResult из core.interfaces если есть, иначе
# объявляем здесь как TypedDict (25.09 audit: «Заменить dict[str, Any]
# результата регистрации на typed JobRegistrationResult»).
# TypedDict сохраняет dict-style access (``result["registered"]``) +
# добавляет type hints для mypy/IDE. Это минимальное изменение для
# backward compat с существующими callers и tests.
try:
    from src.backend.core.interfaces.scheduler import (  # type: ignore[attr-defined]
        JobRegistrationResult,  # noqa: F401
    )
except ImportError:
    from typing import TypedDict

    class JobRegistrationResult(TypedDict, total=False):  # type: ignore[no-redef]
        """Typed result of ``SchedulerFacade.add_job`` (25.09 audit).

        Per v6: «Заменить dict[str, Any] результата регистрации на
        typed JobRegistrationResult».

        TypedDict — это dict[str, Any] на runtime с type hints для
        static checking. Сохраняет backward compat с callers
        (``result["registered"]``, ``.get("error")`` и т.п.).

        Attributes:
            job_id: ID зарегистрированной задачи.
            registered: ``True`` если APScheduler registration OK.
            history_materialized: ``True`` если catchup-материализация
                прошла успешно.
            catchup_scheduled: Синоним ``history_materialized`` (legacy
                field name, оставлен для backward compat).
            ticks_in_window: Число тиков в catchup-окне.
            error: Текст ошибки или ``None``.
        """

        job_id: str
        registered: bool
        history_materialized: bool
        catchup_scheduled: bool
        ticks_in_window: int
        error: str | None
