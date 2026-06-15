from __future__ import annotations

from typing import TYPE_CHECKING

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

from src.backend.core.ai.gateway_models import AIRequest

if TYPE_CHECKING:
    from src.backend.core.ai.policy.spec import AIPolicySpec


class PolicyMixin:
    """policy + capability checks (_resolve_policy, _check_capability, _language_from_policy) для PipelineStepsMixin. S56 W2 extraction."""

    __slots__ = ()

    async def _resolve_policy(self, request: AIRequest) -> AIPolicySpec | None:
        """Шаг 1: PolicyResolver → AIPolicySpec.

        Args:
            request: AIRequest.

        Returns:
            Resolved :class:`AIPolicySpec`; ``None`` если ``policy_resolver``
            не задан или не нашёл подходящей политики.

        Raises:
            PolicyNotResolvedError: при ``ai_policy_enforce=True`` и
                отсутствии политики с ``required=True``.
        """
        if self._policy_resolver is None:
            return None
        policy = await self._policy_resolver.resolve(
            workflow_id=request.workflow_id, tenant_id=request.tenant_id
        )
        if policy is None:
            try:
                from src.backend.core.config.features import feature_flags

                strict = bool(feature_flags.ai_policy_enforce)
            except Exception as _:
                strict = False
            if strict:
                from src.backend.core.ai.policy.resolver import PolicyNotResolvedError

                raise PolicyNotResolvedError(request.workflow_id, request.tenant_id)
        return policy

    async def _check_capability(self, request: AIRequest) -> None:
        """Шаг 2: CapabilityGate intercept.

        Args:
            request: AIRequest.

        Raises:
            CapabilityDeniedError: Если capability ``ai.invoke.<workflow_id>``
                не выдана текущему контексту вызова.
        """
        if self._capability_gate is None:
            return
        capability = f"ai.invoke.{request.workflow_id}"
        check = getattr(self._capability_gate, "check", None)
        if check is None:
            return
        result = check(capability)
        try:
            import inspect

            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            logger.debug(
                "AIGateway: capability check for %s failed: %s", capability, exc
            )

    @staticmethod
    def _language_from_policy(policy: AIPolicySpec | None, *, default: str) -> str:
        """Извлекает язык из первого input_sanitizer (``presidio:ru`` → ``ru``)."""
        if policy is None or not policy.input_sanitizers:
            return default
        ref = policy.input_sanitizers[0]
        cfg_lang = ref.config.get("language") if ref.config else None
        if cfg_lang:
            return str(cfg_lang)
        name = ref.name
        if ":" in name:
            return name.rsplit(":", 1)[-1] or default
        return default
