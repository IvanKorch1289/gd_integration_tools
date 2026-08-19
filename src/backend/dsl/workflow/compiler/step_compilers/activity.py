"""Sprint 16 P1-11: activity-related step compilers.

Phases: activity, signal_wait, sleep, pause, resume, sensor, agent_invoke.
"""
from __future__ import annotations

# ruff: noqa: F821 — shared symbols (exceptions, _build_retry_policy) defined in __init__.py
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.workflow.compiler.gateways import (  # noqa: E402
    compile_and,
    compile_or,
    compile_xor,
)
from src.backend.dsl.workflow.spec import (
    ActivityDeclaration,
    AgentInvokeDeclaration,
    PauseDeclaration,
    ResumeDeclaration,
    SensorDeclaration,
    SignalWaitDeclaration,
    SleepDeclaration,
)

_logger = get_logger("dsl.workflow.step_compilers.activity")


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
    # Cycle 33 restore: BPMN gateway markers (XOR/AND/OR) приходят как
    # ActivityDeclaration с args["gateway"] = GatewaySpec (live or dict).
    # Cycle 3 fail-fast (NotImplementedError) заменён на dispatch в
    # runtime-компиляторы compile_xor/and/or из :mod:`.gateways`.
    # Проверяем ДО temporalio import — fail-fast для неподдерживаемых kind.
    #
    # Поддерживаем оба типа payload: live GatewaySpec instance (от
    # WorkflowBuilder.gateway_xor/and/or) + dict (от bpmn_importer).
    if decl.args and "gateway" in decl.args:
        gw = decl.args["gateway"]
        gw_kind: str | None = getattr(gw, "kind", None)
        if gw_kind is None and isinstance(gw, dict):
            gw_kind_raw = gw.get("kind")
            gw_kind = gw_kind_raw if isinstance(gw_kind_raw, str) else None
        if gw_kind == "xor":
            return await compile_xor(decl, ctx)
        if gw_kind == "and":
            return await compile_and(decl, ctx)
        if gw_kind == "or":
            return await compile_or(decl, ctx)
        # Unknown kind → fall through to normal activity compile (will fail
        # at Temporal layer with "activity not found"). This preserves the
        # pre-cycle-33 behavior of treating non-gateway activity args as
        # regular activity payloads.

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
            # Cycle 27 H1: default behavior is "raise" (fail-loud).
            # Operators must explicitly set on_timeout="continue" for
            # legacy silent-skip behavior.
            workflow.logger.warning(
                "wait_signal timeout: signal %r not received within %ss; on_timeout=%r",
                decl.signal_name,
                decl.timeout_s,
                decl.on_timeout,
            )
            if decl.on_timeout == "raise":
                raise TimeoutError(
                    f"wait_signal: signal {decl.signal_name!r} not received "
                    f"within {decl.timeout_s}s"
                ) from None
            # "continue" branch: return None, downstream MUST handle None
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


_RESUME_SIGNAL = "__dsl_resume__"


async def compile_pause_step(decl: PauseDeclaration, ctx: dict[str, Any]) -> Any:
    """Приостановить workflow до внешнего resume-signal.

    Temporal Python SDK не имеет ``workflow.pause()``. Durable pause реализован
    через ``workflow.wait_condition``; emitter регистрирует signal-handler с
    именем :data:`_RESUME_SIGNAL` для workflow, содержащих pause-step.
    """
    from temporalio import workflow

    signals = ctx.setdefault("_signals", {})
    await workflow.wait_condition(lambda: _RESUME_SIGNAL in signals)
    signals.pop(_RESUME_SIGNAL, None)
    if decl.output_key:
        pause_ts = workflow.now()
        ctx.setdefault("_outputs", {})[decl.output_key] = pause_ts.isoformat()
    return None


async def compile_resume_step(decl: ResumeDeclaration, ctx: dict[str, Any]) -> Any:
    """Подтвердить обработку внешнего resume-signal.

    Само возобновление выполняет signal-handler, разблокирующий pause-step;
    declaration-step очищает возможный дубликат сигнала детерминированно.
    """
    del decl
    ctx.setdefault("_signals", {}).pop(_RESUME_SIGNAL, None)
    return None


