"""Enforced-invoke orchestrator for AIGateway (T-P1.1c).

Extracts :meth:`AIGateway._enforced_invoke` (87 LOC) из ``gateway.py`` в
отдельный mixin. Содержит 9-step pipeline orchestrator + per-step audit
event emission (ADR-0071 §3: requested → policy_resolved → sanitized →
guarded.input → guarded.output → completed|denied|failed).

MRO линеен: ``AIGateway(EnforcedInvokeMixin, PipelineStepsMixin)``.

Пайплайн делегирует individual steps в :class:`PipelineStepsMixin`
(``_resolve_policy``, ``_check_capability``, ``_apply_input_sanitizers``,
``_apply_input_guards``, ``_render_prompt``, ``_invoke_llm``,
``_apply_output_guards``, ``_apply_output_sanitizers``, ``_cost_track``).

Audit-context: импортируется из :mod:`gateway_audit_mixin` (T-P1.1a).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from src.backend.core.ai.gateway_audit_mixin import _AuditContext
from src.backend.core.ai.gateway_models import AIRequest, AIResponse

if TYPE_CHECKING:
    from src.backend.core.ai.gateway_pipeline_mixin import (
        PipelineStepsMixin as _PipelineStepsMixin,
    )
else:
    _PipelineStepsMixin = object

class EnforcedInvokeMixin(_PipelineStepsMixin):
    """9-step pipeline orchestrator (ADR-NEW-19, S25 W1..W5 + S27 W2..W5).

    Mixin (без ``__init__``) — relies on facade для state injection
    (``_audit_service``, ``_policy_resolver`` и т.д.). Пайплайн-шаги —
    в :class:`PipelineStepsMixin`. Audit dataclass — в :mod:`gateway_audit_mixin`.
    """

    async def _enforced_invoke(self, request: AIRequest) -> AIResponse:
        """Полный 9-step pipeline (impl S25 W1..W5 + S27 W2..W5).

        После каждого шага эмитит событие ``ai.invocation.*`` через
        :func:`emit_ai_invocation_event` (ADR-0071 §3):
        ``requested`` → ``policy_resolved`` → ``sanitized`` →
        ``guarded.input`` → ``guarded.output`` → ``completed|denied|failed``.

        Args:
            request: AIRequest.

        Returns:
            AIResponse после прохождения всех 9 шагов.
        """
        # Собираем контекст для аудита
        ctx = _AuditContext(request=request, audit_service=self._audit_service)
        start_ms = int(time.monotonic() * 1000)

        # Шаг 0: emit REQUESTED
        await ctx._emit("requested", latency_ms=int(time.monotonic() * 1000) - start_ms)

        # Шаг 1: policy resolution
        policy = await self._resolve_policy(request)
        ctx.policy = policy
        ctx.policy_name = policy.name if policy else "default"
        await ctx._emit(
            "policy_resolved", latency_ms=int(time.monotonic() * 1000) - start_ms
        )

        # Шаг 1.5 (S168 W9 P0-1): enforce tool policy per AIPolicySpec.tools.
        # ToolsSpec declared in S76, but never wired — agents could call any
        # tool regardless of whitelist/blacklist. Now enforced per
        # ``enforce_tool_policy(tool_name=request.workflow_id, spec=policy.tools)``.
        # on_violation ∈ {fail, warn, block} per spec.
        if policy is not None and getattr(policy, "tools", None) is not None:
            from src.backend.core.ai.policy.enforcer.tools_policy import (
                enforce_tool_policy,
            )
            enforce_tool_policy(request.workflow_id, policy.tools)

        # Шаг 2: capability check (throws CapabilityDeniedError на fail)
        await self._check_capability(request)

        # Шаг 3: input sanitizers
        sanitized = await self._apply_input_sanitizers(request, policy)
        ctx.input_sanitized = sanitized
        ctx.input_pii_detected = getattr(self, "_last_input_pii_detected", False)
        await ctx._emit(
            "sanitized",
            pii_detected=ctx.input_pii_detected,
            latency_ms=int(time.monotonic() * 1000) - start_ms,
        )

        # Шаг 4: input guards
        input_guard_results = await self._apply_input_guards(sanitized, policy)
        ctx.input_guard_results = input_guard_results
        if input_guard_results:
            for gr in input_guard_results:
                await ctx._emit_guard("guarded.input", gr)
        else:
            await ctx._emit(
                "guarded.input", latency_ms=int(time.monotonic() * 1000) - start_ms
            )

        # Шаг 5: render prompt
        rendered = await self._render_prompt(request, policy, sanitized)
        ctx.rendered = rendered

        # Шаг 6: invoke LLM
        completion = await self._invoke_llm(rendered, policy, request.stream)
        ctx.completion = completion
        ctx.model_used = completion.model_used
        ctx.tokens_prompt = completion.tokens_prompt
        ctx.tokens_completion = completion.tokens_completion

        # Шаг 7: output guards
        output_guard_results = await self._apply_output_guards(completion, policy)
        ctx.output_guard_results = output_guard_results
        if output_guard_results:
            for gr in output_guard_results:
                await ctx._emit_guard("guarded.output", gr)
        else:
            await ctx._emit(
                "guarded.output", latency_ms=int(time.monotonic() * 1000) - start_ms
            )

        # Шаг 8: output sanitizers
        sanitized_output = await self._apply_output_sanitizers(completion, policy)

        # Шаг 9a: audit emit (завершающее событие)
        ctx.final_response = sanitized_output
        await ctx._emit_final(start_ms)

        # Шаг 9b: cost track
        await self._cost_track(request, policy, sanitized_output)

        return sanitized_output
