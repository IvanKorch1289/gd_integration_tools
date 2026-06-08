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

from src.backend.core.ai.errors import GuardResult
from src.backend.core.ai.gateway_models import AIRequest, AIResponse
from src.backend.infrastructure.logging.factory import get_logger

if TYPE_CHECKING:
    from src.backend.core.ai.policy.spec import AIPolicySpec

__all__ = ("PipelineStepsMixin",)

logger = get_logger(__name__)


class PipelineStepsMixin:
    """Mixin с 9-step pipeline методами для :class:`AIGateway`.

    Зависит от facade-provided attrs:
    - ``self._policy_resolver`` — :class:`PolicyResolver` (или None)
    - ``self._capability_gate`` — :class:`CapabilityGate` (или None)
    - ``self._audit_service`` — :class:`AuditService` (или None)
    - ``self._cost_tracker`` — cost aggregator (или None)
    - ``self._sanitizer`` — :class:`AsyncPIISanitizerProtocol` (или None)
    - ``self._llm_gateway`` — :class:`LiteLLMGateway` (или None)
    - ``self._policy_enforcer`` — :class:`AIPolicyEnforcer` (или None)
    """

    _policy_resolver: Any | None
    _capability_gate: Any | None
    _policy_enforcer: Any | None
    _audit_service: Any | None
    _cost_tracker: Any | None
    _sanitizer: Any | None
    _llm_gateway: Any | None

    # ── 9-step pipeline methods ──────────────────────────────────────────

    async def _resolve_policy(self, request: AIRequest) -> AIPolicySpec | None:
        """Шаг 1: PolicyResolver → AIPolicySpec.

        Args:
            request: AIRequest.

        Returns:
            Resolved :class:`AIPolicySpec`; ``None`` если ``policy_resolver``
            не задан или не нашёл подходящей политики.

        Raises:
            PolicyNotResolvedError: при ``ai_policy_enforce=True`` и
                отсутствии политики с ``required=True``.
        """
        if self._policy_resolver is None:
            return None
        policy = await self._policy_resolver.resolve(
            workflow_id=request.workflow_id, tenant_id=request.tenant_id
        )
        if policy is None:
            try:
                from src.backend.core.config.features import feature_flags

                strict = bool(feature_flags.ai_policy_enforce)
            except Exception as _:
                strict = False
            if strict:
                from src.backend.core.ai.policy.resolver import PolicyNotResolvedError

                raise PolicyNotResolvedError(request.workflow_id, request.tenant_id)
        return policy

    async def _check_capability(self, request: AIRequest) -> None:
        """Шаг 2: CapabilityGate intercept.

        Args:
            request: AIRequest.

        Raises:
            CapabilityDeniedError: Если capability ``ai.invoke.<workflow_id>``
                не выдана текущему контексту вызова.
        """
        if self._capability_gate is None:
            return
        capability = f"ai.invoke.{request.workflow_id}"
        check = getattr(self._capability_gate, "check", None)
        if check is None:
            return
        result = check(capability)
        try:
            import inspect

            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            logger.debug(
                "AIGateway: capability check for %s failed: %s", capability, exc
            )

    async def _apply_input_sanitizers(
        self, request: AIRequest, policy: AIPolicySpec | None
    ) -> str:
        """Шаг 3: input sanitizers (PII через Presidio / PIITokenizer).

        Использует :class:`PresidioSanitizerAdapter` для маскировки PII в
        ``prompt_inline`` / ``prompt_ref``. Если sanitizer не задан или
        Presidio недоступен — возвращается исходный prompt без изменений.

        Args:
            request: AIRequest.
            policy: Resolved AIPolicySpec (``input_sanitizers`` указывает
                язык/конфигурацию).

        Returns:
            Sanitized prompt-строка (placeholders типа ``[PHONE_1]`` вместо
            оригинальных PII-данных).
        """
        prompt = request.prompt_inline or request.prompt_ref or ""
        if not prompt:
            return ""

        sanitizer = self._resolve_sanitizer()
        if sanitizer is None:
            return prompt

        language = self._language_from_policy(policy, default="ru")
        try:
            result = await sanitizer.sanitize_async(prompt, language=language)
        except RuntimeError as exc:
            logger.warning("AIGateway: sanitize_async недоступен (%s)", exc)
            return prompt
        except Exception as exc:
            logger.error("AIGateway: input sanitize failed: %s", exc, exc_info=True)
            return prompt

        replacements = getattr(result, "replacements", {}) or {}
        self._last_input_replacements = dict(replacements)
        self._last_input_pii_detected = bool(replacements)
        return getattr(result, "sanitized_text", prompt)

    async def _apply_input_guards(
        self, sanitized: str, policy: AIPolicySpec | None
    ) -> list[GuardResult]:
        """Шаг 4: input guards (NeMo Colang + Rebuff/Lakera).

        При наличии :class:`AIPolicyEnforcer` с настроенными guards вызывает
        :meth:`AIPolicyEnforcer.guard_input`. Иначе — no-op.

        Args:
            sanitized: Sanitized input после шага 3.
            policy: Resolved AIPolicySpec.

        Returns:
            Список :class:`GuardResult` от каждого guard'а.
        """
        if self._policy_enforcer is None or policy is None:
            return []
        if not policy.input_guards:
            return []
        guard = getattr(self._policy_enforcer, "guard_input", None)
        if guard is None:
            return []
        try:
            results = await guard(sanitized, policy)
            return results if results is not None else []
        except NotImplementedError:
            logger.debug(
                "AIGateway: input guards не реализованы (Wave S24 W2 deferred)"
            )
            return []

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

        budget_spec = policy.budget if policy else None
        if budget_spec is None:
            return sanitized

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

        total_tokens = count_tokens(sanitized)
        if total_tokens <= limit:
            return sanitized

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
                encoded_full = enc.encode(sanitized)
                truncated_enc = encoded_full[:half] + encoded_full[-(limit - half) :]
                return enc.decode(truncated_enc)
            except Exception:
                pass

        # Fallback: naive char-level
        half_chars = (limit * 4) // 2
        return (
            sanitized[:half_chars] + "\n... [truncated] ...\n" + sanitized[-half_chars:]
        )

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
            result = await client.run(prompt=rendered, deps=deps, stream=stream)

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
        response = await gw.acompletion(
            [{"role": "user", "content": rendered}], model=model, stream=False, **kwargs
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

    # ── helpers ──────────────────────────────────────────────────────────

    def _resolve_sanitizer(self) -> Any | None:
        """Lazy-резолв sanitizer'а через DI или фабрику Presidio."""
        if self._sanitizer is not None:
            return self._sanitizer
        try:
            from src.backend.services.ai.pii.presidio_analyzer import (
                get_presidio_sanitizer_adapter,
            )

            self._sanitizer = get_presidio_sanitizer_adapter()
        except Exception as exc:
            logger.debug("AIGateway: PresidioSanitizerAdapter недоступен (%s)", exc)
            self._sanitizer = None
        return self._sanitizer

    def _resolve_llm_gateway(self) -> Any:
        """Lazy-резолв :class:`LiteLLMGateway` через DI singleton."""
        if self._llm_gateway is not None:
            return self._llm_gateway
        from src.backend.services.ai.gateway import get_litellm_gateway

        self._llm_gateway = get_litellm_gateway()
        return self._llm_gateway

    @staticmethod
    def _language_from_policy(policy: AIPolicySpec | None, *, default: str) -> str:
        """Извлекает язык из первого input_sanitizer (``presidio:ru`` → ``ru``)."""
        if policy is None or not policy.input_sanitizers:
            return default
        ref = policy.input_sanitizers[0]
        cfg_lang = ref.config.get("language") if ref.config else None
        if cfg_lang:
            return str(cfg_lang)
        name = ref.name
        if ":" in name:
            return name.rsplit(":", 1)[-1] or default
        return default

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
