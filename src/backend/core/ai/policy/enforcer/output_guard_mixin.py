from __future__ import annotations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from src.backend.core.ai.gateway import AIRequest, AIResponse
    from src.backend.core.ai.policy.spec import AIPolicySpec, GuardRef
    from src.backend.core.messaging.dlq import DLQWriter

from src.backend.core.ai.errors import GuardrailViolationError, GuardResult

class OutputGuardMixin:
    """output guard (2 methods: entry + backend) для AIPolicyEnforcer. S67 W2 extraction."""

    __slots__ = ()

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

