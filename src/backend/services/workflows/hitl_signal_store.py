"""HITL signal store: Protocol + in-memory реализация (S3 сплит, из hitl_service).

S3 (ledger, 2026-09-05): выделение зон ответственности из
``hitl_service.py`` (507 LOC god-object) по паттерну закрытых M2-сплитов.
Redis-реализация — :mod:`hitl_signal_store_redis`. Обратная совместимость —
``hitl_service`` ре-экспортирует публичные имена.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from src.backend.services.workflows.hitl_models import HitlPendingSignal

__all__ = ("HitlSignalStore", "InMemoryHitlSignalStore")


@runtime_checkable
class HitlSignalStore(Protocol):
    """Backend-агностичное хранилище pending signals."""

    async def put(self, signal: HitlPendingSignal) -> None:
        """Store a HITL signal.

        Args:
            signal: Signal to store.

        """
        ...

    async def get(self, signal_id: str) -> HitlPendingSignal | None:
        """Get signal by ID.

        Args:
            signal_id: Signal identifier.

        Returns:
            Signal if found, None otherwise.

        """
        ...

    async def list_pending(
        self, *, tenant_id: str | None = None
    ) -> list[HitlPendingSignal]:
        """List pending signals.

        Args:
            tenant_id: Optional tenant filter.

        Returns:
            List of pending signals.

        """
        ...

    async def mark_resolved(
        self, signal_id: str, *, action: str, resolved_by: str
    ) -> HitlPendingSignal:
        """Mark signal as resolved.

        Args:
            signal_id: Signal identifier.
            action: Resolution action.
            resolved_by: Resolver identity.

        Returns:
            Updated signal.

        """
        ...

    async def wait_for(self, signal_id: str, timeout: float | None = None) -> bool:
        """Wait for signal resolution.

        Args:
            signal_id: Signal identifier.
            timeout: Optional timeout in seconds.

        Returns:
            True if resolved, False if timeout.

        """
        ...


class InMemoryHitlSignalStore:
    """In-memory store для dev_light и unit-тестов."""

    def __init__(self) -> None:
        self._store: dict[str, HitlPendingSignal] = {}
        self._lock = asyncio.Lock()
        self._events: dict[str, asyncio.Event] = {}

    async def put(self, signal: HitlPendingSignal) -> None:
        """Store a HITL signal.

        Args:
            signal: Signal to store.

        """
        async with self._lock:
            self._store[signal.signal_id] = signal
            self._events.setdefault(signal.signal_id, asyncio.Event())

    async def get(self, signal_id: str) -> HitlPendingSignal | None:
        """Get signal by ID.

        Args:
            signal_id: Signal identifier.

        Returns:
            Signal if found, None otherwise.

        """
        async with self._lock:
            return self._store.get(signal_id)

    async def list_pending(
        self, *, tenant_id: str | None = None
    ) -> list[HitlPendingSignal]:
        """List pending signals.

        Args:
            tenant_id: Optional tenant filter.

        Returns:
            List of pending signals.

        """
        async with self._lock:
            items = [s for s in self._store.values() if not s.is_resolved]
        if tenant_id is not None:
            items = [s for s in items if s.tenant_id == tenant_id]
        return sorted(items, key=lambda s: s.created_at)

    async def mark_resolved(
        self, signal_id: str, *, action: str, resolved_by: str
    ) -> HitlPendingSignal:
        """Mark signal as resolved.

        Args:
            signal_id: Signal identifier.
            action: Resolution action.
            resolved_by: Resolver identity.

        Returns:
            Updated signal.

        Raises:
            KeyError: If signal not found.
            ValueError: If signal already resolved.

        """
        async with self._lock:
            signal = self._store.get(signal_id)
            if signal is None:
                raise KeyError(f"HITL signal {signal_id!r} not found")
            if signal.is_resolved:
                raise ValueError(
                    f"HITL signal {signal_id!r} already resolved by "
                    f"{signal.resolved_by!r} as {signal.resolved_action!r}"
                )
            signal.resolved_at = datetime.now(UTC)
            signal.resolved_action = action
            signal.resolved_by = resolved_by
            event = self._events.get(signal_id)
        if event is not None:
            event.set()
        return signal

    async def wait_for(self, signal_id: str, timeout: float | None = None) -> bool:
        """Ждёт разрешения signal'а без polling.

        ponytail: event-driven wakeup вместо busy-wait. Для multi-instance
        production нужен Redis pub/sub — пока in-memory.
        """
        async with self._lock:
            event = self._events.setdefault(signal_id, asyncio.Event())
            signal = self._store.get(signal_id)
            if signal is not None and signal.is_resolved:
                return True
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except TimeoutError:
            return False
        return True
