"""ADR-0414 — модель аудита шагов workflow (pg-runner).

Модель «шаг workflow для аудита»
--------------------------------

* **Шаг** — переход между событиями event log'а ``step_started`` и
  терминальным исходом (``step_finished`` / ``step_failed`` / отмена
  workflow'а). Именно этот переход — единица аудита; отдельные
  instance-level события (``created`` / ``paused`` / ``resumed``) шагами
  не считаются.
* На шаг эмитится **два** audit-события:

  * ``workflow.step.started`` — на старте шага;
  * ``workflow.step.succeeded`` / ``workflow.step.failed`` /
    ``workflow.step.cancelled`` — на терминальном исходе шага.

* **Метаданные — и только они**: ``route_id``, ``step``, ``tenant``,
  ``attempt``, ``outcome``, ``duration_ms``, ``capability`` и
  ``workflow_id``. Значения данных шага и payload шага в событие
  **не попадают** — тот же принцип «без данных», что в ADR-0401 для
  процессоров DSL.
* **Идемпотентность**: событие старта эмитится **один раз** на пару
  (инстанс, шаг, попытка). Признак «старт уже зафиксирован» — событие
  ``step_started`` с тем же ``idempotency_key`` в event log'е, поэтому
  повторный запуск шага (переpickup инстанста) событие не дублирует.
  Терминальное событие — по той же паре, дедупликация симметричная.
* **Гейт включения**: аудит шагов работает, только если роут объявил
  capability ``audit.write`` (аналог ``audit_event`` у процессоров в
  ADR-0401: нет декларации — нет событий). Проверка — декларация, а не
  runtime-авторизация: аудит пишет сам runner, а не пользовательский
  агент.

References:
* ADR-0401 — аудит процессоров (формат метаданных, принцип «без данных»).
* ADR-0392 — sync-fallback доставки audit-событий (ADR-0392 в ``core/audit``).
"""

from __future__ import annotations

from typing import Any, Final

from src.backend.core.domain.models.workflow_event import WorkflowEventType
from src.backend.core.logging import get_logger
from src.backend.infrastructure.workflow.pg_runner_internals.rows import (
    WorkflowEventRow,
)

__all__ = (
    "AUDIT_CAPABILITY",
    "PHASE_CANCELLED",
    "PHASE_FAILED",
    "PHASE_STARTED",
    "PHASE_SUCCEEDED",
    "emit_step_audit",
    "step_audit_enabled",
    "step_start_logged",
    "step_terminal_logged",
)

_logger = get_logger("workflow.step_audit")

AUDIT_CAPABILITY: Final[str] = "audit.write"
"""Capability, которую роут обязан объявить, чтобы его шаги аудировались."""

PHASE_STARTED: Final[str] = "started"
PHASE_SUCCEEDED: Final[str] = "succeeded"
PHASE_FAILED: Final[str] = "failed"
PHASE_CANCELLED: Final[str] = "cancelled"

_PHASE_EVENTS: Final[dict[str, str]] = {
    PHASE_STARTED: "workflow.step.started",
    PHASE_SUCCEEDED: "workflow.step.succeeded",
    PHASE_FAILED: "workflow.step.failed",
    PHASE_CANCELLED: "workflow.step.cancelled",
}
"""Фаза шага → имя audit-события."""

_TERMINAL_EVENTS: Final[frozenset[WorkflowEventType]] = frozenset(
    {WorkflowEventType.step_finished, WorkflowEventType.step_failed}
)
"""События event log'а, означающие терминальный исход шага."""


def step_audit_enabled(route_id: str) -> bool:
    """Включён ли аудит шагов для роута.

    Критерий — **декларация** capability ``audit.write`` роутом
    (``route.toml`` → ``RouteLoader`` → capability-gate). Runtime-гейт
    авторизации здесь не применяется: событие пишет runner, а не
    пользовательский агент.

    Args:
        route_id: Идентификатор роута (namespace capability-деклараций).

    Returns:
        ``True`` — роут объявил ``audit.write``; ``False`` — не объявил
        (аудит шага не эмитится) либо проверка не удалась.

    """
    if not route_id:
        return False
    try:
        from src.backend.core.security.capabilities.gate import get_capability_gate

        return get_capability_gate().has_declaration(route_id, AUDIT_CAPABILITY)
    except Exception as exc:  # pragma: no cover — аудит не должен ронять шаг
        _logger.debug("workflow.step_audit.capability_check_failed: %s", exc)
        return False


