from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass  # cross-mixin / state attrs declared below

"""Реализация Invoker (W22.1 + W22.2/W22.3 + Этап B расширения).

Поддерживает шесть режимов:

* :attr:`InvocationMode.SYNC` — блокирующий вызов через ActionDispatcher.
* :attr:`InvocationMode.ASYNC_API` — fire-and-forget, результат
  публикуется в polling-канал (:class:`MemoryReplyChannel`); клиент
  опрашивает ``GET /api/v1/invocations/{id}``.
* :attr:`InvocationMode.BACKGROUND` — fire-and-forget без отслеживания
  результата.
* :attr:`InvocationMode.STREAMING` — action возвращает ``AsyncIterator``;
  каждый yield пушится в :class:`WsReplyChannel` для зарегистрированного
  invocation_id. Завершение stream'а — закрытие WS со стороны клиента.
* :attr:`InvocationMode.DEFERRED` — однократный отложенный запуск через
  APScheduler (``request.metadata['run_at']`` ISO-datetime или
  ``request.metadata['delay_seconds']``). Не durable — после рестарта
  сервиса задача не восстанавливается (memory jobstore).
* :attr:`InvocationMode.ASYNC_QUEUE` — публикация через Temporal-activity
  adapter (Sprint 8 K2 W1: TaskIQ полностью удалён).
"""

from datetime import UTC, datetime, timedelta

from src.backend.core.interfaces.invocation_reply import ReplyChannelKind
from src.backend.core.interfaces.invoker import (
    InvocationRequest,
    InvocationResponse,
    InvocationStatus,
)
from src.backend.core.logging import get_logger
from src.backend.core.utils.task_registry import get_task_registry

logger = get_logger("services.execution.invoker")


