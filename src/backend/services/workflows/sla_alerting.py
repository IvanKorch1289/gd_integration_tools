"""Workflow SLA alerting service (Sprint 9 K3 W10 / GAP-WF-4.4).

Слой контроля SLA для workflow-instances:

* :class:`SlaTracker` — фоновый watch over running workflow handles,
  emit ``soft_breach`` / ``hard_breach`` событий.
* :class:`SlaAlertDispatcher` — abstract sender (email / Slack / pager);
  in-memory реализация для unit-тестов.
* :func:`evaluate_sla` — single-pass проверка одного workflow с известными
  start_at + sla_policy.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

__all__ = (
    "SlaAlertDispatcher",
    "SlaBreachLevel",
    "SlaBreachRecord",
    "SlaTracker",
    "InMemorySlaAlertDispatcher",
    "evaluate_sla",
)

_logger = logging.getLogger("workflow.sla_alerting")


class SlaBreachLevel(StrEnum):
    NONE = "none"
    SOFT = "soft"
    HARD = "hard"


@dataclass(slots=True)
class SlaBreachRecord:
    """Запись о breach'е для audit / dispatcher.

    Attributes:
        workflow_id: Temporal workflow ID.
        level: SOFT или HARD.
        elapsed_seconds: время с момента start_at.
        soft_limit: настройка SLA.
        hard_limit: настройка SLA.
        breach_action: что было выполнено (``alert``/``cancel``/``none``).
        detected_at: timestamp обнаружения.
    """

    workflow_id: str
    level: SlaBreachLevel
    elapsed_seconds: float
    soft_limit: float
    hard_limit: float
    breach_action: str = "alert"
    detected_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "level": self.level.value,
            "elapsed_seconds": self.elapsed_seconds,
            "soft_limit_seconds": self.soft_limit,
            "hard_limit_seconds": self.hard_limit,
            "breach_action": self.breach_action,
            "detected_at": self.detected_at.isoformat(),
        }


@runtime_checkable
class SlaAlertDispatcher(Protocol):
    """Channel для отправки SLA-нотификаций."""

    async def dispatch(
        self,
        *,
        breach: SlaBreachRecord,
        email: str | None,
        slack: str | None,
    ) -> None:
        ...


class InMemorySlaAlertDispatcher:
    """In-memory dispatcher для unit-тестов и dev_light."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def dispatch(
        self,
        *,
        breach: SlaBreachRecord,
        email: str | None,
        slack: str | None,
    ) -> None:
        self.sent.append(
            {
                "breach": breach.to_dict(),
                "email": email,
                "slack": slack,
            }
        )


def evaluate_sla(
    *,
    workflow_id: str,
    elapsed_seconds: float,
    soft_limit_seconds: float,
    hard_limit_seconds: float,
    breach_action: str = "alert",
    tenant_id: str | None = None,
) -> SlaBreachRecord:
    """Single-pass evaluation одного workflow.

    Sprint 12 K2 W1: дополнительно инкрементирует Prometheus counter
    ``workflow_sla_compliance_total{workflow_id,tenant_id,level}``.

    Returns:
        :class:`SlaBreachRecord` с ``level=NONE`` если в пределах SLA.
    """
    if elapsed_seconds >= hard_limit_seconds:
        level = SlaBreachLevel.HARD
    elif elapsed_seconds >= soft_limit_seconds:
        level = SlaBreachLevel.SOFT
    else:
        level = SlaBreachLevel.NONE
    _emit_sla_metric(workflow_id=workflow_id, tenant_id=tenant_id, level=level)
    return SlaBreachRecord(
        workflow_id=workflow_id,
        level=level,
        elapsed_seconds=elapsed_seconds,
        soft_limit=soft_limit_seconds,
        hard_limit=hard_limit_seconds,
        breach_action=breach_action,
    )


_sla_counter: Any | None = None


