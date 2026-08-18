from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.core.ai.gateway import AIRequest, AIResponse
    from src.backend.core.ai.policy.enforcer._protocol import _AIPolicyEnforcerProtocol
    from src.backend.core.ai.policy.spec import AIPolicySpec

from src.backend.core.logging import get_logger

logger = get_logger(__name__)


class SanitizeMixin:
    """sanitize input/output (2 methods) для AIPolicyEnforcer. S67 W2 extraction."""

    __slots__ = ()

    if TYPE_CHECKING:
        _protocol_self: _AIPolicyEnforcerProtocol

    async def sanitize_input(
        self: _AIPolicyEnforcerProtocol, request: AIRequest, policy: AIPolicySpec
    ) -> str:
        """Применить :attr:`AIPolicySpec.input_sanitizers` (PIITokenizer).

        Использует ``self._pii_tokenizer``, который является экземпляром
        :class:`PIITokenizer` (S25 W4). Возвращает исходный prompt
        если tokenizer не настроен.

        Args:
            request: AIRequest с ``.prompt_inline`` или ``.prompt_ref``.
            policy: Resolved AIPolicySpec.

        Returns:
            Sanitized prompt-строку (PII заменён на placeholder'ы).

        """
        prompt = (
            getattr(request, "prompt_inline", None)
            or getattr(request, "prompt_ref", "")
            or ""
        )
        if not prompt or self._pii_tokenizer is None:
            return prompt

        language = getattr(policy, "language", "ru") if policy else "ru"
        tokenizer = getattr(self._pii_tokenizer, "sanitize_async", None)
        if tokenizer is None:
            return prompt

        try:
            result = await tokenizer(prompt, language=language)
        except Exception as exc:
            # P0-S5 fix (audit 2026-08-18): sanitizer сконфигурирован, но
            # недоступен → fail-closed в production (ai_policy_enforce=True).
            # Иначе PII утекает в LLM. Backward compat: dev/staging (FF off)
            # → log + original prompt (legacy fail-soft).
            if self._is_ai_policy_enforce():
                logger.error("sanitize_input failed — fail-closed: %s", exc)
                raise
            logger.error("sanitize_input failed: %s", exc)
            return prompt

        return getattr(result, "sanitized_text", prompt)

    async def sanitize_output(
        self: _AIPolicyEnforcerProtocol, response: AIResponse, policy: AIPolicySpec
    ) -> AIResponse:
        """Применить :attr:`AIPolicySpec.output_sanitizers` (PII redaction).

        Использует ``self._pii_tokenizer`` для маскировки PII в LLM-ответе.
        Структурированные поля (``structured``) не санитизируются.

        Args:
            response: AIResponse с ``.content`` (raw LLM text).
            policy: Resolved AIPolicySpec.

        Returns:
            AIResponse с sanitized content + ``pii_detected=True``.

        """
        if not getattr(response, "content", None) or self._pii_tokenizer is None:
            return response

        language = getattr(policy, "language", "ru") if policy else "ru"
        tokenizer = getattr(self._pii_tokenizer, "sanitize_async", None)
        if tokenizer is None:
            return response

        try:
            result = await tokenizer(response.content, language=language)
        except Exception as exc:
            # P0-S5 fix: fail-closed в production для output sanitizers.
            if self._is_ai_policy_enforce():
                logger.error("sanitize_output failed — fail-closed: %s", exc)
                raise
            logger.error("sanitize_output failed: %s", exc)
            return response

        sanitized_text = getattr(result, "sanitized_text", response.content)
        replacements = getattr(result, "replacements", None)
        pii_detected = bool(replacements)

        # Rebuild AIResponse with sanitized content
        from src.backend.core.ai.gateway import AIResponse as AIResponse_cls

        return AIResponse_cls(
            content=sanitized_text,
            structured=response.structured,
            tokens_prompt=response.tokens_prompt,
            tokens_completion=response.tokens_completion,
            cost_usd=response.cost_usd,
            model_used=response.model_used,
            pii_detected=pii_detected,
            guardrails_verdict=response.guardrails_verdict or {},
        )

    def _is_ai_policy_enforce(self: _AIPolicyEnforcerProtocol) -> bool:
        """Проверить feature flag ``ai_policy_enforce``.

        P0-S5: используется для fail-closed решения в sanitizers.
        Default — ``True`` (fail-closed) если feature_flags недоступен.
        """
        try:
            from src.backend.core.config.features import feature_flags

            return bool(feature_flags.ai_policy_enforce)
        except Exception as exc:  # pragma: no cover — feature_flags optional
            logger.debug(
                "AIPolicyEnforcer: feature_flags.ai_policy_enforce unavailable (%s); "
                "defaulting to True for fail-closed safety",
                exc,
            )
            return True