class DeferredMixin:
    """streaming + deferred (jobstore + scheduled) invocation для Invoker. S54 W3 extraction."""

    # State attrs + cross-method hints (S54 W3: class-level annotations for mypy MRO)
    _resolve_reply_registry: Any
    _dispatch: Any
    _build_context: Any
    _tasks: Any
    _resolve_channel: Any
    _track: Any
    _run_and_publish: Any
    _run_silent: Any
    _run_and_stream: Any
    _invoke_sync: Any
    _invoke_async_api: Any
    _invoke_background: Any

    _invoke_async_queue: Any
    _invoke_via_temporal_adapter: Any
    _run_temporal_activity: Any
    _run_deferred_job: Any  # method in temporal_mixin

    __slots__ = ()

    def _invoke_streaming(self, request: InvocationRequest) -> InvocationResponse:
        """Запускает streaming action; каждый yield пушится в WS-канал."""
        channel = self._resolve_channel(
            request.reply_channel or ReplyChannelKind.WS.value
        )
        if channel is None:
            return InvocationResponse(
                invocation_id=request.invocation_id,
                status=InvocationStatus.ERROR,
                error=(
                    "STREAMING требует доступного reply_channel (по умолчанию 'ws')"
                ),
                mode=request.mode,
            )
        task = get_task_registry().create_task(
            self._run_and_stream(request, channel),
            name=f"invoker:streaming:{request.invocation_id}",
        )
        self._track(task)
        return InvocationResponse(
            invocation_id=request.invocation_id,
            status=InvocationStatus.ACCEPTED,
            mode=request.mode,
        )

    def _invoke_deferred(self, request: InvocationRequest) -> InvocationResponse:
        """Планирует однократный запуск через APScheduler.

        Время старта определяется одним из полей ``request.metadata``:

        * ``run_at``: ISO-datetime (UTC, e.g. ``2026-04-30T12:00:00+00:00``);
        * ``delay_seconds``: число — относительная задержка в секундах.

        Хранилище задач — SQLAlchemy jobstore (durable: переживает рестарт
        сервиса). Если SQLAlchemy недоступен (например, dev_light без
        синхронного движка) — fallback на in-memory ``backup`` jobstore
        с предупреждением; в этом случае задача не durable.

        ``request.metadata['deferred_durable']`` может явно отключить
        durable-режим (``False`` → ``backup`` jobstore без warning).
        """
        run_at = self._resolve_deferred_run_at(request)
        if run_at is None:
            return InvocationResponse(
                invocation_id=request.invocation_id,
                status=InvocationStatus.ERROR,
                error=(
                    "DEFERRED требует metadata.run_at (ISO datetime) или "
                    "metadata.delay_seconds (число)"
                ),
                mode=request.mode,
                metadata=dict(request.metadata),
            )

        try:
            from apscheduler.triggers.date import DateTrigger

            from src.backend.core.di.providers import get_scheduler_manager_provider

            scheduler_manager = get_scheduler_manager_provider()
        except Exception as exc:
            logger.exception("DEFERRED: APScheduler недоступен")
            return InvocationResponse(
                invocation_id=request.invocation_id,
                status=InvocationStatus.ERROR,
                error=f"APScheduler unavailable: {exc}",
                mode=request.mode,
                metadata=dict(request.metadata),
            )

        jobstore, durable = self._select_deferred_jobstore(request)
        job_id = f"deferred_invocation_{request.invocation_id}"
        try:
            scheduler_manager.scheduler.add_job(
                _run_deferred_job,
                trigger=DateTrigger(run_date=run_at),
                kwargs={"request": request},
                id=job_id,
                replace_existing=False,
                executor="async",
                jobstore=jobstore,
            )
        except Exception as exc:
            # SQLAlchemy недоступен (dev_light без sync engine) или
            # request не picklable — fallback на memory-jobstore.
            if jobstore != "backup":
                logger.warning(
                    "DEFERRED: durable jobstore недоступен (%s); "
                    "fallback на memory (id=%s)",
                    exc,
                    request.invocation_id,
                )
                scheduler_manager.scheduler.add_job(
                    _run_deferred_job,
                    trigger=DateTrigger(run_date=run_at),
                    kwargs={"request": request},
                    id=job_id,
                    replace_existing=False,
                    executor="async",
                    jobstore="backup",
                )
                durable = False
            else:
                raise
        meta = dict(request.metadata)
        meta["scheduled_at"] = run_at.isoformat()
        meta["scheduler_job_id"] = job_id
        meta["deferred_durable"] = durable
        return InvocationResponse(
            invocation_id=request.invocation_id,
            status=InvocationStatus.ACCEPTED,
            mode=request.mode,
            metadata=meta,
        )

    @staticmethod
    def _select_deferred_jobstore(request: InvocationRequest) -> tuple[str, bool]:
        """Возвращает имя jobstore и флаг durability.

        ``metadata['deferred_durable']``:

        * ``True`` (default) → SQLAlchemy ``default`` jobstore;
        * ``False`` → memory ``backup`` jobstore (для тестов/short-lived).
        """
        durable_raw = (request.metadata or {}).get("deferred_durable", True)
        durable = bool(durable_raw)
        return ("default" if durable else "backup", durable)

    def _resolve_deferred_run_at(self, request: InvocationRequest) -> datetime | None:
        meta = request.metadata or {}
        run_at_raw = meta.get("run_at")
        if isinstance(run_at_raw, datetime):
            return run_at_raw if run_at_raw.tzinfo else run_at_raw.replace(tzinfo=UTC)
        if isinstance(run_at_raw, str) and run_at_raw:
            try:
                parsed = datetime.fromisoformat(run_at_raw)
            except ValueError:
                logger.warning("DEFERRED: невалидный run_at=%r", run_at_raw)
                return None
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

        delay_raw = meta.get("delay_seconds")
        if isinstance(delay_raw, (int, float)) and delay_raw >= 0:
            return datetime.now(UTC) + timedelta(seconds=float(delay_raw))
        return None
