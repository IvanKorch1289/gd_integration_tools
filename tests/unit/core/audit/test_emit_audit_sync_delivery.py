"""Синхронный контекст: audit-событие ДОСТАВЛЯЕТСЯ, а не теряется.

ADR-0392 (волна 18, кластер G3 — логирование).

Дефект: ``core/audit/facade/_base.py`` при отсутствии running event loop
делал ``coro.close()`` и писал ``audit.emit.dropped_no_event_loop`` —
событие УНИЧТОЖАЛОСЬ. Страдали:

* FastAPI sync-эндпоинты (исполняются в threadpool — loop в потоке нет);
* ``asyncio.to_thread`` / ``run_in_executor``;
* CLI-команды и воркеры.

Контракт после фикса: в sync-контексте событие доставляется в unified
audit-service через выделенный фоновый event loop (собственный поток).
Вызывающий поток НЕ блокируется; потеря события — явная ошибка в лог,
а не тишина.
"""

from __future__ import annotations

import asyncio
import contextvars
import time
from typing import Any

import pytest

from src.backend.core.audit.facade import _base as base_module

#: Таймаут ожидания доставки (секунды).
DELIVERY_TIMEOUT = 10.0

#: ContextVar для проверки пропагации контекста в фоновую доставку.
_probe_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "audit_sync_probe", default=""
)


class _RecordingAuditService:
    """Double unified audit-service: async ``emit`` пишет kwargs в список."""

    def __init__(self) -> None:
        """Создать пустой recorder."""
        self.calls: list[dict[str, Any]] = []

    async def emit(self, **kwargs: Any) -> None:
        """Записать kwargs-вызова ``emit`` + зафиксировать contextvar."""
        self.calls.append({**kwargs, "_probe": _probe_var.get()})


@pytest.fixture
def recording_service(monkeypatch: pytest.MonkeyPatch) -> _RecordingAuditService:
    """Подменить unified audit-service на recorder."""
    service = _RecordingAuditService()
    monkeypatch.setattr(base_module, "get_unified_audit_service", lambda: service)
    return service


def _wait_for_delivery(service: _RecordingAuditService) -> bool:
    """Дождаться доставки события (poll + timeout, без ``sleep``-фикстур)."""
    deadline = time.monotonic() + DELIVERY_TIMEOUT
    while time.monotonic() < deadline:
        if service.calls:
            return True
        time.sleep(0.005)
    return bool(service.calls)


@pytest.mark.unit
class TestSyncContextDelivery:
    """Событие из sync-контекста доходит до audit-service."""

    def test_sync_emit_delivers_event(
        self, recording_service: _RecordingAuditService
    ) -> None:
        """Sync-вызов ``emit_audit`` → событие реально доставлено."""
        base_module.emit_audit(
            event="capability.check",
            actor="core",
            resource="db.read",
            action="check",
            outcome="denied",
            details={"capability": "db.read"},
        )

        assert _wait_for_delivery(recording_service), (
            "audit-событие не доставлено в sync-контексте"
        )
        call = recording_service.calls[0]
        assert call["event"] == "capability.check"
        assert call["outcome"] == "denied"
        assert call["details"]["capability"] == "db.read"

    def test_sync_emit_returns_handle_not_none(
        self, recording_service: _RecordingAuditService
    ) -> None:
        """Sync-вызов возвращает handle доставки (событие не «сброшено»)."""
        result = base_module.emit_audit(event="sync.handle")
        assert result is not None
        assert _wait_for_delivery(recording_service)

    def test_sync_emit_does_not_block_caller(
        self, recording_service: _RecordingAuditService
    ) -> None:
        """Вызывающий sync-поток не блокируется на доставке.

        Доставка идёт в фоновом потоке, поэтому сам ``emit_audit``
        возвращается быстро (доли секунды), даже если backend медленный.
        """
        started = time.monotonic()
        base_module.emit_audit(event="sync.nonblocking")
        elapsed = time.monotonic() - started
        assert elapsed < 2.0, f"emit_audit блокировал вызывающий поток: {elapsed:.3f}s"

    def test_sync_emit_propagates_contextvars(
        self, recording_service: _RecordingAuditService
    ) -> None:
        """Contextvars вызывающего потока видны в фоновой доставке.

        Иначе терялись бы ``correlation_id`` / ``tenant_id`` — то есть
        audit-событие доставлялось бы, но без привязки к запросу.
        """
        token = _probe_var.set("ctx-value")
        try:
            base_module.emit_audit(event="sync.context")
        finally:
            _probe_var.reset(token)

        assert _wait_for_delivery(recording_service)
        assert recording_service.calls[0]["_probe"] == "ctx-value"

    def test_multiple_sync_emits_are_all_delivered(
        self, recording_service: _RecordingAuditService
    ) -> None:
        """Серия sync-вызовов — все события доставлены (ничего не теряется)."""
        for index in range(5):
            base_module.emit_audit(event=f"sync.batch.{index}")

        deadline = time.monotonic() + DELIVERY_TIMEOUT
        while len(recording_service.calls) < 5 and time.monotonic() < deadline:
            time.sleep(0.005)

        assert len(recording_service.calls) == 5


@pytest.mark.unit
class TestAsyncContextUnchanged:
    """Async-путь не сломан рефакторингом sync-фоллбэка."""

    @pytest.mark.asyncio
    async def test_async_emit_still_uses_task_registry(
        self, recording_service: _RecordingAuditService
    ) -> None:
        """В async-контексте событие уходит через fire-and-forget task."""
        base_module.emit_audit(event="async.path")

        for _ in range(50):
            if recording_service.calls:
                break
            await asyncio.sleep(0)

        assert len(recording_service.calls) == 1
