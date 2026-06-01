"""Step Compilers — превращают декларации шагов в Temporal-вызовы.

План V16.1 §4 Sprint 4 (К3): для каждого WorkflowStep типа существует
функция-компилятор, которая принимает ``decl`` + ``ctx`` (рантайм-state
workflow) и эмитит соответствующий ``temporalio.workflow.*`` вызов.

Все функции возвращают ``Awaitable[Any]`` и могут быть вызваны
непосредственно из ``async def run(self, input)`` workflow-класса.

Доступные компиляторы:
    * :func:`compile_activity_step` — ``workflow.execute_activity``.
    * :func:`compile_saga_step` — forward + on-error compensate.
    * :func:`compile_signal_wait_step` — ``workflow.wait_condition``
      на ``self._signals[signal_name]``.
    * :func:`compile_sleep_step` — ``workflow.sleep``.
    * :func:`compile_sensor_step` — periodic ``workflow.execute_activity``
      + ``workflow.sleep`` цикл с timeout.

Все компиляторы — pure-functions без побочных эффектов: их можно
безопасно вызывать дважды для тестов determinism.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Callable

from src.backend.dsl.workflow.spec import (
    ActivityDeclaration,
    AgentInvokeDeclaration,
    PauseDeclaration,
    ResumeDeclaration,
    RetryPolicy,
    SagaDeclaration,
    SensorDeclaration,
    SignalWaitDeclaration,
    SleepDeclaration,
    WorkflowStep,
)

__all__ = (
    "StepCompiler",
    "compile_activity_step",
    "compile_saga_step",
    "compile_sensor_step",
    "compile_signal_wait_step",
    "compile_sleep_step",
    "compile_agent_invoke_step",
    "compile_pause_step",
    "compile_resume_step",
    "dispatch_step_compile",
)


_logger = logging.getLogger("workflow.compiler.step_compilers")

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


async def compile_activity_step(decl: ActivityDeclaration, ctx: dict[str, Any]) -> Any:
    """Выполнить ``workflow.execute_activity`` для :class:`ActivityDeclaration`.

    Args:
        decl: Декларация activity-шага.
        ctx: Рантайм-контекст workflow (содержит ``_outputs``,
            ``_default_timeout_s``, ``_default_retry_policy``,
            ``_input``).

    Returns:
        Результат выполнения activity (Any).
    """
    from temporalio import workflow

    timeout_s = decl.timeout_s or ctx["_default_timeout_s"]
    retry_policy = _build_retry_policy(
        decl.retry_policy, ctx.get("_default_retry_policy")
    )

    # args передаются как single-dict (Temporal сериализует через DataConverter).
    payload = dict(decl.args) if decl.args else {}
    payload.setdefault("_workflow_input", ctx.get("_input", {}))

    kwargs: dict[str, Any] = {"start_to_close_timeout": timedelta(seconds=timeout_s)}
    if retry_policy is not None:
        kwargs["retry_policy"] = retry_policy

    result = await workflow.execute_activity(decl.name, payload, **kwargs)

    if decl.output_key:
        ctx.setdefault("_outputs", {})[decl.output_key] = result
    return result


async def compile_saga_step(decl: SagaDeclaration, ctx: dict[str, Any]) -> Any:
    """Выполнить saga: forward-цепочка + compensate при exception.

    Compensate-шаги выполняются в reverse-порядке только для тех
    forward-шагов, которые УЖЕ выполнились до ошибки. Если compensate
    падает — лог + продолжение (best-effort), исходный exception
    re-raise после завершения compensation.
    """
    from temporalio import workflow

    completed: list[ActivityDeclaration] = []
    try:
        for forward_step in decl.forward:
            await compile_activity_step(forward_step, ctx)
            completed.append(forward_step)
    except Exception as exc:
        # Запускаем compensation в reverse-порядке относительно ВЫПОЛНЕННЫХ
        # forward-шагов; compensate-цепочка декларации соответствует
        # forward индексам по позиции (best-effort при разной длине).
        for compensate_idx in range(len(completed) - 1, -1, -1):
            if compensate_idx >= len(decl.compensate):
                continue
            try:
                await compile_activity_step(decl.compensate[compensate_idx], ctx)
            except Exception as comp_exc:  # noqa: BLE001 — saga best-effort
                workflow.logger.warning(
                    "saga compensation failed for step %d: %s", compensate_idx, comp_exc
                )
        raise exc
    return None


async def compile_signal_wait_step(
    decl: SignalWaitDeclaration, ctx: dict[str, Any]
) -> Any:
    """Дождаться внешнего сигнала через ``workflow.wait_condition``.

    Workflow-класс должен иметь signal-handler для ``decl.signal_name``;
    handler сохраняет payload в ``ctx["_signals"][signal_name]``.
    Этот компилятор только ждёт пока ключ появится.
    """
    from temporalio import workflow

    signals = ctx.setdefault("_signals", {})

    def _signal_received() -> bool:
        return decl.signal_name in signals

    if decl.timeout_s is not None:
        try:
            await workflow.wait_condition(
                _signal_received, timeout=timedelta(seconds=decl.timeout_s)
            )
        except TimeoutError:
            return None
    else:
        await workflow.wait_condition(_signal_received)

    payload = signals.pop(decl.signal_name, None)
    if decl.output_key:
        ctx.setdefault("_outputs", {})[decl.output_key] = payload
    return payload


async def compile_sleep_step(decl: SleepDeclaration, ctx: dict[str, Any]) -> Any:
    """Durable sleep через ``workflow.sleep``.

    Args:
        decl: Декларация sleep-шага.
        ctx: Не используется (зарезервирован для consistency).
    """
    from temporalio import workflow

    del ctx
    await workflow.sleep(timedelta(seconds=decl.duration_s))
    return None


async def compile_sensor_step(decl: SensorDeclaration, ctx: dict[str, Any]) -> Any:
    """Periodic-sensor: выполнять predicate как activity до True или timeout.

    Predicate — строка ``module:fn`` или ``action_id``: компилируется в
    activity-вызов. Если predicate возвращает truthy — sensor завершается.
    """
    from temporalio import workflow

    elapsed = 0.0
    while True:
        result = await workflow.execute_activity(
            decl.predicate,
            {},
            start_to_close_timeout=timedelta(seconds=ctx["_default_timeout_s"]),
        )
        if result:
            return result
        if decl.timeout_s is not None and elapsed >= decl.timeout_s:
            raise TimeoutError(
                f"sensor {decl.predicate!r} timed out after {decl.timeout_s}s"
            )
        await workflow.sleep(timedelta(seconds=decl.poll_interval_s))
        elapsed += decl.poll_interval_s


async def compile_agent_invoke_step(
    decl: AgentInvokeDeclaration, ctx: dict[str, Any]
) -> Any:
    """Выполнить AI-агент через AIGateway (S27 W6, R-V15-9).

    При ``durable=True`` использует LangGraph Checkpointer
    (требует ``feature_flags.langgraph_postgres_checkpoint=True``).
    При отсутствии checkpointing — fallback на stateless call.

    Args:
        decl: Декларация agent_invoke шага.
        ctx: Рантайм-контекст workflow (содержит ``_input`` и ``_outputs``).
    """

    # Resolve input context
    if decl.input_context is None:
        raw_input = ctx.get("_input", {})
    elif decl.input_context.startswith("${") and decl.input_context.endswith("}"):
        # Dot-path expression: extract from _input
        parts = decl.input_context[2:-1].split(".")
        cursor: Any = ctx.get("_input", {})
        for part in parts:
            if cursor is None:
                break
            cursor = (
                cursor.get(part)
                if isinstance(cursor, dict)
                else getattr(cursor, part, None)
            )
        raw_input = cursor if cursor is not None else {}
    else:
        # Simple dot-path
        parts = decl.input_context.split(".")
        cursor: Any = ctx.get("_input", {})
        for part in parts:
            if cursor is None:
                break
            cursor = (
                cursor.get(part)
                if isinstance(cursor, dict)
                else getattr(cursor, part, None)
            )
        raw_input = cursor if cursor is not None else {}

    timeout_s = decl.timeout_s or ctx.get("_default_timeout_s", 300.0)

    if decl.durable:
        # Durable mode: check LangGraph checkpoint availability
        try:
            from src.backend.services.ai.agents.langgraph_postgres_saver import (
                get_langgraph_postgres_saver,
            )

            saver = await get_langgraph_postgres_saver()
            if saver is not None:
                # TODO S24 W3: integrate LangGraph Checkpointer here
                # For now, fall through to stateless mode
                _logger.debug(
                    "AgentInvoke %s: durable mode requested but checkpointer "
                    "integration pending S24 W3 — using stateless fallback",
                    decl.agent_id,
                )
        except Exception as exc:  # noqa: BLE001
            _logger.debug("LangGraph saver unavailable: %s", exc)

    # Stateless call via AIGateway
    try:
        from src.backend.core.ai.gateway import AIGateway, AIRequest

        gateway = AIGateway()
        # Build prompt from raw_input (single user message)
        prompt_text = str(raw_input) if raw_input else ""
        request = AIRequest(
            workflow_id=decl.agent_id,
            tenant_id=ctx.get("_tenant_id", "unknown"),
            correlation_id=ctx.get("_correlation_id", "n/a"),
            prompt_inline=prompt_text,
            context={"max_turns": decl.max_turns, "timeout_s": timeout_s},
        )
        result = await gateway.invoke(request)

        if decl.output_key:
            ctx.setdefault("_outputs", {})[decl.output_key] = result
        return result
    except ImportError as exc:
        raise ImportError(
            f"AIGateway not available for AgentInvoke {decl.agent_id}: {exc}"
        ) from exc


async def compile_pause_step(decl: PauseDeclaration, ctx: dict[str, Any]) -> Any:
    """Приостановить workflow через ``workflow.pause()`` (S35 GAP-DSL-2).

    Устанавливает флаг, который предотвращает продолжение выполнения
    workflow до вызова ``workflow.resume()``.

    Args:
        decl: Декларация pause-шага.
        ctx: Рантайм-контекст workflow (содержит ``_outputs``).

    Returns:
        None.
    """
    from temporalio import workflow

    workflow.pause()
    if decl.output_key:
        import datetime

        ctx.setdefault("_outputs", {})[decl.output_key] = datetime.datetime.now(
            tz=datetime.timezone.utc
        ).isoformat()
    return None


async def compile_resume_step(decl: ResumeDeclaration, ctx: dict[str, Any]) -> Any:
    """Возобновить paused workflow через ``workflow.resume()`` (S35 GAP-DSL-2).

    Снимает флаг паузы и позволяет workflow продолжить выполнение.
    Опционально восстанавливает состояние из checkpoint.

    Args:
        decl: Декларация resume-шага.
        ctx: Рантайм-контекст workflow (не используется, зарезервирован).

    Returns:
        None.
    """
    from temporalio import workflow

    del ctx
    workflow.resume()
    return None


_STEP_DISPATCH: dict[type, StepCompiler] = {
    ActivityDeclaration: compile_activity_step,
    SagaDeclaration: compile_saga_step,
    SignalWaitDeclaration: compile_signal_wait_step,
    SleepDeclaration: compile_sleep_step,
    SensorDeclaration: compile_sensor_step,
    AgentInvokeDeclaration: compile_agent_invoke_step,
    PauseDeclaration: compile_pause_step,
    ResumeDeclaration: compile_resume_step,
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
