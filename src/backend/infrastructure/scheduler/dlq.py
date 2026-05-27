"""APScheduler EVENT_JOB_ERROR → DLQ writer (Sprint 21 W4, G-09 closure).

Источник: PLAN.md V22.2 §4 + ADR-NEW-13 (RPACallPolicy) ассоциированно.

Назначение:
    Захватывает все APScheduler ``EVENT_JOB_ERROR`` события и пишет их в
    :class:`DLQWriter` с ``kind='scheduler_job'``. Отдельный in-memory
    rotating buffer ``SchedulerDLQStore`` хранит последние ``N`` failed jobs
    для admin REST endpoint (``/admin/scheduler/dlq``) — list/retry/delete.

Структура failed job entry:
    * ``id`` — UUID записи (для retry/delete API).
    * ``job_id`` — APScheduler job_id.
    * ``exception`` — repr(exc).
    * ``traceback`` — str(traceback) (для admin debug).
    * ``scheduled_at`` — оригинальное время schedule.
    * ``failed_at`` — UTC момент failure.
    * ``retry_count`` — сколько раз делался retry через admin (default 0).

Feature-flag:
    ``scheduler_dlq_enabled`` (W0) — default-OFF. При False listener
    не регистрируется (legacy logging-only behaviour).

См. также:
    * :func:`attach_scheduler_metrics` в observability.py.
    * :mod:`src.backend.core.messaging.dlq` для DLQEnvelope.
"""

from __future__ import annotations

import logging
import threading
import traceback
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from src.backend.core.config.features import feature_flags
from src.backend.core.messaging.dlq import DLQEnvelope, DLQReason, DLQWriter

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

__all__ = (
    "SchedulerDLQStore",
    "SchedulerDLQEntry",
    "attach_scheduler_dlq",
    "get_scheduler_dlq_store",
    "set_scheduler_dlq_store",
)

_logger = logging.getLogger("infrastructure.scheduler.dlq")


class SchedulerDLQEntry:
    """In-memory запись failed scheduler job (для admin REST API).

    Минимальная иммутабельная dataclass-like структура; mutable только
    ``retry_count`` через :meth:`mark_retried`.
    """

    __slots__ = (
        "id",
        "job_id",
        "exception",
        "traceback_text",
        "scheduled_at",
        "failed_at",
        "retry_count",
    )

    def __init__(
        self,
        *,
        job_id: str,
        exception: str,
        traceback_text: str,
        scheduled_at: datetime | None,
        failed_at: datetime,
    ) -> None:
        self.id = str(uuid.uuid4())
        self.job_id = job_id
        self.exception = exception
        self.traceback_text = traceback_text
        self.scheduled_at = scheduled_at
        self.failed_at = failed_at
        self.retry_count = 0

    def mark_retried(self) -> None:
        """Инкрементирует счётчик ручных retry через admin endpoint."""
        self.retry_count += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "job_id": self.job_id,
            "exception": self.exception,
            "traceback": self.traceback_text,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "failed_at": self.failed_at.isoformat(),
            "retry_count": self.retry_count,
        }


class SchedulerDLQStore:
    """In-memory ring buffer для failed scheduler jobs.

    Thread-safe (защищён ``threading.Lock``); APScheduler listener вызывается
    из event-thread.

    Args:
        capacity: максимум хранимых записей (default 256).
    """

    def __init__(self, capacity: int = 256) -> None:
        if capacity < 1:
            raise ValueError("capacity должен быть >= 1")
        self._capacity = capacity
        self._entries: OrderedDict[str, SchedulerDLQEntry] = OrderedDict()
        self._lock = threading.Lock()

    def add(self, entry: SchedulerDLQEntry) -> None:
        """Добавляет запись; вытесняет самую старую при превышении capacity."""
        with self._lock:
            self._entries[entry.id] = entry
            while len(self._entries) > self._capacity:
                self._entries.popitem(last=False)

    def list(self, limit: int | None = None) -> list[SchedulerDLQEntry]:
        """Возвращает entries (новейшие сверху)."""
        with self._lock:
            items = list(reversed(self._entries.values()))
        if limit is not None:
            items = items[:limit]
        return items

    def get(self, entry_id: str) -> SchedulerDLQEntry | None:
        with self._lock:
            return self._entries.get(entry_id)

    def delete(self, entry_id: str) -> bool:
        with self._lock:
            return self._entries.pop(entry_id, None) is not None

    def size(self) -> int:
        with self._lock:
            return len(self._entries)


