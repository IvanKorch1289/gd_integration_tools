"""K3 S5 W10 — workflow dryrun: симуляция execution без Temporal.

Wave ``[wave:s5/k3-w10-workflow-dryrun]``.

Принимает :class:`WorkflowDeclaration` и input_data, проходит по шагам
последовательно, генерирует JSON-отчёт со списком activities + signals +
timer-fires + state transitions.

Используется в ``manage.py workflow dryrun`` (CLI) и unit-тестах для
golden-snapshot сравнения workflow-декларации.

Feature flag: ``feature_flags.workflow_dryrun_enabled`` (default-OFF).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.workflow.spec import WorkflowDeclaration

__all__ = ("run_workflow_dryrun", "DryRunReport")


DryRunReport = dict[str, Any]


def run_workflow_dryrun(
    declaration: WorkflowDeclaration,
    input_data: dict[str, Any],
) -> DryRunReport:
    """Симулировать выполнение workflow без Temporal.

    Args:
        declaration: Декларация workflow (из YAML/BPMN).
        input_data: Входные данные (передаются первой activity).

    Returns:
        ``DryRunReport`` со полями:
            * ``workflow_name`` — имя workflow;
            * ``version`` — версия декларации;
            * ``activities`` — list[dict] выполненных activity;
            * ``signals`` — list[dict] ожидаемых signals;
            * ``timer_fires`` — list[dict] таймеров;
            * ``state_transitions`` — list[dict] переходов;
            * ``ts`` — timestamp запуска;
            * ``input`` — переданные input_data.
    """
    activities: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    timer_fires: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []

    state = "STARTED"
    transitions.append({"from": None, "to": state, "step": None})

    for idx, step in enumerate(declaration.steps):
        step_type = getattr(step, "type", "unknown")
        step_name = getattr(step, "name", f"step_{idx}")
        next_state = f"STEP_{idx}_RUNNING"
        transitions.append({"from": state, "to": next_state, "step": step_name})
        state = next_state

        match step_type:
            case "activity":
                activities.append(
                    {
                        "step_index": idx,
                        "name": step_name,
                        "activity": step_name,
                        "input_keys": list(input_data.keys()),
                        "timeout_s": getattr(step, "timeout_s", None),
                    }
                )
            case "saga":
                activities.append(
                    {
                        "step_index": idx,
                        "name": step_name,
                        "saga_steps": [
                            getattr(s, "name", "unnamed")
                            for s in (getattr(step, "forward", []) or [])
                        ],
                    }
                )
            case "wait_signal":
                signals.append(
                    {
                        "step_index": idx,
                        "name": step_name,
                        "signal_name": getattr(step, "signal_name", step_name),
                        "timeout_s": getattr(step, "timeout_s", None),
                    }
                )
            case "sleep":
                timer_fires.append(
                    {
                        "step_index": idx,
                        "name": step_name,
                        "duration_s": getattr(step, "duration_s", None),
                    }
                )
            case "sensor":
                activities.append(
                    {
                        "step_index": idx,
                        "name": step_name,
                        "sensor": True,
                        "interval_s": getattr(step, "poll_interval_s", None),
                    }
                )
            case _:
                activities.append(
                    {
                        "step_index": idx,
                        "name": step_name,
                        "type": step_type,
                        "raw": True,
                    }
                )

        completed_state = f"STEP_{idx}_COMPLETED"
        transitions.append(
            {"from": state, "to": completed_state, "step": step_name}
        )
        state = completed_state

    transitions.append({"from": state, "to": "FINISHED", "step": None})

    return {
        "workflow_name": declaration.name,
        "version": declaration.version,
        "activities": activities,
        "signals": signals,
        "timer_fires": timer_fires,
        "state_transitions": transitions,
        "ts": datetime.now(UTC).isoformat(),
        "input": dict(input_data),
    }
