"""Sprint 16 P1-11: Step compiler subpackage — extracted из monolithic 885 LOC файла.

Каждая группа step'ов изолирована в свой модуль:
- :mod:`activity` — activity/signal_wait/sleep/pause/resume/sensor/agent_invoke
- :mod:`flow` — saga/checkpoint/continue_as_new
- :mod:`governance` — reflect/guardrail/escalate

Этот ``__init__.py`` содержит:
* исключения (Sensor*, Guardrail*),
* ``StepCompiler`` type alias,
* ``_build_retry_policy`` helper,
* ``_STEP_DISPATCH`` registry (импортирует компиляторы из подмодулей),
* ``dispatch_step_compile`` функция-фасад.

Ponytail: 1 type per file, явный dispatch table, zero side effects при import.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from src.backend.core.logging import get_logger

# Re-export исключений и компиляторов из подмодулей.
# Note: submodules are imported for side effects (e.g., `_RESUME_SIGNAL` registration).
from src.backend.dsl.workflow.compiler.step_compilers import (  # noqa: F401
    activity,
    flow,
    governance,
)
from src.backend.dsl.workflow.compiler.step_compilers.activity import (
    _RESUME_SIGNAL,  # noqa: F401 — backward-compat (used by emitter.py)
    compile_activity_step,
    compile_agent_invoke_step,
    compile_pause_step,
    compile_resume_step,
    compile_sensor_step,
    compile_signal_wait_step,
    compile_sleep_step,
)
from src.backend.dsl.workflow.compiler.step_compilers.flow import (
    compile_checkpoint_step,
    compile_continue_as_new_step,
    compile_saga_step,
)
from src.backend.dsl.workflow.compiler.step_compilers.governance import (
    compile_escalate_step,
    compile_guardrail_step,
    compile_reflect_step,
)
from src.backend.dsl.workflow.spec import (
    ActivityDeclaration,
    AgentInvokeDeclaration,
    CheckpointDeclaration,
    ContinueAsNewDeclaration,
    EscalateDeclaration,
    GuardrailDeclaration,
    PauseDeclaration,
    ReflectDeclaration,
    ResumeDeclaration,
    RetryPolicy,
    SagaDeclaration,
    SensorDeclaration,
    SignalWaitDeclaration,
    SleepDeclaration,
    WorkflowStep,
)

# Relative import (avoid Pyright false-positive on long absolute path within
# the same package; runtime resolves both equivalently).
from ..activity_bridge import (
    LANGGRAPH_CHECKPOINT_GET_ACTIVITY,
    LANGGRAPH_CHECKPOINT_PUT_ACTIVITY,
)

# Cycle 33 restore: gateway runtime compilers (P0 #8 + #9).
# Lazy import inside compile_activity_step to avoid circular import at module
# load time (gateways.py imports from spec.py which is already in MRO).
from ..gateways import (  # noqa: F401 — backward-compat re-export
    compile_and,
    compile_or,
    compile_xor,
)

# Layer 6 Workflow Cycle 2 fix: именованные константы для magic
# timeout-чисел (Ponytail D-rule: no magic numbers).
# LangGraph checkpoint I/O activities — обычно быстрые DB calls,
# 10s достаточно для типичной нагрузки.
LANGGRAPH_CHECKPOINT_TIMEOUT_S: int = 10

__all__ = (
    "GuardrailValueTypeError",
    "LANGGRAPH_CHECKPOINT_GET_ACTIVITY",
    "LANGGRAPH_CHECKPOINT_PUT_ACTIVITY",
    "LANGGRAPH_CHECKPOINT_TIMEOUT_S",
    "SensorMaxIterationsError",
    "SensorPollIntervalError",
    "SensorTimeoutRequiredError",
    "StepCompiler",
    "compile_activity_step",
    "compile_agent_invoke_step",
    "compile_checkpoint_step",
    "compile_continue_as_new_step",
    "compile_escalate_step",
    "compile_guardrail_step",
    "compile_pause_step",
    "compile_reflect_step",
    "compile_resume_step",
    "compile_saga_step",
    "compile_sensor_step",
    "compile_signal_wait_step",
    "compile_sleep_step",
    "dispatch_step_compile",
)


_logger = get_logger("workflow.compiler.step_compilers")


# D-A8-10 fix (cycle 1): guards для sensor infinite polling.
_SENSOR_MAX_ITERATIONS_DEFAULT: int = 1000


class SensorTimeoutRequiredError(ValueError):
    """Raised when sensor timeout_s не выставлен (D-A8-10 cycle 1).

    Default-OFF policy: sensor без timeout = infinite polling.
    """


class SensorPollIntervalError(ValueError):
    """Raised when sensor poll_interval_s <= 0 (D-A8-10 cycle 1).

    Tight loop DoS vector — poll_interval_s должно быть > 0.
    """


class SensorMaxIterationsError(RuntimeError):
    """Raised when sensor exceeds max_iterations (D-A8-10 cycle 1).

    Защита от unbounded event history growth в Temporal даже при
    выставленном timeout_s.
    """


# D-A8-07 fix (cycle 1): explicit exception для non-numeric guardrail value.
# Banking context: guardrail на cost/max должен fail-CLOSED, не silently
# PASS при non-numeric value (cost explosion без обнаружения).
class GuardrailValueTypeError(RuntimeError):
    """Raised when guardrail target value не является numeric (int/float).

    Banking-context critical: silent fail-OPEN при non-numeric = cost
    explosion без alerting. D-A8-07 cycle 1 fix.
    """


# Сигнатура компилятора шага: декларация + рантайм-контекст → coroutine.
# ``ctx`` — словарь в котором workflow держит output_key значения,
# семафор сигналов и default-настройки.
StepCompiler = Callable[[Any, dict[str, Any]], Any]


def _build_retry_policy(
    decl_policy: RetryPolicy | None, default_policy: RetryPolicy | None
) -> Any:
    """Сконструировать ``temporalio.common.RetryPolicy`` из декларации.

    Если decl_policy и default_policy оба ``None`` — возвращает ``None``
    (Temporal SDK применит свои дефолты). Lazy-import temporalio.
    """
    policy = decl_policy or default_policy
    if policy is None:
        return None
    from temporalio.common import RetryPolicy as TemporalRetryPolicy

    kwargs: dict[str, Any] = {
        "initial_interval": timedelta(seconds=policy.initial_interval_s),
        "backoff_coefficient": policy.backoff_coefficient,
        "maximum_attempts": policy.max_attempts,
    }
    if policy.maximum_interval_s is not None:
        kwargs["maximum_interval"] = timedelta(seconds=policy.maximum_interval_s)
    if policy.non_retryable_errors:
        kwargs["non_retryable_error_types"] = list(policy.non_retryable_errors)
    if policy.jitter is not None:
        kwargs["jitter"] = policy.jitter
    return TemporalRetryPolicy(**kwargs)


# Sprint 16 P1-11: dispatch registry — single source of truth для step type → compiler.
# All 13 compile функции импортируются из подмодулей (activity/flow/governance).
_STEP_DISPATCH: dict[type, StepCompiler] = {
    ActivityDeclaration: compile_activity_step,
    SagaDeclaration: compile_saga_step,
    SignalWaitDeclaration: compile_signal_wait_step,
    SleepDeclaration: compile_sleep_step,
    PauseDeclaration: compile_pause_step,
    ResumeDeclaration: compile_resume_step,
    SensorDeclaration: compile_sensor_step,
    AgentInvokeDeclaration: compile_agent_invoke_step,
    # S7 fix: 4 advanced declarations registered.
    ReflectDeclaration: compile_reflect_step,
    CheckpointDeclaration: compile_checkpoint_step,
    GuardrailDeclaration: compile_guardrail_step,
    EscalateDeclaration: compile_escalate_step,
    # P1-W1 fix (audit 2026-08-18): wire ContinueAsNewHandler.
    ContinueAsNewDeclaration: compile_continue_as_new_step,
}


async def dispatch_step_compile(step: WorkflowStep, ctx: dict[str, Any]) -> Any:
    """Диспетчер: выбирает компилятор по типу декларации шага.

    Args:
        step: Любой :data:`WorkflowStep`.
        ctx: Рантайм-контекст workflow.

    Returns:
        Результат соответствующего компилятора.

    Raises:
        TypeError: Если тип ``step`` неизвестен (новый step добавлен,
            но компилятор не зарегистрирован).

    """
    compiler = _STEP_DISPATCH.get(type(step))
    if compiler is None:
        raise TypeError(
            f"No step compiler registered for {type(step).__name__}; "
            "did you add a new WorkflowStep without updating step_compilers?"
        )
    return await compiler(step, ctx)
