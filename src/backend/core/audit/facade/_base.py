"""S107 W3 — ``core.audit.facade._base``: canonical audit emit + safe wrapper.

Per-domain helpers (S106 W2 Path A) живут в отдельных модулях пакета
``core.audit.facade``: ``authorization``, ``waf``, ``capability``,
``secrets``, ``ai``, ``banking``. Все они делегируют на
``emit_audit`` (здесь).

References:
* ADR-0187 (S103 closure)
* ``docs/migration/audit-emit-deprecation.md`` (Path A/B/C/D guide)
* ``tools/check_audit_deprecation.py`` (S105 W2 regression guard)

"""

from __future__ import annotations

import asyncio
import atexit
import contextvars
import threading
from collections.abc import Coroutine
from concurrent.futures import Future
from typing import Any

from src.backend.core.audit.facade.audit_service import get_unified_audit_service
from src.backend.core.logging import get_logger
from src.backend.core.utils.task_registry import get_task_registry

__all__ = ("emit_audit", "emit_audit_safe")

_logger = get_logger("core.audit.facade.base")

# ─────────────── sync-контекст: собственный event loop в фоновом потоке ───────────────
#
# ADR-0392: раньше в sync-контексте корутина закрывалась (``coro.close()``)
# и событие ТЕРЯЛОСЬ (``audit.emit.dropped_no_event_loop``). Страдали
# FastAPI sync-эндпоинты (threadpool), ``asyncio.to_thread`` и CLI.
#
# Теперь событие ДОСТАВЛЯЕТСЯ: выделяется один фоновый поток со своим
# event loop, корутина планируется в него через
# ``asyncio.run_coroutine_threadsafe``. Вызывающий поток не блокируется.
_sync_loop: asyncio.AbstractEventLoop | None = None
_sync_thread: threading.Thread | None = None
_sync_loop_lock = threading.Lock()


def _run_sync_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Точка входа фонового потока: крутит event loop до остановки.

    Args:
        loop: Event loop, который нужно обслуживать.

    """
    asyncio.set_event_loop(loop)
    try:
        loop.run_forever()
    finally:
        loop.close()


def _ensure_sync_loop() -> asyncio.AbstractEventLoop:
    """Лениво создать (и вернуть) выделенный event loop для sync-контекста.

    Returns:
        Живой event loop, обслуживаемый фоновым daemon-потоком.

    """
    global _sync_loop, _sync_thread
    with _sync_loop_lock:
        if _sync_loop is not None and not _sync_loop.is_closed():
            return _sync_loop
        loop = asyncio.new_event_loop()
        thread = threading.Thread(
            target=_run_sync_loop, args=(loop,), name="audit-sync-dispatch", daemon=True
        )
        thread.start()
        _sync_loop = loop
        _sync_thread = thread
        return loop


def _shutdown_sync_loop() -> None:
    """Остановить фоновый event loop (вызывается на выходе процесса)."""
    global _sync_loop, _sync_thread
    with _sync_loop_lock:
        loop, thread = _sync_loop, _sync_thread
        _sync_loop = None
        _sync_thread = None
    if loop is None:
        return
    try:
        loop.call_soon_threadsafe(loop.stop)
    except RuntimeError:
        # Loop уже закрыт — ничего делать не нужно.
        return
    if thread is not None:
        thread.join(timeout=5.0)


atexit.register(_shutdown_sync_loop)


def _with_context(
    ctx: contextvars.Context, coro: Coroutine[Any, Any, Any]
) -> Coroutine[Any, Any, Any]:
    """Обернуть корутину так, чтобы она видела contextvars вызывающего.

    ``asyncio.run_coroutine_threadsafe`` выполняет корутину в контексте
    ФОНОВОГО потока, а не вызывающего. Без обёртки терялись бы
    ``correlation_id`` / ``tenant_id`` — событие доставлялось бы, но без
    привязки к запросу.

    Args:
        ctx: Снимок contextvars вызывающего потока.
        coro: Корутина аудита.

    Returns:
        Корутину-обёртку, восстанавливающую contextvars.

    """

    async def _runner() -> Any:
        for var, value in ctx.items():
            try:
                var.set(value)
            except (LookupError, RuntimeError, TypeError):
                continue
        return await coro

    return _runner()


def _log_audit_task_failure(task: asyncio.Task[Any]) -> None:
    """Залогировать исключение fire-and-forget задачи аудита.

    Args:
        task: Завершённая задача, созданная диспетчером.

    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        _logger.warning("audit.emit.task_failed", extra={"error": repr(exc)})


def _log_audit_delivery_failure(future: Future[Any]) -> None:
    """Залогировать ошибку доставки audit-события в sync-контексте.

    Args:
        future: Завершённый future фоновой доставки.

    """
    if future.cancelled():
        return
    exc = future.exception()
    if exc is not None:
        _logger.error("audit.emit.sync_delivery_failed", extra={"error": repr(exc)})


def _dispatch_sync_audit(coro: Any, *, event: str) -> Any:
    """Доставить audit-событие из чисто sync-контекста.

    Событие уходит в unified audit-service через выделенный фоновый
    event loop (см. :func:`_ensure_sync_loop`). Вызывающий поток не
    блокируется; ошибка доставки логируется явно (не тишина).

    Args:
        coro: Корутина ``AuditService.emit()``.
        event: Имя события — для диагностических логов.

    Returns:
        :class:`concurrent.futures.Future` доставки либо ``None``, если
        доставка невозможна.

    """
    try:
        loop = _ensure_sync_loop()
        future = asyncio.run_coroutine_threadsafe(
            _with_context(contextvars.copy_context(), coro), loop
        )
    except Exception as exc:
        # Доставка невозможна — событие НЕ теряем молча.
        coro.close()
        _logger.error(
            "audit.emit.dropped_sync_delivery_failed",
            extra={"event": event, "error": repr(exc)},
        )
        return None
    future.add_done_callback(_log_audit_delivery_failure)
    return future