async def compile_sensor_step(decl: SensorDeclaration, ctx: dict[str, Any]) -> Any:
    """Periodic-sensor: выполнять predicate как activity до True или timeout.

    Predicate — строка ``module:fn`` или ``action_id``: компилируется в
    activity-вызов. Если predicate возвращает truthy — sensor завершается.

    D-A8-10 fix (cycle 1): защита от infinite polling. Три проверки:
    1. timeout_s обязателен (default-OFF: None → fail-fast SensorTimeoutRequiredError).
    2. poll_interval_s > 0 (иначе tight loop → CPU saturation, DoS vector).
    3. max_iterations cap (default 1000) — защита от unbounded event history
       growth в Temporal даже при timeout.
    """
    from temporalio import workflow

    # D-A8-10 fix (cycle 1): validation guards.
    if decl.timeout_s is None:
        raise SensorTimeoutRequiredError(
            f"sensor {decl.predicate!r} requires explicit timeout_s "
            f"(D-A8-10 cycle 1 — default-OFF, иначе infinite polling)."
        )
    if decl.poll_interval_s <= 0:
        raise SensorPollIntervalError(
            f"sensor {decl.predicate!r} poll_interval_s={decl.poll_interval_s} "
            f"must be > 0 (D-A8-10 cycle 1 — иначе tight loop DoS)."
        )
    max_iterations = _SENSOR_MAX_ITERATIONS_DEFAULT
    elapsed = 0.0
    iterations = 0
    while True:
        iterations += 1
        if iterations > max_iterations:
            # D-A8-10 fix (cycle 1): iteration cap защищает от unbounded
            # event history growth в Temporal даже при выставленном timeout.
            raise SensorMaxIterationsError(
                f"sensor {decl.predicate!r} exceeded max_iterations={max_iterations} "
                f"(elapsed={elapsed}s, timeout_s={decl.timeout_s}s) "
                f"(D-A8-10 cycle 1)."
            )
        result = await workflow.execute_activity(
            decl.predicate,
            {},
            start_to_close_timeout=timedelta(seconds=ctx["_default_timeout_s"]),
        )
        if result:
            return result
        if elapsed >= decl.timeout_s:
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
        cursor = ctx.get("_input", {})
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

    # Stateless call via AIGateway as Temporal activity (sandbox-safe)
    from temporalio import workflow

    prompt_text = str(raw_input) if raw_input else ""
    payload = {
        "workflow_id": decl.agent_id,
        "tenant_id": ctx.get("_tenant_id", "unknown"),
        "correlation_id": ctx.get("_correlation_id", "n/a"),
        "prompt_inline": prompt_text,
        "context": {"max_turns": decl.max_turns, "timeout_s": timeout_s},
    }

    if decl.durable:
        # Durable mode: thread-scoped checkpoint via LangGraph Checkpointer
        # activities (S100 W1). DB I/O is sandbox-safe because it lives in
        # activities, NOT in workflow code.
        correlation_id = ctx.get("_correlation_id", "n/a")
        thread_id = f"{decl.agent_id}:{correlation_id}"

        # Best-effort: load prior state. None = saver unavailable OR first run.
        prior = await workflow.execute_activity(
            LANGGRAPH_CHECKPOINT_GET_ACTIVITY,
            thread_id,
            start_to_close_timeout=timedelta(seconds=LANGGRAPH_CHECKPOINT_TIMEOUT_S),
        )
        if prior is not None:
            _logger.debug(
                "AgentInvoke %s: resuming thread %s (prior checkpoint found)",
                decl.agent_id,
                thread_id,
            )
        # Always call agent (durable mode = checkpoint around, not skip).
        result = await workflow.execute_activity(
            "_agent_invoke",
            payload,
            start_to_close_timeout=timedelta(seconds=timeout_s),
        )
        # Best-effort persist. Failure does NOT break the workflow —
        # durable mode degrades to stateless when saver is unavailable.
        state_to_persist: dict[str, Any] = {
            "thread_id": thread_id,
            "agent_id": decl.agent_id,
            "tenant_id": ctx.get("_tenant_id", "unknown"),
            "prior_summary": str(prior)[:500] if prior else None,
            "output_summary": str(result)[:1000],
            "ts": correlation_id,
        }
        await workflow.execute_activity(
            LANGGRAPH_CHECKPOINT_PUT_ACTIVITY,
            state_to_persist,
            start_to_close_timeout=timedelta(seconds=LANGGRAPH_CHECKPOINT_TIMEOUT_S),
        )
    else:
        result = await workflow.execute_activity(
            "_agent_invoke",
            payload,
            start_to_close_timeout=timedelta(seconds=timeout_s),
        )

    if decl.output_key:
        ctx.setdefault("_outputs", {})[decl.output_key] = result
    return result


# S7 fix (S36-W8): добавлены 4 step-compilers для advanced declarations
# (ReflectDeclaration, CheckpointDeclaration, GuardrailDeclaration,
# EscalateDeclaration). До этого dispatch_step_compile() выбрасывал
# TypeError при попытке скомпилировать эти шаги — они были declared
# в advanced_declarations.py и accepted by WorkflowDeclaration (через
# Annotated union), но не имели компиляторов.


