"""Wave 13 (Q3) — dispatch-семантика ``core.audit.facade._base.emit_audit``.

Регрессия: ``AuditService.emit()`` — coroutine, а sync-facade ``emit_audit``
возвращал её без ``await``. В sync-контексте это давало
``RuntimeWarning: coroutine 'AuditService.emit' was never awaited``, а
capability-решения (granted/denied) НЕ доходили до unified audit-service.

Контракт диспетчера:

* running event loop есть → fire-and-forget задача (через
  ``TaskRegistry``) + done-callback, логирующий исключение задачи;
* running event loop нет → корутина закрывается явно (``coro.close()``) —
  без RuntimeWarning, событие фиксируется как dropped в логе.
"""

from __future__ import annotations

import asyncio
import gc
import time
import warnings
from typing import Any

import pytest

from src.backend.core.audit.facade import _base as base_module
from src.backend.core.audit.facade import emit_capability_check


class _RecordingAuditService:
    """Double unified audit-service: async ``emit`` пишет kwargs в список."""

    def __init__(self) -> None:
        """Создать пустой recorder."""
        self.calls: list[dict[str, Any]] = []

    async def emit(self, **kwargs: Any) -> None:
        """Записать kwargs-вызова ``emit``."""
        self.calls.append(kwargs)


@pytest.fixture
def recording_service(monkeypatch: pytest.MonkeyPatch) -> _RecordingAuditService:
    """Подменить unified audit-service на recorder."""
    service = _RecordingAuditService()
    monkeypatch.setattr(base_module, "get_unified_audit_service", lambda: service)
    return service


@pytest.mark.asyncio
async def test_emit_capability_check_reaches_service_in_running_loop(
    recording_service: _RecordingAuditService,
) -> None:
    """В async-контексте событие реально уходит в unified audit-service."""
    emit_capability_check(
        plugin="core",
        capability="db.read",
        requested_scope=None,
        declared_scope=None,
        outcome="granted",
    )

    for _ in range(10):
        if recording_service.calls:
            break
        await asyncio.sleep(0)

    assert len(recording_service.calls) == 1
    call = recording_service.calls[0]
    assert call["event"] == "capability.check"
    assert call["outcome"] == "granted"
    assert call["details"]["capability"] == "db.read"


def test_emit_capability_check_sync_context_has_no_never_awaited_warning(
    recording_service: _RecordingAuditService,
) -> None:
    """В sync-контексте нет RuntimeWarning 'coroutine ... was never awaited'.

    Фильтр — по корутине audit-emit: чужие never-awaited корутины других
    модулей (собираются ``gc.collect()``) не должны ломать этот тест.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        emit_capability_check(
            plugin="core",
            capability="db.read",
            requested_scope=None,
            declared_scope=None,
            outcome="denied",
        )
        gc.collect()

    never_awaited = [
        item
        for item in caught
        if issubclass(item.category, RuntimeWarning)
        and "never awaited" in str(item.message)
        and "_RecordingAuditService.emit" in str(item.message)
    ]
    assert never_awaited == []


def test_emit_audit_sync_context_delivers_event_without_running_loop(
    recording_service: _RecordingAuditService,
) -> None:
    """Sync-контекст: событие ДОСТАВЛЯЕТСЯ (ADR-0392), а не теряется.

    Раньше корутина закрывалась (``coro.close()``) и событие уничтожалось
    (``audit.emit.dropped_no_event_loop``) — страдали FastAPI sync-эндпоинты
    (threadpool), ``asyncio.to_thread`` и CLI.
    """
    result = base_module.emit_audit(
        event="capability.check",
        actor="core",
        resource="db.read",
        action="check",
        outcome="denied",
        details={"capability": "db.read"},
    )

    assert result is not None

    deadline = time.monotonic() + 10.0
    while not recording_service.calls and time.monotonic() < deadline:
        time.sleep(0.005)

    assert len(recording_service.calls) == 1
    call = recording_service.calls[0]
    assert call["event"] == "capability.check"
    assert call["outcome"] == "denied"
    assert call["details"]["capability"] == "db.read"
