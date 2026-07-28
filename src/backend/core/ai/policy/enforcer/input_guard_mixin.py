from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.core.ai.policy.enforcer._protocol import _AIPolicyEnforcerProtocol
    from src.backend.core.ai.policy.spec import AIPolicySpec, GuardRef

from src.backend.core.ai.errors import GuardrailViolationError, GuardResult
from src.backend.core.logging import get_logger

logger = get_logger(__name__)


class InputGuardMixin:
    """input guard mixin для AIPolicyEnforcer. S67 W2 extraction.

    S172 audit (2026-07-16): Rebuff + llm_guard + nemo fallback paths removed
    (upstream archived 2026-07-16; см. ``research/agent-framework/REPORT.md`` F4.1, F4.2).
    Only ``lakera:<variant>`` remains as external provider.
    """

    __slots__ = ()

    if TYPE_CHECKING:
        _protocol_self: _AIPolicyEnforcerProtocol

    async def guard_input(
        self: "_AIPolicyEnforcerProtocol", prompt: str, policy: AIPolicySpec
    ) -> list[GuardResult]:
        """Применить :attr:`AIPolicySpec.input_guards` к sanitized prompt.

        Поддерживаемые guard'ы:
        - ``"lakera:<variant>"`` — внешний API (deprecated S172, см. tenant_config)
        - Остальные namespace — log warning + return None (S172 deferred).

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

        # S172 audit: nemo runtime call deferred — requires architecturally clean
        # integration path. See research/agent-framework/REPORT.md F4.1.
        if name.startswith("nemo:"):
            logger.warning(
                "AIPolicyEnforcer: nemo guard %r skipped (S172 deferred integration)",
                name,
                extra={"guard_ref": name, "category": "policy_deferred"},
            )
            return None

        # S172 audit: llm_guard archived 2026-07-16 (upstream gone).
        if name.startswith("llm_guard:") or name.startswith("llm-guard:"):
            logger.warning(
                "AIPolicyEnforcer: llm_guard %r не поддерживается (S172 — "
                "upstream archived 2026-07-16). Используйте lakera:.",
                name,
                extra={"guard_ref": name, "category": "policy_degraded"},
            )
            if on_block == "fail":
                raise GuardrailViolationError(
                    guard_name=ref.name,
                    flagged_categories=["llm_guard_archived"],
                    on_block=on_block,
                    content=prompt,
                )
            return GuardResult(
                guard_name=ref.name, verdict="warned", categories=["llm_guard_archived"]
            )

        # S172 audit: Rebuff archived 2026-07-16 (upstream gone).
        if name.startswith("rebuff:"):
            logger.warning(
                "AIPolicyEnforcer: rebuff guard %r не поддерживается (S172 — "
                "upstream archived 2026-07-16). Используйте lakera:.",
                name,
                extra={"guard_ref": name, "category": "policy_degraded"},
            )
            if on_block == "fail":
                raise GuardrailViolationError(
                    guard_name=ref.name,
                    flagged_categories=["rebuff_archived"],
                    on_block=on_block,
                    content=prompt,
                )
            return GuardResult(
                guard_name=ref.name, verdict="warned", categories=["rebuff_archived"]
            )

        # Lakera
        if name.startswith("lakera:"):
            return await self._guard_input_lakera(prompt, ref, on_block)

        logger.warning("AIPolicyEnforcer: unknown input guard %r — skipped", name)
        return None

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
            # P0 security (cycle 30): fail-closed by default when guard
            # provider is unavailable (network/timeout/5xx). Only an explicit
            # ``fail_open=True`` override allows continuation, and every
            # override is audit-logged for visibility.
            logger.warning("AIPolicyEnforcer: Lakera check failed: %s", exc)
            if not getattr(ref, "fail_open", False):
                raise GuardrailViolationError(
                    guard_name=ref.name,
                    flagged_categories=["guard_provider_unavailable"],
                    on_block="fail",
                    content=prompt,
                ) from exc
            # Explicit audited override (dev/staging with degraded provider).
            try:
                from src.backend.core.audit.facade import emit_audit_safe

                emit_audit_safe(
                    event="ai.guardrail.provider_failure",
                    details={
                        "guard": ref.name,
                        "provider_error": str(exc),
                        "fail_open": True,
                    },
                    severity="warning",
                )
            except Exception:  # pragma: no cover — audit must never block
                pass
            return GuardResult(
                guard_name=ref.name,
                verdict="warned",
                categories=["guard_provider_unavailable"],
            )
