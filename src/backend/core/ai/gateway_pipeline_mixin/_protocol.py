"""Structural protocol for AIGateway PipelineStepsMixin family.

Sprint 36 (tech-debt): объявляет cross-mixin атрибуты и хелперы, чтобы
mypy видел ``self._policy_resolver``, ``self._resolve_sanitizer()`` и т.д.
внутри каждого миксина.
"""

from __future__ import annotations

from typing import Any, Protocol

from src.backend.core.ai.gateway_models import AIRequest, AIResponse
from src.backend.core.ai.policy.spec import AIPolicySpec


class _PipelineStepsProtocol(Protocol):
    """Общий контракт для PolicyMixin / InputMixin / LlmInvocationMixin / OutputMixin / ObservabilityMixin."""

    _policy_resolver: Any
    _capability_gate: Any
    _audit_service: Any
    _cost_tracker: Any
    _sanitizer: Any
    _llm_gateway: Any
    _policy_enforcer: Any
    _last_input_replacements: dict[str, Any]
    _last_input_pii_detected: bool

    async def _resolve_policy(self, request: AIRequest) -> AIPolicySpec | None: ...

    async def _check_capability(self, request: AIRequest) -> None: ...

    @staticmethod
    def _language_from_policy(policy: AIPolicySpec | None, *, default: str) -> str: ...

    def _resolve_sanitizer(self) -> Any | None: ...

    async def _apply_input_sanitizers(
        self, request: AIRequest, policy: AIPolicySpec | None
    ) -> str: ...

    async def _apply_input_guards(
        self, sanitized: str, policy: AIPolicySpec | None
    ) -> list[Any]: ...

    async def _render_prompt(
        self, request: AIRequest, policy: AIPolicySpec | None, sanitized: str
    ) -> str: ...

    async def _invoke_llm(
        self, rendered: str, policy: AIPolicySpec | None, stream: bool
    ) -> AIResponse: ...

    @staticmethod
    def _provider_from_model(model: str) -> str: ...

    async def _apply_output_guards(
        self, response: AIResponse, policy: AIPolicySpec | None
    ) -> list[Any]: ...

    async def _apply_output_sanitizers(
        self, response: AIResponse, policy: AIPolicySpec | None
    ) -> AIResponse: ...

    def _resolve_llm_gateway(self) -> Any: ...

    async def _audit_emit(
        self, request: AIRequest, policy: AIPolicySpec | None, response: AIResponse
    ) -> None: ...

    async def _cost_track(
        self, request: AIRequest, policy: AIPolicySpec | None, response: AIResponse
    ) -> None: ...
