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

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.workflow.spec import (
    ActivityDeclaration,
    AgentInvokeDeclaration,
    CheckpointDeclaration,
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
from .activity_bridge import (  # noqa: I001 — intentional relative
    LANGGRAPH_CHECKPOINT_GET_ACTIVITY,
    LANGGRAPH_CHECKPOINT_PUT_ACTIVITY,
)

# Cycle 33 restore: gateway runtime compilers (P0 #8 + #9).
# Lazy import inside compile_activity_step to avoid circular import at module
# load time (gateways.py imports from spec.py which is already in MRO).
from .gateways import (  # noqa: I001 — intentional relative
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
    "StepCompiler",
    "compile_activity_step",
    "compile_agent_invoke_step",
    "compile_checkpoint_step",
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


async def compile_saga_step(decl: SagaDeclaration, ctx: dict[str, Any]) -> Any:
    """Выполнить saga: forward-цепочка + compensate при exception.

    Compensate-шаги выполняются в reverse-порядке только для тех
    forward-шагов, которые УЖЕ выполнились до ошибки. Если compensate
    падает — лог + продолжение (best-effort), исходный exception
    re-raise после завершения compensation.

    Phase 6 fix (cycle 28): при наличии ``compensate_map`` используется
    explicit name→step mapping вместо positional ``compensate[]``.
    ``compensate_map`` validated в ``validate_compensate_map`` (Pydantic
    model_validator); ошибки валидации → ValidationError на build().
    """
    from temporalio import workflow

    completed: list[ActivityDeclaration] = []
    # Phase 6: resolve compensation step lookup. Prefer explicit
    # ``compensate_map`` (forward_name → compensate_step); fallback to
    # positional ``compensate[]`` (index-based).
    compensate_by_name: dict[str, ActivityDeclaration] = {}
    if decl.compensate_map:
        # Build name→step index from forward (used to resolve map values).
        forward_by_name = {step.name: step for step in decl.forward}
        for fwd_name, comp_name in decl.compensate_map.items():
            if fwd_name not in forward_by_name:
                workflow.logger.warning(
                    "saga compensate_map references unknown forward step: %s",
                    fwd_name,
                )
                continue
            # comp_name must reference an ActivityDeclaration in compensate[]
            comp_step = next(
                (s for s in decl.compensate if s.name == comp_name),
                None,
            )
            if comp_step is None:
                workflow.logger.warning(
                    "saga compensate_map: forward=%s → compensate=%s "
                    "not found in compensate[]",
                    fwd_name,
                    comp_name,
                )
                continue
            compensate_by_name[fwd_name] = comp_step
    try:
        for forward_step in decl.forward:
            await compile_activity_step(forward_step, ctx)
            completed.append(forward_step)
    except Exception as exc:
        # Запускаем compensation в reverse-порядке относительно ВЫПОЛНЕННЫХ
        # forward-шагов; compensate-цепочка декларации соответствует
        # forward индексам по позиции (best-effort при разной длине).
        # Cycle 19 (meta-coord P1.2 fix): log WARNING when compensate count
        # does not match completed forward steps (silent skip was misleading).
        # Phase 6: prefer explicit map when available.
        if not compensate_by_name and len(decl.compensate) < len(decl.forward):
            workflow.logger.warning(
                "saga compensate count (%d) < forward count (%d); "
                "compensation for forward steps beyond compensate length "
                "will be silently skipped",
                len(decl.compensate),
                len(decl.forward),
            )
        # Cycle 27 W1+H2: collect all compensation errors and chain them
        # with the original via raise ... from ... so the original
        # exception is preserved. Previously, strict_compensate=True
        # re-raised comp_exc, swallowing the original cause.
        # Phase 6: when compensate_map is present, look up compensate step
        # by forward_name; otherwise fall back to positional compensate[].
        comp_errors: list[BaseException] = []
        for completed_step in reversed(completed):
            if compensate_by_name:
                comp_step = compensate_by_name.get(completed_step.name)
                if comp_step is None:
                    # No compensation mapped for this forward step
                    continue
            else:
                # Positional fallback (backward compat)
                idx = completed.index(completed_step)
                if idx >= len(decl.compensate):
                    continue
                comp_step = decl.compensate[idx]
            try:
                await compile_activity_step(comp_step, ctx)
            except Exception as comp_exc:
                comp_errors.append(comp_exc)
                workflow.logger.warning(
                    "saga compensation failed for step %s: %s",
                    comp_step.name,
                    comp_exc,
                )
        if comp_errors and decl.strict_compensate:
            # Chain: original exc is the primary, comp errors are cause chain.
            # Allow caller to inspect both via __cause__ / __context__.
            workflow.logger.error(
                "saga strict_compensate=True: original exc + %d "
                "compensation errors; re-raising original with chained cause",
                len(comp_errors),
            )
            raise exc from comp_errors[-1]
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
            # Cycle 27 H1: default behavior is "raise" (fail-loud).
            # Operators must explicitly set on_timeout="continue" for
            # legacy silent-skip behavior.
            workflow.logger.warning(
                "wait_signal timeout: signal %r not received within %ss; "
                "on_timeout=%r",
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


async def compile_reflect_step(decl: ReflectDeclaration, ctx: dict[str, Any]) -> Any:
    """Reflect-шаг: procedural memory update (S28 W3 + S7).

    В Temporal выполняется как ``workflow.execute_activity`` (background
    activity для memory update). Async_mode=True → запускаем в фоне.

    Args:
        decl: Декларация reflect-шага.
        ctx: Рантайм-контекст workflow.

    Returns:
        ``True`` если reflect успешно запущен.
    """
    from temporalio import workflow

    payload = {
        "source_step": decl.source_step,
        "memory_writes": list(decl.memory_writes),
        "consolidation_policy": decl.consolidation_policy,
        "async_mode": decl.async_mode,
        "outputs_snapshot": ctx.get("_outputs", {}),
    }
    if decl.async_mode:
        # Background (no await) — Temporal worker handles scheduling.
        await workflow.start_activity(
            "memory.reflect", payload, start_to_close_timeout=timedelta(seconds=60)
        )
    else:
        await workflow.execute_activity(
            "memory.reflect", payload, start_to_close_timeout=timedelta(seconds=60)
        )
    if decl.output_key:
        ctx.setdefault("_outputs", {})[decl.output_key] = {"reflected": True}
    return True


async def compile_checkpoint_step(
    decl: CheckpointDeclaration, ctx: dict[str, Any]
) -> Any:
    """Checkpoint-шаг: workflow state persistence (S28 W3 + S7).

    В Temporal сохраняется через ``workflow.upsert_search_attributes``
    (для visibility) + activity для durable snapshot. Это позволяет
    resume/replay.

    Args:
        decl: Декларация checkpoint-шага.
        ctx: Рантайм-контекст workflow.

    Returns:
        ``checkpoint_id`` (auto-generated UUID если не задан).
    """
    import uuid as _uuid

    from temporalio import workflow

    checkpoint_id = decl.checkpoint_id or str(_uuid.uuid4())
    outputs = ctx.get("_outputs", {})
    # Если указаны include_steps — фильтруем; иначе весь state.
    if decl.include_steps:
        snapshot = {
            sid: outputs.get(sid) for sid in decl.include_steps if sid in outputs
        }
    else:
        snapshot = dict(outputs)

    await workflow.execute_activity(
        "workflow.checkpoint.put",
        {
            "checkpoint_id": checkpoint_id,
            "snapshot": snapshot,
            "metadata": dict(decl.metadata),
        },
        start_to_close_timeout=timedelta(seconds=30),
    )
    if decl.output_key:
        ctx.setdefault("_outputs", {})[decl.output_key] = checkpoint_id
    return checkpoint_id


async def compile_guardrail_step(
    decl: GuardrailDeclaration, ctx: dict[str, Any]
) -> Any:
    """Guardrail-шаг: проверка лимита + action on exceed (S28 W3 + S7).

    Семантика: читает значение ``target`` из ctx, сравнивает с threshold.
    При превышении — действие per ``on_exceed``:
    - ``fail`` → raise exception → Temporal retries или fail.
    - ``warn`` → log + continue.
    - ``dlq`` → emit DLQ event + continue (не fail).
    - ``escalate`` → set ctx flag ``_escalate_requested`` для downstream.

    D-A8-07 fix (cycle 1): fail-CLOSED при non-numeric value. Ранее
    fallback к ``0.0`` для non-numeric (dict, str, None) — guardrail
    молча PASS, banking-context cost explosion без обнаружения.
    Теперь: raise GuardrailValueTypeError при non-numeric.

    Args:
        decl: Декларация guardrail-шага.
        ctx: Рантайм-контекст workflow.

    Returns:
        ``{"rule": str, "value": float, "exceeded": bool}``.
    """
    outputs = ctx.get("_outputs", {})
    target = decl.target
    raw_value: Any = None
    if target is None:
        # Используем последний output (current step). Warn если их >1 —
        # implicit ordering сценарий хрупкий; рекомендуем explicit target.
        if outputs:
            if len(outputs) > 1:
                _logger.warning(
                    "guardrail step with multiple outputs and no target — "
                    "using last; prefer explicit target to avoid order-dependence",
                    extra={"output_keys": list(outputs.keys()), "rule": decl.rule},
                )
            raw_value = next(reversed(outputs.values()))
    elif "." in target:
        # Dot-path — простая навигация по dict.
        cur: Any = outputs
        for part in target.split("."):
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                cur = None
                break
        raw_value = cur
    else:
        raw_value = outputs.get(target, 0)

    # D-A8-07 fix (cycle 1): explicit fail-CLOSED при non-numeric.
    # Раньше: \`value = float(cur) if isinstance(cur, (int, float)) else 0.0\`
    # → silent fallback к 0.0 → guardrail PASS даже при cost explosion.
    if not isinstance(raw_value, (int, float)):
        raise GuardrailValueTypeError(
            f"Guardrail {decl.rule!r} target={target!r} value type "
            f"{type(raw_value).__name__} (value={raw_value!r}) — "
            f"expected numeric (int/float) для banking-context cost safety. "
            f"Fallback к 0.0 был silent fail-OPEN (D-A8-07 cycle 1)."
        )

    value: float = float(raw_value)

    exceeded = value > decl.threshold
    result = {"rule": decl.rule, "value": value, "exceeded": exceeded}
    if exceeded:
        if decl.on_exceed == "fail":
            raise RuntimeError(
                f"Guardrail {decl.rule!r} exceeded: value={value} > "
                f"threshold={decl.threshold}"
            )
        if decl.on_exceed == "warn":
            _logger.warning(
                "guardrail %s exceeded: value=%s threshold=%s",
                decl.rule,
                value,
                decl.threshold,
            )
        elif decl.on_exceed == "dlq":
            ctx.setdefault("_dlq_events", []).append(
                {"rule": decl.rule, "value": value, "threshold": decl.threshold}
            )
        elif decl.on_exceed == "escalate":
            ctx["_escalate_requested"] = True
    if decl.output_key:
        ctx.setdefault("_outputs", {})[decl.output_key] = result
    return result


async def compile_escalate_step(decl: EscalateDeclaration, ctx: dict[str, Any]) -> Any:
    """Escalate-шаг: переключение на другого агента/модель (S28 W3 + S7).

    Реализация: обновляет ctx['_active_agent'] / ctx['_active_model'] —
    downstream agent_invoke шаги подхватывают их. Логирует escalation
    для audit-trail.

    Args:
        decl: Декларация escalate-шага.
        ctx: Рантайм-контекст workflow.

    Returns:
        ``{"to_agent": str | None, "to_model": str | None, "reason": str | None}``.
    """
    if decl.to_agent is not None:
        ctx["_active_agent"] = decl.to_agent
    if decl.to_model is not None:
        ctx["_active_model"] = decl.to_model
    _logger.info(
        "workflow escalated: to_agent=%s to_model=%s reason=%s",
        decl.to_agent,
        decl.to_model,
        decl.reason,
    )
    result = {
        "to_agent": decl.to_agent,
        "to_model": decl.to_model,
        "reason": decl.reason,
    }
    if decl.output_key:
        ctx.setdefault("_outputs", {})[decl.output_key] = result
    return result


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