def _dispatch_audit_coro(coro: Any, *, event: str) -> Any:
    """Диспетчеризовать корутину ``AuditService.emit()``.

    ``AuditService.emit()`` — coroutine, поэтому sync-facade обязан явно
    определить её судьбу, иначе Python выдаёт ``RuntimeWarning: coroutine
    ... was never awaited`` и событие молча теряется.

    Поведение:

    * есть running event loop → задача создаётся через
      :class:`~src.backend.core.utils.task_registry.TaskRegistry`
      (fire-and-forget, ничего не блокирует) + done-callback, логирующий
      исключение задачи;
    * running loop нет (чисто sync-контекст) → событие доставляется в
      выделенный фоновый event loop (ADR-0392): корутина НЕ закрывается,
      потеря события — только явная ошибка в лог.

    ``asyncio.run()`` НЕ используется: клиенты audit-service могут быть
    привязаны к другому event loop.

    Args:
        coro: Корутина ``AuditService.emit()`` (или иной awaitable).
        event: Имя события — для лога dropped-события.

    Returns:
        Task (awaitable) в async-контексте, ``Future`` доставки — в
        sync-контексте; non-coroutine значение возвращается как есть.

    """
    if not asyncio.iscoroutine(coro) or isinstance(coro, asyncio.Future):
        # Не корутина (sync-реализация emit, mock, уже запланированная
        # задача) — диспетчеризация не нужна.
        return coro
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # Чисто sync-контекст — доставляем через фоновый event loop.
        return _dispatch_sync_audit(coro, event=event)
    try:
        task = get_task_registry().create_task(coro, name="core.audit.emit")
    except RuntimeError:
        # Реестр закрыт (app shutdown) — событие не доставить.
        coro.close()
        _logger.warning("audit.emit.dropped_registry_closed", extra={"event": event})
        return None
    task.add_done_callback(_log_audit_task_failure)
    return task


def emit_audit(
    event: str,
    *,
    actor: str = "system",
    resource: str = "",
    action: str = "",
    outcome: str = "success",
    details: dict[str, Any] | None = None,
) -> Any:
    """Canonical facade method — emit audit event (sync-диспетчер).

    S103 W3: re-export ``AuditService.emit()`` через canonical location.
    Async-версия ``audit_service.emit()`` (для использования внутри
    async-контекстов) — preferred. Этот sync wrapper exists для
    ``__init__``/module-level calls (e.g. ``emit_audit(event='boot')``).

    Корутина ``AuditService.emit()`` диспетчеризируется (см.
    :func:`_dispatch_audit_coro`): в async-контексте событие реально уходит
    в audit-service (fire-and-forget task), в sync-контексте — событие
    доставляется через выделенный фоновый event loop (ADR-0392); потеря
    события фиксируется явной ошибкой в логе, а не тишиной.

    Args:
        event: Имя события (``"feature.toggled"``).
        actor: Кто выполнил (``"admin:alice"`` или ``"system"``).
        resource: Ресурс (например, ``"feature_flag/ai_workspace_ttl"``).
        action: Действие (``"toggle"``, ``"create"``, ``"delete"``).
        outcome: Результат (``"success"`` / ``"failure"`` / ``"denied"``).
        details: Доп. metadata (dict).

    Returns:
        Task (awaitable) в async-контексте, ``Future`` доставки — в
        sync-контексте (``None``, если доставка невозможна).

    """
    svc = get_unified_audit_service()
    coro = svc.emit(  # type: ignore[no-untyped-call]
        event=event,
        actor=actor,
        resource=resource,
        action=action,
        outcome=outcome,
        details=details,
    )
    return _dispatch_audit_coro(coro, event=event)


def emit_audit_safe(
    *,
    event: str,
    action: str = "",
    outcome: str = "success",
    details: dict[str, Any] | None = None,
    severity: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Any:
    """Emit audit event ``_safe`` variant (Path A pattern E/G — never raises).

    Used by ``core/security/pii_tokenizer.py`` (3 calls) и
    ``dsl/engine/processors/agent_dsl/_base.py`` (3 calls).
    Wraps ``emit_audit`` в try/except — PII / agent pipelines не должны
    raise при audit failures.

    Args:
        event: Event name.
        action: Action performed.
        outcome: ``"success"`` / ``"failure"``.
        details: Optional details dict.
        severity: Optional severity (``"info"`` / ``"warning"`` / ``"error"``).
        extra: Optional extra fields (merged into details).

    Returns:
        Task (awaitable) в async-контексте, ``Future`` доставки — в
        sync-контексте (``None`` при ошибке emit — никогда не raise).

    """
    merged_details: dict[str, Any] = dict(details or {})
    if severity is not None:
        merged_details["severity"] = severity
    if extra:
        merged_details.update(extra)
    try:
        return emit_audit(
            event=event,
            actor="system",
            action=action,
            outcome=outcome,
            details=merged_details or None,
        )
    except Exception:
        return None