# Module-level singleton store + DLQWriter slot
_default_store: SchedulerDLQStore | None = None


def get_scheduler_dlq_store() -> SchedulerDLQStore | None:
    """Возвращает дефолтный store (или None если не сконфигурирован)."""
    return _default_store


def set_scheduler_dlq_store(store: SchedulerDLQStore | None) -> None:
    """Устанавливает дефолтный store (вызывается в lifespan)."""
    global _default_store
    _default_store = store


def attach_scheduler_dlq(
    scheduler: "AsyncIOScheduler",
    *,
    writer: DLQWriter | None = None,
    store: SchedulerDLQStore | None = None,
) -> SchedulerDLQStore | None:
    """Регистрирует ``EVENT_JOB_ERROR`` listener для DLQ.

    Args:
        scheduler: запущенный AsyncIOScheduler.
        writer: опц. ``DLQWriter`` для durable backend (Postgres/Kafka).
            При ``None`` запись только в in-memory store.
        store: опц. SchedulerDLQStore; при ``None`` создаётся новый и
            устанавливается module singleton через :func:`set_scheduler_dlq_store`.

    Returns:
        Подключённый store (или None если feature-flag OFF).
    """
    if not feature_flags.scheduler_dlq_enabled:
        _logger.debug("scheduler_dlq disabled by feature-flag — no-op")
        return None

    if store is None:
        store = SchedulerDLQStore()
        set_scheduler_dlq_store(store)

    try:
        from apscheduler.events import EVENT_JOB_ERROR
    except ImportError:
        _logger.warning(
            "attach_scheduler_dlq: apscheduler not installed — no-op"
        )
        return store

    def _on_job_error(event: Any) -> None:
        try:
            exc = getattr(event, "exception", None)
            tb_obj = getattr(event, "traceback", None)
            tb_text = (
                "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
                if exc is not None
                else (str(tb_obj) if tb_obj else "")
            )
            entry = SchedulerDLQEntry(
                job_id=str(getattr(event, "job_id", "unknown")),
                exception=repr(exc) if exc is not None else "Unknown",
                traceback_text=tb_text,
                scheduled_at=getattr(event, "scheduled_run_time", None),
                failed_at=datetime.now(timezone.utc),
            )
            store.add(entry)

            if writer is not None:
                envelope = DLQEnvelope(
                    transport="scheduler_job",
                    error_class=type(exc).__name__ if exc is not None else "Unknown",
                    error_message=str(exc) if exc is not None else "",
                    reason=DLQReason.UNEXPECTED,
                    metadata={
                        "job_id": entry.job_id,
                        "scheduled_at": (
                            entry.scheduled_at.isoformat()
                            if entry.scheduled_at
                            else None
                        ),
                    },
                )
                # Schedule async write — listener вызывается sync;
                # writer.write() — coroutine, поэтому fire-and-forget через
                # TaskRegistry (если есть running loop) для leak-prevention.
                import asyncio

                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    _logger.warning(
                        "DLQWriter.write skipped — no running loop in listener"
                    )
                else:
                    from src.backend.core.utils.task_registry import (
                        get_task_registry,
                    )

                    get_task_registry().create_task(
                        writer.write(envelope),
                        name="scheduler-dlq-write",
                        deadline_seconds=10.0,
                    )
        except Exception as _:  # noqa: BLE001
            _logger.exception("scheduler DLQ listener failed")

    scheduler.add_listener(_on_job_error, EVENT_JOB_ERROR)
    _logger.info(
        "Scheduler DLQ listener attached (capacity=%s, writer=%s)",
        store._capacity,
        "set" if writer is not None else "none",
    )
    return store
