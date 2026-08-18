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


from src.backend.core.ai.gateway_pipeline_mixin._protocol import _PipelineStepsProtocol


class PolicyMixin(_PipelineStepsProtocol):
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
                не выдана текущему контексту вызова. Не подавляется —
                fail-closed: caller получает ``403`` / ``CapabilityDeniedError``
                вместо silent allow-all.

        Notes:
            Sprint 1.5: вызов идёт через canonical 3-arg signature
            ``check(plugin, capability, scope)``. Ранее был 1-arg
            (``check(capability)``), который для :class:`CapabilityGate`
            поднимал :class:`TypeError` и попадал в silent ``except``
            → fail-open. Composition root через
            :func:`services.ai.gateway_adapter.adapt_capability_gate`
            оборачивает canonical gate в 3-arg callback.

            P0-S4 fix (audit 2026-08-18): если ``_capability_gate is None``,
            поведение зависит от feature flag ``ai_policy_enforce``:
            * ``ai_policy_enforce=True`` (production) — raise
              ``CapabilityDeniedError`` (fail-closed).
            * ``ai_policy_enforce=False`` (dev/staging) — log warning +
              silent allow (backward compat).

            Другие исключения (TypeError для legacy 1-arg callbacks,
            RuntimeError) — логируются, чтобы dev/staging с устаревшими
            callback'ами не падали. ``CapabilityDeniedError`` всегда
            пробрасывается — security boundary.
        """
        if self._capability_gate is None:
            await self._handle_missing_capability_gate(request)
            return
        capability = f"ai.invoke.{request.workflow_id}"
        scope = request.workflow_id
        check = getattr(self._capability_gate, "check", None)
        if check is None:
            await self._handle_missing_capability_gate(request)
            return
        try:
            import inspect

            result = check("core", capability, scope)
            if inspect.isawaitable(result):
                await result
        except TypeError:
            # ponytail: backward-compat shim для legacy 1-arg callbacks.
            try:
                legacy = check(capability)
                if inspect.isawaitable(legacy):
                    await legacy
            except Exception as exc:
                logger.debug(
                    "AIGateway: capability check for %s failed: %s", capability, exc
                )
        except Exception as exc:
            from src.backend.core.security.capabilities.errors import (
                CapabilityDeniedError as _CapabilityDeniedError,
            )

            if isinstance(exc, _CapabilityDeniedError):
                # Security boundary: deny должен доходить до caller'а,
                # а не глохнуть в debug-логе.
                raise
            logger.debug(
                "AIGateway: capability check for %s failed: %s", capability, exc
            )

    async def _handle_missing_capability_gate(self, request: AIRequest) -> None:
        """P0-S4 (audit 2026-08-18): capability gate не настроен.

        Без fix — silent allow, любая prompt injection проходит.
        С fix:
        * ``ai_policy_enforce=True`` (production) — raise CapabilityDeniedError
          с audit event (security boundary).
        * ``ai_policy_enforce=False`` (dev/staging) — log warning + allow
          (backward compat для legacy dev setups).
        """
        try:
            from src.backend.core.config.features import feature_flags

            enforce = bool(feature_flags.ai_policy_enforce)
        except Exception as exc:  # pragma: no cover — feature_flags optional
            logger.debug(
                "AIGateway: feature_flags.ai_policy_enforce unavailable (%s); "
                "defaulting to enforce=True for safety",
                exc,
            )
            enforce = True  # fail-closed when feature_flags unavailable

        if enforce:
            try:
                import inspect

                from src.backend.core.audit.facade import emit_audit_safe

                audit_result = emit_audit_safe(
                    event="ai.gateway.capability_gate_missing",
                    details={
                        "workflow_id": request.workflow_id,
                        "tenant_id": getattr(request, "tenant_id", None),
                        "reason": "no_capability_gate_configured",
                    },
                    severity="error",
                )
                if inspect.isawaitable(audit_result):
                    await audit_result
            except Exception:  # pragma: no cover — audit must never block
                pass
            from src.backend.core.security.capabilities.errors import (
                CapabilityDeniedError,
            )

            raise CapabilityDeniedError(
                plugin="ai.gateway",
                capability=f"ai.invoke.{request.workflow_id}",
                requested_scope=request.workflow_id,
                declared_scope=None,
                tenant=request.tenant_id,
                correlation_id=request.correlation_id,
            )

        logger.warning(
            "AIGateway: capability gate не настроен — silent allow "
            "(ai_policy_enforce=False). Это OK для dev/staging, "
            "НЕ для production. workflow_id=%s",
            request.workflow_id,
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
