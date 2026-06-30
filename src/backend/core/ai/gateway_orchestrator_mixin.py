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

S172 M1.3 (ARC-003 refactor): deduplicated tool-policy enforcement.
Раньше проверка ``enforce_tool_policy()`` вызывалась дважды — после
policy resolution (step 1.5, S168 W9 P0-1 fix) и после prompt render
(step 5, S36-W5 P0-1). Обе делали одно и то же — привели к
единому helper ``_enforce_tool_policy_once()``, который вызывается
один раз между capability check (step 2) и input sanitizers (step 3).
Семантика identical: ``enforced_name = request.tool_name or request.workflow_id``,
``policy.tools.whitelist/blacklist`` — backed by ``tools_policy.enforce_tool_policy``.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from src.backend.core.ai.gateway_audit_mixin import _AuditContext
from src.backend.core.ai.gateway_models import AIRequest, AIResponse
from src.backend.core.logging import get_logger

logger = get_logger(__name__)


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

    def _enforce_tool_policy_once(
        self, request: AIRequest, policy: object | None
    ) -> None:
        """Единая точка enforce tool whitelist/blacklist (S172 M1.3, ARC-003).

        Раньше проверка :func:`enforce_tool_policy` вызывалась дважды —
        после ``_resolve_policy`` (pre-S1) и после ``_render_prompt``
        (S76 W3 follow-up). Обе делали одну и ту же работу, различаясь
        только местом в pipeline. После ARC-003 refactor вызывается
        один раз между capability check (step 2) и input sanitizers (step 3).

        Args:
            request: AIRequest — для извлечения ``tool_name`` / ``workflow_id``.
            policy: :class:`AIPolicySpec` или ``None`` (default policy → no-op).

        Raises:
            ToolPolicyViolationError: При blacklist match или whitelist miss.

        Notes:
            S1 fix semantics сохранены: ``enforced_name = request.tool_name or
            request.workflow_id``. Если whitelist+blacklist пустые — no-op
            (backward-compat с pre-S76 policies).
        """
        if policy is None:
            return
        tools = getattr(policy, "tools", None)
        if tools is None:
            return
        whitelist = getattr(tools, "whitelist", None) or []
        blacklist = getattr(tools, "blacklist", None) or []
        if not whitelist and not blacklist:
            return
        from src.backend.core.ai.policy.enforcer.tools_policy import enforce_tool_policy

        enforced_name = request.tool_name or request.workflow_id
        enforce_tool_policy(enforced_name, tools)

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

        # Шаг 2: capability check (throws CapabilityDeniedError на fail)
        await self._check_capability(request)

        # Шаг 2.5 (S172 M1.3 ARC-003): tool policy enforcement — единожды,
        # сразу после capability check и перед sanitization.
        # (Pre-M1.3: проверка делалась дважды — после step 1 и после step 5.)
        self._enforce_tool_policy_once(request, policy)

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
