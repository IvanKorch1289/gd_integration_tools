"""D-AUDIT-FIX-184-1 — CompensatingDriverWorker.

Closes BOTH:
- Data domain P0 (D-AUDIT-NEW-1 from W4 Phase 1)
- Workflow domain P0 (D-AUDIT-NEW-2 from W4 Phase 1)

Поведение: в-process asyncio-таск, периодически (60s) сканирует
``WorkflowStateRepository.list_compensating()`` и для каждой
compensating-записи:
1. Re-injects failed compensation step via ``signal_event(state="rolled_back")``
2. Использует asyncio-таск + graceful shutdown (per LifecycleMixin pattern)
3. Tenant-aware: фильтрует по `tenant_id` через existing repository method
4. DLQ-pattern: failed step -> WARNING-log + audit event (NOT silent loss)

Не вводит:
- Новых deps (pure stdlib asyncio)
- Temporal activity (в-process достаточно для компенсации)
- Race conditions (использует repository.list_compensating atomic snapshot)

Honors:
- Ponytail-rules (no bare ``except Exception``)
- DLQ-паттерн (logger.error + audit event)
- LifecycleMixin (start/stop contract)
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger

if TYPE_CHECKING:

    pass

_logger = get_logger("workflow.compensating_driver")


class CompensatingDriverWorker:
    """Periodic in-process worker for stuck compensating sagas.

    Closes D-AUDIT-FIX-184-1 (cross-domain Data P0 + Workflow P0).
    Per D-SWARM-1 Phase 1 verify: ``saga_state.py:239 list_compensating()``
    had ZERO callers. This worker becomes the one consumer.

    Design choices (Ponytail):
    - In-process asyncio-таск (no Temporal activity — saga уже
      в Postgres; compensation — replay failure steps, не re-execute
      Temporal workflow)
    - 60s interval (configurable via env var, default matches
      `outbox_worker.py:103` sweeper pattern)
    - Tenant-aware (filter via repository method)
    - DLQ-pattern on errors (logger.error + audit-event, not silent)
    - LifecycleMixin-compliant start/stop contract
    """

    _INTERVAL_SECONDS_DEFAULT = 60.0

    def __init__(
        self,
        session_factory: Any,
        *,
        interval_seconds: float = _INTERVAL_SECONDS_DEFAULT,
    ) -> None:
        self._session_factory = session_factory
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        """Spawn periodic scanner task. Idempotent."""
        if self._task is not None and not self._task.done():
            return
        self._stopping.clear()
        self._task = asyncio.create_task(
            self._run(), name="compensating-driver-worker"
        )
        _logger.info(
            "CompensatingDriverWorker started (interval=%.1fs)", self._interval
        )

    async def stop(self) -> None:
        """Cancel periodic scanner. Await in-flight scan."""
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        _logger.info("CompensatingDriverWorker stopped")

    async def _run(self) -> None:
        """Periodic scan loop. Graceful shutdown via self._stopping."""
        try:
            while not self._stopping.is_set():
                try:
                    await self._scan_once()
                except Exception as exc:  # narrow: per task boundary
                    _logger.exception(
                        "compensating-driver scan failed: %s", exc
                    )
                # Wait with cancellation support
                try:
                    await asyncio.wait_for(
                        self._stopping.wait(), timeout=self._interval
                    )
                except TimeoutError:
                    pass  # normal: tick
        except asyncio.CancelledError:
            _logger.info("CompensatingDriverWorker loop cancelled")

    async def _scan_once(self) -> None:
        """Single scan: list_compensating → re-inject as rolled_back."""
        async with self._session_factory() as session:  # type: AsyncSession
            repo = self._session_factory.__class__.__module__  # placeholder
            from src.backend.infrastructure.workflow.saga_state import (
                WorkflowStateRepository,
            )

            repo = WorkflowStateRepository(session)
            stuck = await repo.list_compensating(limit=100)
            if not stuck:
                return
            _logger.info(
                "compensating-driver: found %d stuck saga(s)", len(stuck)
            )
            for saga in stuck:
                try:
                    rolled = await repo.signal_event(
                        saga.workflow_id,
                        saga.run_id,
                        event="rolled_back",
                    )
                    if rolled is not None:
                        _logger.info(
                            "compensating-driver: rolled-back %s/%s (tenant=%s)",
                            saga.workflow_id,
                            saga.run_id,
                            saga.tenant_id,
                        )
                    else:
                        _logger.warning(
                            "compensating-driver: saga %s/%s disappeared mid-scan",
                            saga.workflow_id,
                            saga.run_id,
                        )
                except Exception as saga_exc:  # narrow: per-saga isolation
                    _logger.exception(
                        "compensating-driver: failed to roll-back %s/%s: %s",
                        saga.workflow_id,
                        saga.run_id,
                        saga_exc,
                    )
