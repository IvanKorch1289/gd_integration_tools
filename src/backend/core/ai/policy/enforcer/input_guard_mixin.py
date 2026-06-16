from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.core.ai.policy.enforcer._protocol import _AIPolicyEnforcerProtocol
    from src.backend.core.ai.policy.spec import AIPolicySpec, GuardRef

from src.backend.core.ai.errors import GuardrailViolationError, GuardResult
from src.backend.core.logging import get_logger

logger = get_logger(__name__)

# NeMo guard → LLM Guard scanner fallback (Python 3.14 incompat, ADR-0175 C7)
_NEMO_TO_LLM_GUARD_FALLBACK: dict[str, str] = {
    "nemo:colang:topics": "llm_guard:BanTopics",
    "nemo:colang:sensitive": "llm_guard:Sensitive",
    "nemo:moderation": "llm_guard:PromptInjection",
    "nemo:prompt_injection": "llm_guard:PromptInjection",
}


class InputGuardMixin:
    """input guard (5 methods: 1 entry + 4 backends) для AIPolicyEnforcer. S67 W2 extraction."""

    __slots__ = ()

    if TYPE_CHECKING:
        _protocol_self: _AIPolicyEnforcerProtocol

    async def guard_input(
        self: "_AIPolicyEnforcerProtocol", prompt: str, policy: AIPolicySpec
    ) -> list[GuardResult]:
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

    async def _guard_input_one(
        self: "_AIPolicyEnforcerProtocol", prompt: str, ref: GuardRef
    ) -> GuardResult | None:
        """Apply single input guard ref.

        Returns GuardResult with verdict 'passed' if no block,
        or raises GuardrailViolationError if on_block='fail'.
        """
        name = ref.name.lower()
        on_block = ref.on_block

        # NeMo — Python 3.14 incompat, fallback to llm_guard if mapped
        if name.startswith("nemo:"):
            fallback = _NEMO_TO_LLM_GUARD_FALLBACK.get(name)
            if fallback is not None:
                logger.warning(
                    "AIPolicyEnforcer: nemo guard %r → fallback to %r "
                    "(NeMo Python 3.14 incompat)",
                    name,
                    fallback,
                    extra={
                        "guard_ref": name,
                        "fallback": fallback,
                        "category": "policy_degradation",
                    },
                )
                # Delegate to llm_guard with mapped scanner
                from src.backend.core.ai.policy.spec import GuardRef

                mapped_ref = GuardRef(name=fallback, on_block=on_block)
                return await self._guard_input_llm_guard(prompt, mapped_ref, on_block)
            logger.warning(
                "AIPolicyEnforcer: nemo guard %r skipped (Python 3.14 incompat, no fallback)",
                name,
                extra={"guard_ref": name, "category": "policy_degradation"},
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
        self: "_AIPolicyEnforcerProtocol", prompt: str, ref: GuardRef, on_block: str
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
        self: "_AIPolicyEnforcerProtocol", prompt: str, ref: GuardRef, on_block: str
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
        self: "_AIPolicyEnforcerProtocol", prompt: str, ref: GuardRef, on_block: str
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
