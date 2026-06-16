from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from src.backend.core.ai.errors import GuardResult
    from src.backend.core.ai.gateway import AIRequest, AIResponse
    from src.backend.core.ai.policy.spec import AIPolicySpec, GuardRef
    from src.backend.core.messaging.dlq import DLQWriter


class _AIPolicyEnforcerProtocol(Protocol):
    """Cross-mixin protocol for AIPolicyEnforcer cluster."""

    _pii_tokenizer: object | None
    _nemo_runtime: object | None
    _llama_guard_runtime: object | None
    _llm_guard_client: Any | None
    _dlq_writer: DLQWriter | None

    async def guard_input(
        self, prompt: str, policy: AIPolicySpec
    ) -> list[GuardResult]: ...
    async def _guard_input_one(
        self, prompt: str, ref: GuardRef
    ) -> GuardResult | None: ...
    async def _guard_input_rebuff(
        self, prompt: str, ref: GuardRef, on_block: str
    ) -> GuardResult: ...
    async def _guard_input_lakera(
        self, prompt: str, ref: GuardRef, on_block: str
    ) -> GuardResult: ...
    async def _guard_input_llm_guard(
        self, prompt: str, ref: GuardRef, on_block: str
    ) -> GuardResult: ...
    async def guard_output(
        self, response: AIResponse, policy: AIPolicySpec
    ) -> list[GuardResult]: ...
    async def _guard_output_one(
        self, response: AIResponse, ref: GuardRef
    ) -> GuardResult | None: ...
    async def sanitize_input(self, request: AIRequest, policy: AIPolicySpec) -> str: ...
    async def sanitize_output(
        self, response: AIResponse, policy: AIPolicySpec
    ) -> AIResponse: ...
    def _handle_guard_block(
        self, *, guard_name: str, flagged: list[str], on_block: str, content: str
    ) -> None: ...
    async def _publish_dlq(
        self, guard_name: str, flagged: list[str], content: str
    ) -> None: ...
