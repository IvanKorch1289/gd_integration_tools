"""Sprint 16 P1-11: governance step compilers (reflect, guardrail, escalate).

Phases: reflect (procedural memory update), guardrail (PII/quality checks),
escalate (raise severity + audit event).
"""

from __future__ import annotations

# S44 W34: top-level ``from . import GuardrailValueTypeError`` causes
# circular import (step_compilers.__init__ → emitter → step_compilers).
# Use deferred (function-local) import instead.
from datetime import timedelta
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.workflow.spec import (
    EscalateDeclaration,
    GuardrailDeclaration,
    ReflectDeclaration,
)

_logger = get_logger("dsl.workflow.step_compilers.governance")


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
        # S44 W34: function-local import to avoid circular import
        # (step_compilers.__init__ → emitter → step_compilers).
        from src.backend.dsl.workflow.compiler.step_compilers import (
            GuardrailValueTypeError as _GuardrailValueTypeError,
        )
        raise _GuardrailValueTypeError(
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
