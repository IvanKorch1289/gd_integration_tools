from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass  # cross-mixin / state attrs declared below

"""PipelineStepsMixin для :class:`AIGateway` (S38 P1.1b, v9 P1 split).

Извлечено из ``core/ai/gateway.py`` в рамках T-P1.1b (v9 P1 God-объекты
split, Variant C mixin, maximal scope) для уменьшения god-файла
(939 → ~250 LOC facade + 600 LOC mixin).

Mixin содержит 9-step pipeline methods (policy resolve, capability check,
input/output sanitizers, input/output guards, render prompt, invoke LLM,
audit emit, cost track) + 5 helpers (resolvers + static utilities).

Composition::

    class AIGateway(PipelineStepsMixin, AuditContextMixin):
        def __init__(self, ...): ...   # facade owns init/state
        async def invoke(self, request): ...   # entry point
        async def _enforced_invoke(self, request): ...   # orchestrator

Mixin не имеет ``__init__`` — relies on facade's ``__init__`` для ``self._X`` attrs.

См. также:
* :class:`AIGateway` — :mod:`core.ai.gateway` (ADR-NEW-19);
* :class:`AuditContextMixin` — :mod:`core.ai.gateway_audit_mixin`.
"""

from typing import TYPE_CHECKING

from src.backend.core.ai.gateway_models import AIRequest, AIResponse

if TYPE_CHECKING:
    from src.backend.core.ai.policy.spec import AIPolicySpec


class ObservabilityMixin:
    """audit + cost tracking (_audit_emit, _cost_track) для PipelineStepsMixin. S56 W2 extraction."""

    __slots__ = ()

    async def _audit_emit(
        self, request: AIRequest, policy: AIPolicySpec | None, response: AIResponse
    ) -> None:
        """Шаг 9a: Audit emit через Unified :class:`AuditService`.

        Эмитит событие ``ai.invocation.completed`` (либо ``failed``) в
        ClickHouse через ``audit_events`` таблицу. При отсутствии
        :class:`AuditService` — резолвится singleton'ом
        :func:`get_unified_audit_service`.

        Args:
            request: AIRequest.
            policy: Resolved AIPolicySpec.
            response: Sanitized AIResponse.
        """
        audit = self._audit_service
        if audit is None:
            try:
                from src.backend.services.audit.audit_service import (
                    get_unified_audit_service,
                )

                audit = get_unified_audit_service()
            except Exception as exc:
                logger.debug("AIGateway: AuditService недоступен (%s)", exc)
                return

        policy_name = policy.name if policy is not None else "default"
        details: dict[str, Any] = {
            "workflow_id": request.workflow_id,
            "policy": policy_name,
            "model_used": response.model_used,
            "tokens_prompt": response.tokens_prompt,
            "tokens_completion": response.tokens_completion,
            "cost_usd": response.cost_usd,
            "pii_detected": response.pii_detected,
            "guardrails_verdict": dict(response.guardrails_verdict),
        }
        if policy is not None:
            details.update(dict(policy.audit.extra_attrs))

        try:
            await audit.emit(
                event="ai.invocation.completed",
                actor=f"tenant:{request.tenant_id}",
                resource=f"ai_workflow:{request.workflow_id}",
                action="invoke",
                outcome="success",
                severity="info",
                correlation_id=request.correlation_id,
                tenant_id=request.tenant_id,
                route_name=request.workflow_id,
                details=details,
            )
        except Exception as exc:
            logger.warning("AIGateway: audit emit failed: %s", exc)

    async def _cost_track(
        self, request: AIRequest, policy: AIPolicySpec | None, response: AIResponse
    ) -> None:
        """Шаг 9b: Cost-tracker (Langfuse v3 OTel + Prometheus).

        При наличии ``cost_tracker`` вызывает ``record_cost`` /
        ``record_tokens``. При отсутствии — no-op (LangFuse callback
        уже подписан на ``litellm.success_callback`` через
        :class:`CostTrackingCallback`).

        Args:
            request: AIRequest.
            policy: Resolved AIPolicySpec (для budget enforce — Wave S25 W5).
            response: AIResponse с tokens + cost_usd.
        """
        del policy
        tracker = self._cost_tracker
        if tracker is None:
            return
        record_cost = getattr(tracker, "record_cost", None)
        record_tokens = getattr(tracker, "record_tokens", None)
        try:
            if record_cost is not None and response.cost_usd > 0:
                record_cost(
                    provider=self._provider_from_model(response.model_used),
                    model=response.model_used,
                    cost_usd=response.cost_usd,
                )
            if record_tokens is not None:
                record_tokens(
                    provider=self._provider_from_model(response.model_used),
                    model=response.model_used,
                    input_tokens=response.tokens_prompt,
                    output_tokens=response.tokens_completion,
                )
        except Exception as exc:
            logger.debug("AIGateway: cost-track failed: %s", exc)
