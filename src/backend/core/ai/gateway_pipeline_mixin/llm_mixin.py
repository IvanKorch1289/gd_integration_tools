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

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.core.ai.gateway_models import AIRequest, AIResponse
from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from src.backend.core.ai.policy.spec import AIPolicySpec

logger = get_logger(__name__)


class LlmInvocationMixin:
    """LLM invocation (_render_prompt, _invoke_llm, _extract_completion, _provider_from_model) для PipelineStepsMixin. S56 W2 extraction."""

    __slots__ = ()

    async def _render_prompt(
        self, request: AIRequest, policy: AIPolicySpec | None, sanitized: str
    ) -> str:
        """Шаг 5: PromptRenderer (Langfuse + tiktoken trim) + context strategy.

        gap-ai-8: при наличии ``policy.budget`` применяет context strategy
        (rolling_window / map_reduce / hierarchical) для управления размером
        conversation history в рамках ``budget.max_tokens_prompt``.

        Для полной поддержки multi-message strategies необходимо чтобы
        ``request.messages`` содержал историю (list[ContextMessage]).
        При отсутствии — применяется string-level tiktoken truncation.

        Args:
            request: AIRequest.
            policy: Resolved AIPolicySpec (для budget).
            sanitized: Sanitized prompt после шага 3.

        Returns:
            Rendered prompt после template + budget trim + context strategy.
        """
        from src.backend.core.ai.context_strategy import get_context_strategy
        from src.backend.core.config.features import feature_flags

        prompt = sanitized

        if feature_flags.prompt_registry_gateway_wiring and request.prompt_ref:
            try:
                from src.backend.services.ai.prompt_registry import get_prompt_registry

                registry = get_prompt_registry()
                compiled = await registry.get_compiled(
                    request.prompt_ref,
                    version=None,
                    label="production",
                    variables=request.context,
                )
                prompt = compiled
            except Exception as exc:
                logger.debug(
                    "PromptRegistry lookup failed for %s: %s", request.prompt_ref, exc
                )

        budget_spec = policy.budget if policy else None
        if budget_spec is None:
            return prompt

        limit = budget_spec.max_tokens_prompt
        strategy_type = getattr(budget_spec, "context_strategy", "rolling_window")

        enc = None
        try:
            import tiktoken

            enc = tiktoken.get_encoding("cl100k_base")

            def count_tokens(text: str) -> int:
                return len(enc.encode(text))
        except Exception as _:
            # Rough fallback: ~4 chars per token
            def count_tokens(text: str) -> int:
                return max(1, len(text) // 4)

        total_tokens = count_tokens(prompt)
        if total_tokens <= limit:
            return prompt

        # String-level truncation: keep start + end (best for most prompts)
        # This is the fallback; full strategy requires request.messages
        logger.debug(
            "Prompt %d tokens exceeds budget %d, truncating", total_tokens, limit
        )

        try:
            get_context_strategy(strategy_type)
        except Exception as _:
            pass

            # Fallback strategy used below

        # String-level: split at 60/40 boundary, truncate middle
        if enc is not None:
            half = limit // 2
            try:
                encoded_full = enc.encode(prompt)
                truncated_enc = encoded_full[:half] + encoded_full[-(limit - half) :]
                return enc.decode(truncated_enc)
            except Exception:
                pass

        # Fallback: naive char-level
        half_chars = (limit * 4) // 2
        return prompt[:half_chars] + "\n... [truncated] ...\n" + prompt[-half_chars:]

    async def _invoke_llm(
        self, rendered: str, policy: AIPolicySpec | None, stream: bool
    ) -> AIResponse:
        """Шаг 6: PydanticAI unified client (S32 W1) или LiteLLMGateway fallback.

        При наличии ``policy.model_router`` использует :class:`PydanticAIClient`
        для интеграции ModelRouter fallback chain через PydanticAI Agent.
        При отсутствии ``policy`` — backward-compat path через LiteLLMGateway
        напрямую (pass-through scaffold).

        Args:
            rendered: Готовый prompt.
            policy: Resolved AIPolicySpec (для ``model_router``).
            stream: Streaming flag (reserved, пока not supported).

        Returns:
            AIResponse с raw completion (до output guards/sanitize).
        """
        if (
            policy is not None
            and hasattr(policy, "model_router")
            and policy.model_router is not None
        ):
            from src.backend.core.ai.pydantic_ai_client import (
                LLMDependencies,
                PydanticAIClient,
            )

            gw = self._resolve_llm_gateway()
            model_router = policy.model_router

            client = PydanticAIClient(
                gateway=gw,
                model_router=model_router,
                metrics_registry=getattr(self, "_metrics_registry", None),
            )

            deps = LLMDependencies(
                tenant_id=getattr(self, "_tenant_id", "default"), correlation_id=""
            )
            result = await client.run(
                prompt=rendered, deps=deps, stream=stream, _internal_gateway_call=True
            )

            return AIResponse(
                content=result.content,
                tokens_prompt=result.tokens_prompt,
                tokens_completion=result.tokens_completion,
                model_used=result.model_used,
                cost_usd=result.cost_usd,
            )

        # Backward-compat: LiteLLMGateway напрямую (scaffold pass-through)
        gw = self._resolve_llm_gateway()
        model = None
        fallbacks: list[str] | None = None
        if policy is not None:
            model = policy.model_router.primary
            fallbacks = list(policy.model_router.fallback) or None

        kwargs: dict[str, Any] = {}
        if fallbacks:
            kwargs["fallbacks"] = fallbacks
        # S127 W4 (TD-022): inject Anthropic prompt cache_control
        # для cacheable моделей (50-90% token savings на повторных
        # вызовах с идентичным prompt).
        from src.backend.infrastructure.ai.prompt_cache_middleware import (
            inject_prompt_cache,
        )

        messages = [{"role": "user", "content": rendered}]
        if model is not None:
            messages = inject_prompt_cache(messages, model)
        response = await gw.acompletion(
            messages, model=model, stream=False, **kwargs
        )

        content, tokens_prompt, tokens_completion, model_used = (
            self._extract_completion(response, fallback_model=model)
        )
        return AIResponse(
            content=content,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            model_used=model_used,
        )

    @staticmethod
    def _extract_completion(
        response: Any, *, fallback_model: str | None
    ) -> tuple[str, int, int, str]:
        """Вытаскивает content/tokens/model из litellm-ответа.

        Поддерживает оба формата:
        * ``litellm.ModelResponse`` — атрибуты ``.choices``, ``.usage``,
          ``.model``;
        * ``dict`` — те же ключи.

        Returns:
            ``(content, prompt_tokens, completion_tokens, model_used)``.
        """
        if isinstance(response, dict):
            choices = response.get("choices", [])
            usage = response.get("usage", {}) or {}
            model_used = response.get("model") or fallback_model or ""
        else:
            choices = getattr(response, "choices", []) or []
            usage_obj = getattr(response, "usage", None)
            usage = (
                usage_obj.model_dump()
                if usage_obj is not None and hasattr(usage_obj, "model_dump")
                else (usage_obj or {})
            )
            if isinstance(usage_obj, dict):
                usage = usage_obj
            model_used = getattr(response, "model", None) or fallback_model or ""

        content = ""
        if choices:
            first = choices[0]
            if isinstance(first, dict):
                msg = first.get("message", {}) or {}
                content = msg.get("content", "") or ""
            else:
                msg = getattr(first, "message", None)
                if msg is not None:
                    content = getattr(msg, "content", "") or ""
                    if isinstance(msg, dict):
                        content = msg.get("content", "") or ""

        if isinstance(usage, dict):
            prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
            completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        else:
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)

        return content, prompt_tokens, completion_tokens, str(model_used)

    @staticmethod
    def _provider_from_model(model: str) -> str:
        """``openai/gpt-4o`` → ``openai``; default ``"openai"``."""
        if "/" in model:
            return model.split("/", 1)[0]
        return "openai"
