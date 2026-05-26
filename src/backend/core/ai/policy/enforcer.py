"""AIPolicyEnforcer — enforcement-точка для AIGateway (S27 W2).

Реализует AIPolicySpec guards:

* Input guards: Rebuff + Lakera (NeMo пропускается — Python 3.14 incompat).
* Output guards: Llama Guard 3 (GGUF self-hosted).

GuardrailViolationError поднимается при ``on_block="fail"``.
DLQ publish при ``on_block="dlq"``.
Warn-лог при ``on_block="warn"``.

См. docs/adr/0067-ai-policy-spec-dsl.md.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.core.ai.gateway import AIRequest, AIResponse
    from src.backend.core.ai.policy.spec import AIPolicySpec, GuardRef
    from src.backend.core.messaging.dlq import DLQWriter

from src.backend.core.ai.errors import GuardrailViolationError

__all__ = ("AIPolicyEnforcer",)

logger = logging.getLogger(__name__)

# Re-export GuardResult из LlamaGuardRuntime (используется в unit-тестах)
try:
    from src.backend.core.ai.guardrails.llamaguard import GuardResult
except ImportError:
    GuardResult = None


class AIPolicyEnforcer:
    """Применяет AIPolicySpec guards к request/response.

    Composition root подключает backends через конструктор:
    - ``llama_guard_runtime``: LlamaGuardRuntime (S25 W4, GGUF)
    - ``pii_tokenizer``: PIITokenizer (S25 W4) — для sanitize_input
    - ``nemo_runtime``: NeMo (Python 3.14 incompat — skip при None)

    Не применяет guards если :attr:`AIPolicySpec.required` = False
    (контролируется AIGateway через feature-flag).
    """

    def __init__(
        self,
        *,
        pii_tokenizer: object | None = None,
        nemo_runtime: object | None = None,
        llama_guard_runtime: object | None = None,
        dlq_writer: "DLQWriter | None" = None,
    ) -> None:
        self._pii_tokenizer = pii_tokenizer
        self._nemo_runtime = nemo_runtime
        self._llama_guard_runtime = llama_guard_runtime
        self._dlq_writer = dlq_writer

    # ── Input guards ───────────────────────────────────────────────────────────

    async def guard_input(
        self, prompt: str, policy: "AIPolicySpec"
    ) -> None:
        """Применить :attr:`AIPolicySpec.input_guards` к sanitized prompt.

        Поддерживаетые guard'ы:
        - ``"rebuff:<variant>"`` — Rebuff client
        - ``"lakera:<variant>"`` — Lakera client
        - ``"nemo:*"`` — NeMo Colang (skip, Python 3.14 incompat)

        Raises:
            GuardrailViolationError: При ``on_block="fail"``.
        """
        if not policy.input_guards:
            return

        for ref in policy.input_guards:
            await self._guard_input_one(prompt, ref)

    async def _guard_input_one(
        self, prompt: str, ref: "GuardRef"
    ) -> None:
        """Apply single input guard ref."""
        name = ref.name.lower()
        on_block = ref.on_block

        # NeMo — Python 3.14 incompat, пропускаем
        if name.startswith("nemo:"):
            logger.debug("AIPolicyEnforcer: nemo input guard skipped (Python 3.14 incompat)")
            return

        # Rebuff
        if name.startswith("rebuff:"):
            await self._guard_input_rebuff(prompt, ref, on_block)
            return

        # Lakera
        if name.startswith("lakera:"):
            await self._guard_input_lakera(prompt, ref, on_block)
            return

        logger.warning("AIPolicyEnforcer: unknown input guard %r — skipped", name)

    async def _guard_input_rebuff(
        self, prompt: str, ref: "GuardRef", on_block: str
    ) -> None:
        """Rebuff input guard check."""
        try:
            from src.backend.services.ai.guardrails.rebuff_client import (
                RebuffClient,
            )
            client = RebuffClient()
            result = await client.detect(prompt)
            if result.injected:
                # RebuffResult.categories из metadata, если есть
                categories = result.metadata.get("categories", [])
                self._handle_guard_block(
                    guard_name=ref.name,
                    flagged=categories or ["prompt_injection"],
                    on_block=on_block,
                    content=prompt,
                )
        except GuardrailViolationError:
            # _handle_guard_block уже поднял GuardrailViolationError — пробросить as-is
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("AIPolicyEnforcer: Rebuff check failed: %s", exc)
            if on_block == "fail":
                raise GuardrailViolationError(
                    guard_name=ref.name,
                    flagged_categories=["rebuff_error"],
                    on_block=on_block,
                    content=prompt,
                ) from exc

    async def _guard_input_lakera(
        self, prompt: str, ref: "GuardRef", on_block: str
    ) -> None:
        """Lakera input guard check."""
        try:
            from src.backend.services.ai.guardrails.lakera_client import (
                LakeraClient,
            )
            client = LakeraClient()
            result = await client.screen(prompt)
            if result.flagged:
                # categories = list of dicts; extract keys
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
        except GuardrailViolationError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("AIPolicyEnforcer: Lakera check failed: %s", exc)
            if on_block == "fail":
                raise GuardrailViolationError(
                    guard_name=ref.name,
                    flagged_categories=["lakera_error"],
                    on_block=on_block,
                    content=prompt,
                ) from exc

    def _handle_guard_block(
        self,
        *,
        guard_name: str,
        flagged: list[str],
        on_block: str,
        content: str,
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
            from src.backend.core.utils.task_registry import get_task_registry  # noqa: PLC0415

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
                from src.backend.core.messaging.dlq import DLQWriter
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
                original_payload={"content": content, "guard": guard_name, "categories": flagged},
                error_class="GuardrailViolation",
                error_message=f"Guard {guard_name} blocked: {flagged}",
                reason=DLQReason.UNEXPECTED,
            )
            await writer.write(envelope)
        except Exception as exc:  # noqa: BLE001
            logger.error("AIPolicyEnforcer: DLQ publish failed: %s", exc)

    # ── Output guards ──────────────────────────────────────────────────────────

    async def guard_output(
        self, response: "AIResponse", policy: "AIPolicySpec"
    ) -> None:
        """Применить :attr:`AIPolicySpec.output_guards` к ``response.content``.

        Поддерживаемые guard'ы:
        - ``"llama_guard:safe_v3"`` — Llama Guard 3 (GGUF self-hosted)
        - ``"llama_guard:*"`` — любой Llama Guard variant

        Raises:
            GuardrailViolationError: При ``on_block="fail"``.
        """
        if not policy.output_guards or not response.content:
            return

        for ref in policy.output_guards:
            await self._guard_output_one(response, ref)

    async def _guard_output_one(
        self, response: "AIResponse", ref: "GuardRef"
    ) -> None:
        """Apply single output guard ref."""
        name = ref.name.lower()
        on_block = ref.on_block

        if not name.startswith("llama_guard:"):
            logger.warning(
                "AIPolicyEnforcer: unknown output guard %r — skipped", name
            )
            return

        runtime = self._llama_guard_runtime
        if runtime is None:
            logger.debug(
                "AIPolicyEnforcer: llama_guard runtime not configured — output guard skipped"
            )
            return

        try:
            result = await runtime.classify(response.content)
        except Exception as exc:  # noqa: BLE001
            logger.error("AIPolicyEnforcer: LlamaGuard classify failed: %s", exc)
            if on_block == "fail":
                raise GuardrailViolationError(
                    guard_name=ref.name,
                    flagged_categories=["llamaguard_error"],
                    on_block=on_block,
                    content=response.content,
                ) from exc
            return

        if not result.safe:
            self._handle_guard_block(
                guard_name=ref.name,
                flagged=result.flagged_categories,
                on_block=on_block,
                content=response.content,
            )

    # ── Sanitizers (stub, S25 W4 + S26 W2) ────────────────────────────────────

    async def sanitize_input(
        self, request: "AIRequest", policy: "AIPolicySpec"
    ) -> str:
        """Применить :attr:`AIPolicySpec.input_sanitizers`.

        Raises:
            NotImplementedError: S25 W4 (PIITokenizer integration).
        """
        del request, policy
        raise NotImplementedError("S25 W4: PIITokenizer integration (ADR-NEW-21)")

    async def sanitize_output(
        self, response: "AIResponse", policy: "AIPolicySpec"
    ) -> "AIResponse":
        """Применить :attr:`AIPolicySpec.output_sanitizers`.

        Raises:
            NotImplementedError: S25 W4 + S26 W2 (Presidio + Outlines).
        """
        del policy
        raise NotImplementedError("S25 W4 + S26 W2: output sanitizers")
