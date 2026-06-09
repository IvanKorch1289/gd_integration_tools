"""AIPolicyEnforcer — enforcement-точка для AIGateway (S27 W2).

Реализует AIPolicySpec guards:

* Input guards: LLM Guard (self-hosted, S35 W1) — replaces Rebuff/Lakera external APIs.
  - ``llm_guard:*`` — self-hosted scanner (PromptInjection, Toxicity, etc.)
  - ``rebuff:*`` — deprecated external API (kept for backward-compat)
  - ``lakera:*`` — deprecated external API (kept for backward-compat)
  - ``nemo:*`` — skip (Python 3.14 incompat)
* Output guards: Llama Guard 3 (GGUF self-hosted, S25 W4).

GuardrailViolationError поднимается при ``on_block="fail"``.
DLQ publish при ``on_block="dlq"``.
Warn-лог при ``on_block="warn"``.

См. docs/adr/0067-ai-policy-spec-dsl.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from src.backend.core.ai.gateway import AIRequest, AIResponse
    from src.backend.core.ai.policy.spec import AIPolicySpec, GuardRef
    from src.backend.core.messaging.dlq import DLQWriter

from src.backend.core.ai.errors import GuardrailViolationError, GuardResult

__all__ = ("AIPolicyEnforcer",)

logger = get_logger(__name__)


class AIPolicyEnforcer:
    """Применяет AIPolicySpec guards к request/response.

    Composition root подключает backends через конструктор:
    - ``llama_guard_runtime``: LlamaGuardRuntime (S25 W4, GGUF)
    - ``pii_tokenizer``: PIITokenizer (S25 W4) — для sanitize_input
    - ``nemo_runtime``: NeMo (Python 3.14 incompat — skip при None)
    - ``llm_guard_client``: LLMGuardClient (S35 W1, self-hosted scanner)

    Не применяет guards если :attr:`AIPolicySpec.required` = False
    (контролируется AIGateway через feature-flag).
    """

    def __init__(
        self,
        *,
        pii_tokenizer: object | None = None,
        nemo_runtime: object | None = None,
        llama_guard_runtime: object | None = None,
        llm_guard_client: Any | None = None,
        dlq_writer: DLQWriter | None = None,
    ) -> None:
        self._pii_tokenizer = pii_tokenizer
        self._nemo_runtime = nemo_runtime
        self._llama_guard_runtime = llama_guard_runtime
        self._llm_guard_client = llm_guard_client
        self._dlq_writer = dlq_writer

    # ── Input guards ───────────────────────────────────────────────────────────

    async def guard_input(self, prompt: str, policy: AIPolicySpec) -> list[GuardResult]:
        """Применить :attr:`AIPolicySpec.input_guards` к sanitized prompt.

        Поддерживаетые guard'ы:
        - ``"llm_guard:<scanner>"`` — LLM Guard self-hosted (S35 W1, default)
        - ``"rebuff:<variant>"`` — Rebuff client (deprecated, external API)
        - ``"lakera:<variant>"`` — Lakera client (deprecated, external API)
        - ``"nemo:*"`` — NeMo Colang (skip, Python 3.14 incompat)

        Raises:
            GuardrailViolationError: При ``on_block="fail"``.
        """
        if not policy.input_guards:
            return []

        results: list[GuardResult] = []
        for ref in policy.input_guards:
            result = await self._guard_input_one(prompt, ref)
            if result is not None:
                results.append(result)
        return results

    async def _guard_input_one(self, prompt: str, ref: GuardRef) -> GuardResult | None:
        """Apply single input guard ref.

        Returns GuardResult with verdict 'passed' if no block,
        or raises GuardrailViolationError if on_block='fail'.
        """
        name = ref.name.lower()
        on_block = ref.on_block

        # NeMo — Python 3.14 incompat, пропускаем
        if name.startswith("nemo:"):
            logger.debug(
                "AIPolicyEnforcer: nemo input guard skipped (Python 3.14 incompat)"
            )
            return None

        # LLM Guard — self-hosted (S35 W1, default)
        if name.startswith("llm_guard:") or name.startswith("llm-guard:"):
            return await self._guard_input_llm_guard(prompt, ref, on_block)

        # Rebuff
        if name.startswith("rebuff:"):
            return await self._guard_input_rebuff(prompt, ref, on_block)

        # Lakera
        if name.startswith("lakera:"):
            return await self._guard_input_lakera(prompt, ref, on_block)

        logger.warning("AIPolicyEnforcer: unknown input guard %r — skipped", name)
        return None

    async def _guard_input_rebuff(
        self, prompt: str, ref: GuardRef, on_block: str
    ) -> GuardResult:
        """Rebuff input guard check."""
        try:
            from src.backend.services.ai.guardrails.rebuff_client import RebuffClient

            client = RebuffClient()
            result = await client.detect(prompt)
            if result.injected:
                categories = result.metadata.get("categories", [])
                self._handle_guard_block(
                    guard_name=ref.name,
                    flagged=categories or ["prompt_injection"],
                    on_block=on_block,
                    content=prompt,
                )
                # on_block != fail — block handled (dlq/warn), return blocked result
                return GuardResult(
                    guard_name=ref.name,
                    verdict="blocked",
                    categories=categories or ["prompt_injection"],
                )
            return GuardResult(guard_name=ref.name, verdict="passed")
        except GuardrailViolationError:
            raise
        except Exception as exc:
            logger.warning("AIPolicyEnforcer: Rebuff check failed: %s", exc)
            if on_block == "fail":
                raise GuardrailViolationError(
                    guard_name=ref.name,
                    flagged_categories=["rebuff_error"],
                    on_block=on_block,
                    content=prompt,
                ) from exc
            return GuardResult(guard_name=ref.name, verdict="passed")

    async def _guard_input_lakera(
        self, prompt: str, ref: GuardRef, on_block: str
    ) -> GuardResult:
        """Lakera input guard check."""
        try:
            from src.backend.services.ai.guardrails.lakera_client import LakeraClient

            client = LakeraClient()
            result = await client.screen(prompt)
            if result.flagged:
                categories = [
                    c.get("category") or c.get("name") or str(c)
                    for c in result.categories
                ]
                self._handle_guard_block(
                    guard_name=ref.name,
                    flagged=categories or ["prompt_injection"],
                    on_block=on_block,
                    content=prompt,
                )
                return GuardResult(
                    guard_name=ref.name,
                    verdict="blocked",
                    categories=categories or ["prompt_injection"],
                )
            return GuardResult(guard_name=ref.name, verdict="passed")
        except GuardrailViolationError:
            raise
        except Exception as exc:
            logger.warning("AIPolicyEnforcer: Lakera check failed: %s", exc)
            if on_block == "fail":
                raise GuardrailViolationError(
                    guard_name=ref.name,
                    flagged_categories=["lakera_error"],
                    on_block=on_block,
                    content=prompt,
                ) from exc
            return GuardResult(guard_name=ref.name, verdict="passed")

    async def _guard_input_llm_guard(
        self, prompt: str, ref: GuardRef, on_block: str
    ) -> GuardResult:
        """LLM Guard self-hosted input guard check (S35 W1)."""
        if self._llm_guard_client is None:
            logger.warning(
                "AIPolicyEnforcer: llm_guard input guard requires llm_guard_client "
                "— skipped. Set LLAMA_GUARD_ENABLED=1 for self-hosted scanner."
            )
            return GuardResult(guard_name=ref.name, verdict="passed")
        try:
            from src.backend.core.ai.guardrails.llm_guard_client import LLMGuardResult

            result: LLMGuardResult = await self._llm_guard_client.scan(prompt)
            if result.flagged:
                self._handle_guard_block(
                    guard_name=ref.name,
                    flagged=result.categories,
                    on_block=on_block,
                    content=prompt,
                )
                return GuardResult(
                    guard_name=ref.name, verdict="blocked", categories=result.categories
                )
            return GuardResult(guard_name=ref.name, verdict="passed")
        except GuardrailViolationError:
            raise
        except Exception as exc:
            logger.warning("AIPolicyEnforcer: LLM Guard check failed: %s", exc)
            if on_block == "fail":
                raise GuardrailViolationError(
                    guard_name=ref.name,
                    flagged_categories=["llm_guard_error"],
                    on_block=on_block,
                    content=prompt,
                ) from exc
            return GuardResult(guard_name=ref.name, verdict="passed")

    def _handle_guard_block(
        self, *, guard_name: str, flagged: list[str], on_block: str, content: str
    ) -> None:
        """Handle guard block according to on_block policy."""
        if on_block == "fail":
            raise GuardrailViolationError(
                guard_name=guard_name,
                flagged_categories=flagged,
                on_block=on_block,
                content=content,
            )
        if on_block == "dlq":
            # DLQ publish асинхронно, не блокируем
            from src.backend.core.utils.task_registry import get_task_registry

            get_task_registry().create_task(
                self._publish_dlq(guard_name, flagged, content),
                name=f"policy-enforcer.dlq.{guard_name}",
            )
            logger.warning(
                "AIPolicyEnforcer: guard %r blocked, sent to DLQ (categories=%s)",
                guard_name,
                flagged,
            )
            return
        # warn — just log
        logger.warning(
            "AIPolicyEnforcer: guard %r flagged (on_block=warn, categories=%s)",
            guard_name,
            flagged,
        )

    async def _publish_dlq(
        self, guard_name: str, flagged: list[str], content: str
    ) -> None:
        """Publish blocked content to DLQ (fire-and-forget)."""
        if self._dlq_writer is None:
            try:
                import importlib.util

                if importlib.util.find_spec("src.backend.core.messaging.dlq") is None:
                    logger.debug("DLQWriter not available — skipping DLQ publish")
                    return
            except ImportError:
                logger.debug("DLQWriter not available — skipping DLQ publish")
                return

        writer = self._dlq_writer
        if writer is None:
            return

        try:
            from src.backend.core.messaging.dlq import DLQEnvelope, DLQReason

            envelope = DLQEnvelope(
                transport="ai_guard",
                original_payload={
                    "content": content[:200],
                    "guard": guard_name,
                    "categories": flagged,
                },
                error_class="GuardrailViolation",
                error_message=f"Guard {guard_name} blocked: {flagged}",
                reason=DLQReason.UNEXPECTED,
            )
            await writer.write(envelope)
        except Exception as exc:
            logger.error("AIPolicyEnforcer: DLQ publish failed: %s", exc)

    # ── Output guards ──────────────────────────────────────────────────────────

    async def guard_output(
        self, response: AIResponse, policy: AIPolicySpec
    ) -> list[GuardResult]:
        """Применить :attr:`AIPolicySpec.output_guards` к ``response.content``.

        Поддерживаемые guard'ы:
        - ``"llama_guard:safe_v3"`` — Llama Guard 3 (GGUF self-hosted)
        - ``"llama_guard:*"`` — любой Llama Guard variant

        Raises:
            GuardrailViolationError: При ``on_block="fail"``.
        """
        if not policy.output_guards or not response.content:
            return []

        results: list[GuardResult] = []
        for ref in policy.output_guards:
            result = await self._guard_output_one(response, ref)
            if result is not None:
                results.append(result)
        return results

    async def _guard_output_one(
        self, response: AIResponse, ref: GuardRef
    ) -> GuardResult | None:
        """Apply single output guard ref."""
        name = ref.name.lower()
        on_block = ref.on_block

        if not name.startswith("llama_guard:"):
            logger.warning("AIPolicyEnforcer: unknown output guard %r — skipped", name)
            return None

        runtime = self._llama_guard_runtime
        if runtime is None:
            logger.debug(
                "AIPolicyEnforcer: llama_guard runtime not configured — output guard skipped"
            )
            return None

        # runtime is object at type-check time; check for classify at runtime
        classify = getattr(runtime, "classify", None)
        if not classify or not callable(classify):
            logger.debug(
                "AIPolicyEnforcer: llama_guard runtime has no classify method — skipped"
            )
            return None

        try:
            result = await classify(response.content)
        except Exception as exc:
            logger.error("AIPolicyEnforcer: LlamaGuard classify failed: %s", exc)
            if on_block == "fail":
                raise GuardrailViolationError(
                    guard_name=ref.name,
                    flagged_categories=["llamaguard_error"],
                    on_block=on_block,
                    content=response.content,
                ) from exc
            return None

        if not result.safe:
            self._handle_guard_block(
                guard_name=ref.name,
                flagged=result.flagged_categories,
                on_block=on_block,
                content=response.content,
            )
            return GuardResult(
                guard_name=ref.name,
                verdict="blocked",
                categories=result.flagged_categories,
            )
        return GuardResult(guard_name=ref.name, verdict="passed", categories=[])

    # ── Sanitizers (stub, S25 W4 + S26 W2) ────────────────────────────────────

    async def sanitize_input(self, request: AIRequest, policy: AIPolicySpec) -> str:
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
            logger.error("sanitize_input failed: %s", exc)
            return prompt

        return getattr(result, "sanitized_text", prompt)

    async def sanitize_output(
        self, response: AIResponse, policy: AIPolicySpec
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
