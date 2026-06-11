from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.core.interfaces.ai_clients import AISanitizerProtocol

from src.backend.core.logging import get_logger

logger = get_logger(__name__)


class PolicyMixin:
    """policy/authz gates (_policy_gate, _resolve_authz_gateway, _policy_gate_deny) для AIAgentService. S54 W2 extraction."""

    # State attrs + cross-method hints (S54 W2: class-level annotations for mypy MRO)
    _sanitizer: "AISanitizerProtocol"
    _ai_cfg: Any
    _providers: dict[str, Any]
    _open_webui: Any
    _waf_headers: Any
    _waf_url: Any
    _agent_metrics_service: Any
    _agent_tracer: Any
    _agent_redis: Any
    _get_http_client: Any
    _extract_agent_response: Any
    _call_perplexity: Any

    _maybe_augment_with_rag: Any
    _get_metrics_service: Any
    _resolve_rag_service: Any

    __slots__ = ()

    async def _policy_gate(
        self,
        *,
        model: str,
        tenant_id: str | None,
        route_id: str | None,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Block 1.5 (gap-ai-1.5, ADR-0072): authorize LLM-call через AuthorizationGateway.

        Возвращает:
            None — если gate disabled или decision.allowed=True (continue);
            dict-error-envelope — если gate отрицает либо unavailable (deny).

        Fail-closed: любое исключение (ImportError / RuntimeError /
        AttributeError) → возврат deny-envelope + audit-event
        ``ai.llm.policy.gate.unavailable``. Никогда allow-on-error.
        """
        try:
            from src.backend.core.config.ai_2026 import ai_agent_settings
        except Exception as _:
            return None
        if not ai_agent_settings.policy_gate_enabled:
            return None

        principal = tenant_id or (metadata or {}).get("tenant_id") or "anonymous"
        context: dict[str, Any] = {
            "model": model,
            "route_id": route_id,
            "tenant_id": principal,
        }
        if metadata:
            context["request_metadata"] = metadata

        try:
            gateway = self._resolve_authz_gateway()
        except Exception as exc:
            logger.warning("ai_policy_gate_unavailable: %s", exc)
            return self._policy_gate_deny(
                principal=str(principal),
                reason="ai.llm.policy.gate.unavailable",
                detail=str(exc),
            )

        if gateway is None:
            logger.warning("ai_policy_gate_unavailable: gateway is None (fail-closed)")
            return self._policy_gate_deny(
                principal=str(principal),
                reason="ai.llm.policy.gate.unavailable",
                detail="AuthorizationGateway не зарегистрирован",
            )

        try:
            decision = await gateway.authorize(
                principal=str(principal),
                resource="ai:llm",
                action="call",
                context=context,
            )
        except Exception as exc:
            logger.warning("ai_policy_gate_authorize_failed: %s", exc)
            return self._policy_gate_deny(
                principal=str(principal),
                reason="ai.llm.policy.gate.error",
                detail=f"{type(exc).__name__}: {exc}",
            )

        if not decision.allowed:
            reasons = [
                {"source": r.source, "outcome": r.outcome, "detail": r.detail}
                for r in decision.reasons
            ]
            logger.warning(
                "ai_policy_gate_denied",
                extra={
                    "principal": principal,
                    "model": model,
                    "route_id": route_id,
                    "correlation_id": decision.correlation_id,
                    "reasons": reasons,
                },
            )
            return {
                "success": False,
                "error": "ai.llm.policy.gate.denied",
                "correlation_id": decision.correlation_id,
                "reasons": reasons,
            }
        return None

    @staticmethod
    def _resolve_authz_gateway() -> Any:
        """Lazy resolve :class:`AuthorizationGateway` через DI-provider.

        Returns:
            Экземпляр gateway либо ``None`` (provider не зарегистрирован).
            Не бросает исключения — все ошибки идут в caller (fail-closed).
        """
        try:
            from src.backend.core.di.app_state import get_app_ref

            app = get_app_ref()
            if app is None:
                return None
            return getattr(app.state, "authorization_gateway", None)
        except Exception as _:
            return None

    @staticmethod
    def _policy_gate_deny(
        *, principal: str, reason: str, detail: str
    ) -> dict[str, Any]:
        """Возвращает унифицированный deny-envelope для policy-gate."""
        return {
            "success": False,
            "error": reason,
            "principal": principal,
            "detail": detail,
        }
