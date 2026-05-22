"""AIPolicyEnforcer — middleware-like enforcement-точка для AIGateway.

Scaffold S25 W2 (ADR-NEW-20). Полная реализация — Wave S25 W2 + S27 W2
(когда DSL processor'ы guardrails_apply/pii_mask интегрируются с :class:`AIGateway`).

См. docs/adr/0067-ai-policy-spec-dsl.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.core.ai.gateway import AIRequest, AIResponse
    from src.backend.core.ai.policy.spec import AIPolicySpec

__all__ = ("AIPolicyEnforcer",)


class AIPolicyEnforcer:
    """Применяет AIPolicySpec sanitizers/guards к request/response.

    Используется :class:`AIGateway` внутри ``_apply_*`` методов pipeline.
    Scaffold S25 W2: методы поднимают ``NotImplementedError`` до подключения
    backends (Presidio, NeMo, Llama Guard) из S24/S26.

    Архитектурно — точка composition root'а для:

    * :class:`PIITokenizer` (S25 W4 ADR-NEW-21) — reversible PII;
    * NeMo Guardrails (S24 W2 ADR-NEW-17) — input rails;
    * Llama Guard 3 (S24 W2 ADR-NEW-17) — output classifier;
    * Outlines (S26 W2 opt-in) — grammar-constrained output для self-hosted.

    Notes:
        Enforcer НЕ применяет sanitizers/guards если
        :attr:`AIPolicySpec.required` = False — это контролируется
        :class:`AIGateway` через feature-flag ``ai_policy_enforce``.
    """

    def __init__(
        self,
        *,
        pii_tokenizer: object | None = None,
        nemo_runtime: object | None = None,
        llama_guard_runtime: object | None = None,
    ) -> None:
        """Инициализация.

        Args:
            pii_tokenizer: :class:`PIITokenizer` (S25 W4) — reversible
                tokenizer; при ``None`` — sanitize пропускается (warn).
            nemo_runtime: NeMo Guardrails runtime (S24 W2);
                при ``None`` — input guards пропускаются.
            llama_guard_runtime: Llama Guard 3 runtime (S24 W2);
                при ``None`` — output guards пропускаются.
        """
        self._pii_tokenizer = pii_tokenizer
        self._nemo_runtime = nemo_runtime
        self._llama_guard_runtime = llama_guard_runtime

    async def sanitize_input(
        self, request: "AIRequest", policy: "AIPolicySpec"
    ) -> str:
        """Применить :attr:`AIPolicySpec.input_sanitizers` к ``request.prompt``.

        Args:
            request: AIRequest.
            policy: Resolved AIPolicySpec.

        Returns:
            Sanitized prompt string.

        Raises:
            NotImplementedError: S25 W4 (PIITokenizer integration).
        """
        del request, policy
        raise NotImplementedError("S25 W4: PIITokenizer integration (ADR-NEW-21)")

    async def guard_input(
        self, prompt: str, policy: "AIPolicySpec"
    ) -> None:
        """Применить :attr:`AIPolicySpec.input_guards` к sanitized prompt.

        Args:
            prompt: Sanitized prompt после :meth:`sanitize_input`.
            policy: Resolved AIPolicySpec.

        Raises:
            NotImplementedError: S24 W2 (NeMo Colang + Rebuff/Lakera).
            GuardrailViolationError: При ``on_block="fail"`` и срабатывании
                guard'а (полная реализация — S27 W2).
        """
        del prompt, policy
        raise NotImplementedError("S24 W2: input guards (ADR-NEW-17)")

    async def guard_output(
        self, response: "AIResponse", policy: "AIPolicySpec"
    ) -> None:
        """Применить :attr:`AIPolicySpec.output_guards` к ``response.content``.

        Args:
            response: Raw completion AIResponse.
            policy: Resolved AIPolicySpec.

        Raises:
            NotImplementedError: S24 W2 (Llama Guard 3).
        """
        del response, policy
        raise NotImplementedError("S24 W2: output guards (ADR-NEW-17)")

    async def sanitize_output(
        self, response: "AIResponse", policy: "AIPolicySpec"
    ) -> "AIResponse":
        """Применить :attr:`AIPolicySpec.output_sanitizers` к ``response``.

        Args:
            response: Raw completion AIResponse (после guard_output).
            policy: Resolved AIPolicySpec.

        Returns:
            Sanitized AIResponse (с redacted PII / validated JSON-Schema).

        Raises:
            NotImplementedError: S25 W4 + S26 W2 (Presidio + Outlines).
        """
        del policy
        raise NotImplementedError("S25 W4 + S26 W2: output sanitizers")
