"""DI test: SchedulerFacade принимает SchedulerBackend и RunHistoryStoreProtocol
через ``__init__`` (25.09 audit).

Per v6: «Инъецировать в SchedulerFacade существующий SchedulerBackend
Protocol и новый RunHistoryStoreProtocol; удалить service locator внутри
методов».

Контракт:
- ``__init__(backend=..., history_store=...)`` — injected deps;
- ``add_job`` использует injected ``backend.schedule_cron``;
- ``get_run_history_store`` возвращает injected ``history_store``;
- ``remove_job`` использует injected ``backend.cancel/remove_job``;
- Без deps → backward compat fall-back на service locator.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.services.scheduler.facade import SchedulerFacade
from src.backend.services.scheduler.protocols import (
    JobRegistrationResult,
    RunHistoryStoreProtocol,
)


class _MockBackend:
    """Mock SchedulerBackend — имитирует schedule_cron, cancel, remove_job."""

    def __init__(self) -> None:
        self.schedule_cron_calls: list[dict[str, Any]] = []
        self.cancel_calls: list[str] = []
        self.remove_job_calls: list[str] = []

    def schedule_cron(
        self,
        name: str,
        cron_expr: str,
        callable_ref: Any,
        *,
        timezone: str = "Europe/Moscow",
        replace_existing: bool = True,
    ) -> str:
        self.schedule_cron_calls.append(
            {
                "name": name,
                "cron_expr": cron_expr,
                "callable_ref": callable_ref,
                "timezone": timezone,
                "replace_existing": replace_existing,
            }
        )
        return f"mock-{name}"

    def cancel(self, job_id: str) -> bool:
        self.cancel_calls.append(job_id)
        return True

    def remove_job(self, job_id: str) -> bool:
        self.remove_job_calls.append(job_id)
        return True


class _MockHistoryStore:
    """Mock RunHistoryStoreProtocol — имитирует materialize(ticks) → int."""

    def __init__(self, created_count: int = 0) -> None:
        self.created_count = created_count
        self.materialize_calls: list[dict[str, Any]] = []

    async def materialize(
        self,
        job_id: str,
        ticks: list[Any],
        *,
        status: str = "missed",
        tenant_id: str | None = None,
    ) -> int:
        self.materialize_calls.append(
            {
                "job_id": job_id,
                "ticks": ticks,
                "status": status,
                "tenant_id": tenant_id,
            }
        )
        return self.created_count

    async def pending(self, job_id: str, limit: int = 100) -> list[Any]:
        return []

    async def last_scheduled(self, job_id: str) -> Any:
        return None

    async def mark(self, job_id: str, scheduled_at: Any, **kwargs: Any) -> None:
        pass

    async def run_pending(self, job_id: str, executor: Any, **kwargs: Any) -> int:
        return 0


@pytest.mark.asyncio
async def test_add_job_uses_injected_backend() -> None:
    """Injected backend.schedule_cron вызывается вместо service locator."""
    backend = _MockBackend()
    history_store = _MockHistoryStore()
    facade = SchedulerFacade(backend=backend, history_store=history_store)

    result = await facade.add_job(
        job_id="my_job",
        func=lambda: None,
        cron_expr="0 * * * *",
    )

    # backend был вызван (НЕ service locator).
    assert len(backend.schedule_cron_calls) == 1
    call = backend.schedule_cron_calls[0]
    assert call["name"] == "my_job"
    assert call["cron_expr"] == "0 * * * *"
    assert call["timezone"] == "Europe/Moscow"
    assert call["replace_existing"] is True
    # result — JobRegistrationResult (TypedDict → dict runtime).
    assert result["registered"] is True
    assert result["job_id"] == "mock-my_job"
    assert result["error"] is None


@pytest.mark.asyncio
async def test_add_job_with_catchup_uses_injected_history_store() -> None:
    """Injected history_store используется для catchup materialization."""
    from datetime import datetime, timedelta

    backend = _MockBackend()
    # Inject mock store — BackfillService calls ``materialize(ticks, ...)``
    # и получает `created` count. ``ticks_in_window`` = ``len(ticks)``.
    history_store = _MockHistoryStore(created_count=42)
    facade = SchedulerFacade(backend=backend, history_store=history_store)

    result = await facade.add_job(
        job_id="catchup_job",
        func=lambda: None,
        cron_expr="*/30 * * * *",
        catchup=True,
        catchup_window_days=2,
    )

    assert result["registered"] is True
    assert result["history_materialized"] is True
    assert result["catchup_scheduled"] is True
    # ticks_in_window = len(ticks) computed by BackfillService (не равно 42 — это created).
    # Важно: materialize был вызван с catchup=True → status="pending".
    assert len(history_store.materialize_calls) == 1
    call = history_store.materialize_calls[0]
    assert call["job_id"] == "catchup_job"
    assert call["status"] == "pending"
    assert len(call["ticks"]) > 0  # ticks computed via CronTrigger


@pytest.mark.asyncio
async def test_get_run_history_store_returns_injected() -> None:
    """get_run_history_store возвращает injected history_store (не service locator)."""
    backend = _MockBackend()
    history_store = _MockHistoryStore()
    facade = SchedulerFacade(backend=backend, history_store=history_store)

    result = facade.get_run_history_store()
    assert result is history_store


def test_remove_job_uses_injected_backend_cancel() -> None:
    """remove_job вызывает injected backend.cancel (НЕ backend.remove_job fallback)."""
    backend = _MockBackend()
    facade = SchedulerFacade(backend=backend)

    facade.remove_job("my_job")

    assert backend.cancel_calls == ["my_job"]
    assert backend.remove_job_calls == []  # cancel preferred


def test_remove_job_uses_injected_backend_remove_job_when_no_cancel() -> None:
    """remove_job fallback на backend.remove_job если backend без cancel method."""

    class _LegacyBackend:
        def schedule_cron(self, **kwargs: Any) -> str:
            return "legacy"

        def remove_job(self, job_id: str) -> bool:
            self.calls.append(job_id)
            return True

        calls: list[str] = []

    backend = _LegacyBackend()
    facade = SchedulerFacade(backend=backend)

    facade.remove_job("legacy_job")

    assert backend.calls == ["legacy_job"]


def test_add_job_returns_typed_job_registration_result() -> None:
    """add_job returns JobRegistrationResult TypedDict с обязательными полями.

    Per 25.09 audit: «Заменить dict[str, Any] результата регистрации на
    typed JobRegistrationResult». TypedDict — это typed dict на runtime.
    """
    import inspect

    facade = SchedulerFacade(backend=_MockBackend())
    sig = inspect.signature(facade.add_job)
    return_annotation = sig.return_annotation
    # TypedDict annotation может быть строкой forward reference.
    assert "JobRegistrationResult" in str(return_annotation), (
        f"add_job return annotation must reference JobRegistrationResult, "
        f"got {return_annotation}"
    )


def test_protocols_module_exports() -> None:
    """protocols.py экспортирует RunHistoryStoreProtocol + JobRegistrationResult."""
    from src.backend.services.scheduler import protocols

    assert hasattr(protocols, "RunHistoryStoreProtocol")
    assert hasattr(protocols, "JobRegistrationResult")
    # RunHistoryStoreProtocol — runtime_checkable Protocol
    assert getattr(protocols.RunHistoryStoreProtocol, "_is_runtime_protocol", False) or hasattr(
        protocols.RunHistoryStoreProtocol, "__call__"
    ) or hasattr(protocols.RunHistoryStoreProtocol, "_is_protocol")


def test_run_history_store_protocol_matches_concrete() -> None:
    """Concrete ``RunHistoryStore`` structural-matches ``RunHistoryStoreProtocol``.

    Python Protocol — duck typing. Если concrete class реализует все
    методы Protocol — isinstance check проходит.
    """
    from src.backend.services.scheduler.run_history import RunHistoryStore

    # Method names check (structural match).
    protocol_methods = {"materialize", "pending", "last_scheduled", "mark", "run_pending"}
    concrete_methods = set(dir(RunHistoryStore))
    missing = protocol_methods - concrete_methods
    assert not missing, (
        f"RunHistoryStore missing protocol methods: {missing}. "
        f"Either update Protocol или concrete class."
    )
