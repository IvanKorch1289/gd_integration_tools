"""Sprint 16 P1-11: flow-control step compilers (saga, checkpoint, continue_as_new).

Phases: saga (forward + on-error compensate), checkpoint (state snapshot),
continue_as_new (Temporal Event History reset).
"""

from __future__ import annotations

# ruff: noqa: F821 — shared symbols (exceptions, _build_retry_policy) defined in __init__.py
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.workflow.spec import (
    CheckpointDeclaration,
    ContinueAsNewDeclaration,
    SagaDeclaration,
)

_logger = get_logger("dsl.workflow.step_compilers.flow")


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
                    "saga compensate_map references unknown forward step: %s", fwd_name
                )
                continue
            # comp_name must reference an ActivityDeclaration in compensate[]
            comp_step = next((s for s in decl.compensate if s.name == comp_name), None)
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
                    "saga compensation failed for step %s: %s", comp_step.name, comp_exc
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
    from temporalio import workflow

    # Sprint 8 P1-2: use Temporal deterministic workflow.uuid4() instead of
    # stdlib uuid.uuid4() — гарантирует одинаковый UUID при replay.
    # stdlib uuid даёт разные UUID при каждом replay → nondeterminism error.
    checkpoint_id = decl.checkpoint_id or str(workflow.uuid4())
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


async def compile_continue_as_new_step(
    decl: ContinueAsNewDeclaration, ctx: dict[str, Any]
) -> Any:
    """Continue-As-New шаг: пересоздать execution с чистой историей (D169).

    P1-W1 fix (audit 2026-08-18): wire существующего
    :class:`ContinueAsNewHandler` в workflow runtime.

    Без этого шага WorkflowContinueAsNewProcessor ставил marker в exchange,
    но никто его не читал — Temporal ``workflow.continue_as_new()`` НЕ вызывался.
    Теперь DSL может декларировать ``- type: continue_as_new`` прямо в
    ``WorkflowDeclaration.steps`` — handler wired и Temporal API вызывается.

    Args:
        decl: ContinueAsNewDeclaration (same_workflow_id, same_input, search_attributes).
        ctx: Runtime-context workflow (нужен ``_input`` для same_input).

    Returns:
        ``{"continued_as_new": True, "same_workflow_id": bool, ...}``.

    Raises:
        ImportError: Если temporalio не установлен.

    """
    from src.backend.dsl.workflow.handlers.continue_as_new_handler import (
        ContinueAsNewHandler,
    )

    handler = ContinueAsNewHandler()
    marker = {
        "requested": True,
        "same_workflow_id": decl.same_workflow_id,
        "same_input": decl.same_input,
        "search_attributes": decl.search_attributes,
    }
    # same_input=True → передаём текущий input workflow, иначе пустой dict.
    current_input = ctx.get("_input") if decl.same_input else None
    handler.perform_continue(marker, current_input=current_input)
    _logger.info(
        "workflow continue_as_new invoked same_wf_id=%s same_input=%s sa=%d",
        decl.same_workflow_id,
        decl.same_input,
        len(decl.search_attributes),
    )
    return {
        "continued_as_new": True,
        "same_workflow_id": decl.same_workflow_id,
        "same_input": decl.same_input,
    }