def _emit_sla_metric(
    *,
    workflow_id: str,
    tenant_id: str | None,
    level: "SlaBreachLevel",
) -> None:
    """Increment ``workflow_sla_compliance_total{...,level=...}`` counter.

    Lazy-import prometheus_client; при отсутствии — no-op (тесты не
    должны зависеть от prometheus_client).
    """
    global _sla_counter
    if _sla_counter is None:
        try:
            from prometheus_client import Counter  # type: ignore[import-untyped]

            _sla_counter = Counter(
                "workflow_sla_compliance_total",
                "SLA evaluations per workflow (level=none/soft/hard)",
                labelnames=("workflow_id", "tenant_id", "level"),
            )
        except (ImportError, ValueError):
            _sla_counter = False  # sentinel: do not retry

    if _sla_counter and _sla_counter is not False:
        try:
            _sla_counter.labels(
                workflow_id=workflow_id,
                tenant_id=tenant_id or "",
                level=level.value,
            ).inc()
        except Exception:  # noqa: BLE001
            pass


@dataclass(slots=True)
class _TrackedWorkflow:
    """Запись tracking'а в SlaTracker."""

    workflow_id: str
    start_at: float  # monotonic seconds
    soft_limit_seconds: float
    hard_limit_seconds: float
    escalation_email: str | None
    escalation_slack: str | None
    breach_action: str
    last_alerted_level: SlaBreachLevel = SlaBreachLevel.NONE


class SlaTracker:
    """Фоновый tracker для running workflows.

    Args:
        dispatcher: реализация :class:`SlaAlertDispatcher`.
        check_interval_seconds: период проверки (default 10s).
        on_hard_breach: опц. callback для cancel-action.
    """

    def __init__(
        self,
        *,
        dispatcher: SlaAlertDispatcher,
        check_interval_seconds: float = 10.0,
        on_hard_breach: Any = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._check_interval = check_interval_seconds
        self._on_hard_breach = on_hard_breach
        self._tracked: dict[str, _TrackedWorkflow] = {}
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def track(
        self,
        *,
        workflow_id: str,
        sla: Any,
    ) -> None:
        """Поставить workflow на tracking. ``sla`` — :class:`SlaPolicy`."""
        import time

        async with self._lock:
            self._tracked[workflow_id] = _TrackedWorkflow(
                workflow_id=workflow_id,
                start_at=time.monotonic(),
                soft_limit_seconds=sla.soft_limit_seconds,
                hard_limit_seconds=sla.hard_limit_seconds,
                escalation_email=sla.escalation_email,
                escalation_slack=sla.escalation_slack,
                breach_action=sla.breach_action,
            )

    async def untrack(self, workflow_id: str) -> None:
        """Снять workflow с tracking (после completion)."""
        async with self._lock:
            self._tracked.pop(workflow_id, None)

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="sla-tracker")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self._check_interval
                )
            except asyncio.TimeoutError:
                pass
            await self._check_once()

    async def _check_once(self) -> list[SlaBreachRecord]:
        """Single check; возвращает список breaches."""
        import time

        now = time.monotonic()
        breaches: list[SlaBreachRecord] = []
        async with self._lock:
            entries = list(self._tracked.values())
        for entry in entries:
            elapsed = now - entry.start_at
            breach = evaluate_sla(
                workflow_id=entry.workflow_id,
                elapsed_seconds=elapsed,
                soft_limit_seconds=entry.soft_limit_seconds,
                hard_limit_seconds=entry.hard_limit_seconds,
                breach_action=entry.breach_action,
            )
            if breach.level == SlaBreachLevel.NONE:
                continue
            if (
                entry.last_alerted_level == SlaBreachLevel.HARD
                and breach.level == SlaBreachLevel.HARD
            ):
                continue  # уже отправили hard alert
            if breach.level == entry.last_alerted_level:
                continue  # уже отправили soft alert
            await self._dispatcher.dispatch(
                breach=breach,
                email=entry.escalation_email,
                slack=entry.escalation_slack,
            )
            entry.last_alerted_level = breach.level
            breaches.append(breach)
            if (
                breach.level == SlaBreachLevel.HARD
                and entry.breach_action == "cancel"
                and self._on_hard_breach is not None
            ):
                try:
                    await self._on_hard_breach(entry.workflow_id)
                except Exception:  # noqa: BLE001
                    _logger.exception(
                        "sla.on_hard_breach.callback_failed",
                        extra={"workflow_id": entry.workflow_id},
                    )
        return breaches

    def list_tracked(self) -> list[str]:
        return sorted(self._tracked.keys())
