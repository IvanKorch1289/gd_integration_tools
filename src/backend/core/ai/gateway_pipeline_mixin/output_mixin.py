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

from typing import TYPE_CHECKING, Any

from src.backend.core.ai.errors import GuardResult
from src.backend.core.ai.gateway_models import AIRequest, AIResponse
from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from src.backend.core.ai.policy.spec import AIPolicySpec

class OutputMixin:
    """output sanitization + guards + LLM gateway (_apply_output_guards, _apply_output_sanitizers, _resolve_llm_gateway) для PipelineStepsMixin. S56 W2 extraction."""

    __slots__ = ()

    async def _apply_output_guards(
        self, response: AIResponse, policy: AIPolicySpec | None
    ) -> list[GuardResult]:
        """Шаг 7: output guards (Llama Guard 3).

        При наличии :class:`AIPolicyEnforcer` с настроенными guards вызывает
        :meth:`AIPolicyEnforcer.guard_output`. Иначе — no-op.

        Args:
            response: Raw completion AIResponse.
            policy: Resolved AIPolicySpec.

        Returns:
            Список :class:`GuardResult` от каждого guard'а.
        """
        if self._policy_enforcer is None or policy is None:
            return []
        if not policy.output_guards:
            return []
        guard = getattr(self._policy_enforcer, "guard_output", None)
        if guard is None:
            return []
        try:
            results = await guard(response, policy)
            return results if results is not None else []
        except NotImplementedError:
            logger.debug(
                "AIGateway: output guards не реализованы (Wave S24 W2 deferred)"
            )
            return []

    async def _apply_output_sanitizers(
        self, response: AIResponse, policy: AIPolicySpec | None
    ) -> AIResponse:
        """Шаг 8: output sanitizers (Presidio + JSONSchema через Outlines).

        Применяет PII-маскировку к ``response.content`` через
        :class:`PresidioSanitizerAdapter`. JSONSchema-валидация структуры
        (Outlines) — Wave S26 W2, в текущем cut'е skip.

        Args:
            response: Raw completion AIResponse.
            policy: Resolved AIPolicySpec.

        Returns:
            AIResponse с sanitized.content + ``pii_detected`` метаданными.
        """
        if not response.content:
            return response

        sanitizer = self._resolve_sanitizer()
        if sanitizer is None:
            return response

        language = self._language_from_policy(policy, default="ru")
        try:
            result = await sanitizer.sanitize_async(response.content, language=language)
        except RuntimeError as exc:
            logger.warning("AIGateway: output sanitize_async недоступен (%s)", exc)
            return response
        except Exception as exc:
            logger.error("AIGateway: output sanitize failed: %s", exc, exc_info=True)
            return response

        replacements = getattr(result, "replacements", {}) or {}
        sanitized_text = getattr(result, "sanitized_text", response.content)
        pii_detected = bool(replacements) or getattr(
            self, "_last_input_pii_detected", False
        )
        return AIResponse(
            content=sanitized_text,
            structured=response.structured,
            tokens_prompt=response.tokens_prompt,
            tokens_completion=response.tokens_completion,
            cost_usd=response.cost_usd,
            model_used=response.model_used,
            pii_detected=pii_detected,
            guardrails_verdict=dict(response.guardrails_verdict),
        )

    def _resolve_llm_gateway(self) -> Any:
        """Lazy-резолв :class:`LiteLLMGateway` через DI singleton."""
        if self._llm_gateway is not None:
            return self._llm_gateway
        from src.backend.services.ai.gateway import get_litellm_gateway

        self._llm_gateway = get_litellm_gateway()
        return self._llm_gateway

