from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from src.backend.core.ai.errors import GuardrailViolationError


class HandleMixin:
    """handle guard block + DLQ publish (2 methods) для AIPolicyEnforcer. S67 W2 extraction."""

    __slots__ = ()

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
