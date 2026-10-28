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
from typing import Any

from src.backend.core.audit.facade.audit_service import get_unified_audit_service
from src.backend.core.logging import get_logger
from src.backend.core.utils.task_registry import get_task_registry

__all__ = ("emit_audit", "emit_audit_safe")

_logger = get_logger("core.audit.facade.base")


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
    * running loop нет (чисто sync-контекст) → корутина закрывается явно
      (``coro.close()``) и событие фиксируется в логе как dropped.

    ``asyncio.run()`` НЕ используется: клиенты audit-service могут быть
    привязаны к другому event loop.

    Args:
        coro: Корутина ``AuditService.emit()`` (или иной awaitable).
        event: Имя события — для лога dropped-события.

    Returns:
        Task (awaitable) в async-контексте, ``None`` в sync-контексте;
        non-coroutine значение возвращается как есть.

    """
    if not asyncio.iscoroutine(coro) or isinstance(coro, asyncio.Future):
        # Не корутина (sync-реализация emit, mock, уже запланированная
        # задача) — диспетчеризация не нужна.
        return coro
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # Чисто sync-контекст — доставлять событие некуда.
        coro.close()
        _logger.warning("audit.emit.dropped_no_event_loop", extra={"event": event})
        return None
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
    в audit-service (fire-and-forget task), в sync-контексте — закрывается
    без ``RuntimeWarning`` и помечается в логе как dropped.

    Args:
        event: Имя события (``"feature.toggled"``).
        actor: Кто выполнил (``"admin:alice"`` или ``"system"``).
        resource: Ресурс (например, ``"feature_flag/ai_workspace_ttl"``).
        action: Действие (``"toggle"``, ``"create"``, ``"delete"``).
        outcome: Результат (``"success"`` / ``"failure"`` / ``"denied"``).
        details: Доп. metadata (dict).

    Returns:
        Task (awaitable) в async-контексте, ``None`` в sync-контексте.

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
        Task (awaitable) в async-контексте, ``None`` в sync-контексте
        (или при ошибке emit — никогда не raise).

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