def emit_step_audit(
    *,
    phase: str,
    route_id: str,
    step: str,
    tenant_id: str | None = None,
    attempt: int | None = None,
    duration_ms: float | None = None,
    workflow_id: str | None = None,
) -> bool:
    """Эмитит audit-событие шага workflow (ADR-0414).

    Событие содержит **только метаданные** выполнения шага — значения
    данных шага и его payload в событие не попадают (ADR-0401).

    Ошибка эмиссии никогда не роняет шаг (best-effort, как остальные
    audit-вызовы проекта).

    Args:
        phase: Фаза шага (``started`` / ``succeeded`` / ``failed`` /
            ``cancelled``).
        route_id: Идентификатор роута workflow'а.
        step: Имя шага.
        tenant_id: Tenant workflow-инстанса (``None`` — неизвестен).
        attempt: Номер попытки шага (``None`` — неизвестен).
        duration_ms: Длительность шага в мс (``None`` — не измерена).
        workflow_id: UUID инстанса workflow'а (корреляция события).

    Returns:
        ``True`` — событие эмичено; ``False`` — шаг не аудируется
        (нет декларации ``audit.write``) либо эмиссия не удалась.

    """
    event = _PHASE_EVENTS.get(phase)
    if event is None or not step:
        return False
    if not step_audit_enabled(route_id):
        return False

    details: dict[str, Any] = {
        "route_id": route_id,
        "step": step,
        "outcome": phase,
        "capability": AUDIT_CAPABILITY,
    }
    if tenant_id:
        details["tenant"] = tenant_id
    if attempt is not None:
        details["attempt"] = attempt
    if duration_ms is not None:
        details["duration_ms"] = round(float(duration_ms), 3)
    if workflow_id:
        details["workflow_id"] = workflow_id

    try:
        from src.backend.core.audit.facade import emit_audit

        emit_audit(
            event=event,
            actor=f"workflow_step:{step}",
            resource=f"workflow_step:{step}",
            action="execute",
            outcome=phase,
            details=details,
        )
    except Exception as exc:  # pragma: no cover — аудит не должен ронять шаг
        _logger.debug("workflow.step_audit.emit_failed: %s", exc)
        return False
    return True


def step_start_logged(
    events: list[WorkflowEventRow],
    *,
    step_name: str,
    attempt: int | None = None,
    step_key: str | None = None,
) -> bool:
    """Был ли старт шага уже зафиксирован в event log'е.

    Критерий дедупликации audit-события старта (ADR-0414): событие
    ``step_started`` с тем же ``idempotency_key`` (``step_key``) либо
    с тем же именем шага и номером попытки (legacy-исполнители, у
    которых событие пишет сам executor).

    Args:
        events: События инстанса, прочитанные **до** текущего запуска.
        step_name: Имя шага.
        attempt: Номер попытки шага.
        step_key: Ключ идемпотентности шага (если известен).

    Returns:
        ``True`` — старт шага уже зафиксирован (событие аудита не
        эмитится повторно).

    """
    for event in events:
        if event.event_type != WorkflowEventType.step_started:
            continue
        if step_key is not None:
            if event.payload.get("idempotency_key") == step_key:
                return True
        elif event.step_name == step_name and event.payload.get("attempt") == attempt:
            return True
    return False


def step_terminal_logged(
    events: list[WorkflowEventRow],
    *,
    step_name: str,
    attempt: int | None = None,
    step_key: str | None = None,
) -> bool:
    """Был ли терминальный исход шага уже зафиксирован в event log'е.

    Args:
        events: События инстанса, прочитанные **до** текущего запуска.
        step_name: Имя шага.
        attempt: Номер попытки шага.
        step_key: Ключ идемпотентности шага (если известен).

    Returns:
        ``True`` — терминальный исход уже зафиксирован (событие аудита
        не эмитится повторно).

    """
    for event in events:
        if event.event_type not in _TERMINAL_EVENTS:
            continue
        if step_key is not None and event.payload.get("idempotency_key") == step_key:
            return True
        if event.step_name == step_name and event.payload.get("attempt") == attempt:
            return True
    return False
