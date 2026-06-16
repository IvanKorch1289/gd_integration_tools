from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass  # cross-mixin / state attrs declared below

from src.backend.core.logging import get_logger

logger = get_logger(__name__)

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

from src.backend.core.ai.errors import GuardResult
from src.backend.core.ai.gateway_models import AIRequest

if TYPE_CHECKING:
    from src.backend.core.ai.policy.spec import AIPolicySpec


from src.backend.core.ai.gateway_pipeline_mixin._protocol import _PipelineStepsProtocol


class InputMixin(_PipelineStepsProtocol):
    """input sanitization + guards (_apply_input_sanitizers, _apply_input_guards, _resolve_sanitizer) для PipelineStepsMixin. S56 W2 extraction."""

    __slots__ = ()
    _sanitizer: Any

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

    def _resolve_sanitizer(self) -> Any | None:
        """Lazy-резолв sanitizer'а через DI или фабрику Presidio."""
        sanitizer: Any | None = self._sanitizer
        if sanitizer is not None:
            return sanitizer
        try:
            from src.backend.services.ai.pii.presidio_analyzer import (
                get_presidio_sanitizer_adapter,
            )

            sanitizer = get_presidio_sanitizer_adapter()
        except Exception as exc:
            logger.debug("AIGateway: PresidioSanitizerAdapter недоступен (%s)", exc)
            sanitizer = None
        self._sanitizer = sanitizer
        return sanitizer
