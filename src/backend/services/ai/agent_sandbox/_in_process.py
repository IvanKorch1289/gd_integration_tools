"""InProcessAgentSandbox — zero-isolation in-process execution (W9 P2-13 Phase 5).

W9 P2-13 Phase 5 (cycle 153): извлечено из ``services/ai/agent_sandbox.py``
(601 LOC god-module). DEPRECATED в production (per ARC-008, S172 M5).

Production gate: hard-fail при ``GD_INTEGRATION_PRODUCTION=1`` или
``feature_flags.ai_in_process_sandbox_disabled=True`` (default ON).

Back-compat: ``services/ai/agent_sandbox.py`` (file) продолжает re-export
через thin ``__init__.py`` shim (см. ADR-0330).
"""

from __future__ import annotations

import os
import warnings
from typing import Any

from src.backend.core.ai.agent_sandbox_protocol import AgentSandboxResult
from src.backend.core.logging import get_logger

# S172 M5 (ARC-008) — production gate: при ``default_agent_sandbox ==
# "in_process"`` и ``GD_INTEGRATION_PRODUCTION=1`` — raise at runtime.
# Defensive для ситуаций когда feature-flag bypass завершён.
_IN_PROCESS_PROD_BLOCKED: bool = bool(os.environ.get("GD_INTEGRATION_PRODUCTION"))

_logger = get_logger(__name__)


class InProcessAgentSandbox:
    """In-process sandbox — zero isolation (DEPRECATED в production).

    Используется когда ``isolated=False`` или когда out-of-process backend
    недоступен.

    S172 M5 (ARC-008): при construction в production env — emits
    :class:`DeprecationWarning`. Hard-fail при
    ``GD_INTEGRATION_PRODUCTION=1`` (defense-in-depth против silent
    regressions).
    """

    def __init__(self) -> None:
        # Hard gate (defense-in-depth): in-process НИКОГДА не должен
        # работать в production. Если feature-flag bypass завершён —
        # явный fail-loud. Per D65 / D270 rationale.
        # Cycle 33 AI2: also check feature_flags.ai_in_process_sandbox_disabled
        # (default ON). Operator must explicitly opt-out via feature flag
        # — environment variable GD_INTEGRATION_PRODUCTION alone was
        # bypassable in misconfigured deployments.
        if _IN_PROCESS_PROD_BLOCKED:
            raise RuntimeError(
                "InProcessAgentSandbox forbidden in production "
                "(GD_INTEGRATION_PRODUCTION=1). Use ProcessPool or E2B backend. "
                "See ARC-008 / docs/security/sandbox_backends.md."
            )
        try:
            from src.backend.core.config.features import feature_flags

            if getattr(
                feature_flags,
                "ai_in_process_sandbox_disabled",
                True,  # default: BLOCKED if feature_flags module unavailable
            ):
                raise RuntimeError(
                    "InProcessAgentSandbox blocked by feature_flags."
                    "ai_in_process_sandbox_disabled=True (default). "
                    "Use ProcessPoolAgentSandbox or E2BAgentSandbox. "
                    "To override (DEV ONLY): set FEATURE_AI_IN_PROCESS_SANDBOX_DISABLED=false."
                )
        except ImportError:
            # If feature_flags module unavailable → fail-closed
            raise RuntimeError(
                "InProcessAgentSandbox: feature_flags module unavailable, "
                "defaulting to BLOCKED for safety. Use ProcessPoolAgentSandbox."
            )
        warnings.warn(
            "InProcessAgentSandbox is DEPRECATED since Sprint 172 (ARC-008). "
            "Zero process isolation — same memory + file descriptors as parent. "
            "Use ProcessPoolAgentSandbox (default) or E2BAgentSandbox (opt-in) "
            "for any production / dev_shared workload. "
            "Will be removed in Sprint 175.",
            DeprecationWarning,
            stacklevel=2,
        )
        # Audit event для security visibility: даже вне production
        # констружение zero-isolation sandbox должно быть видимым
        # в audit-log (ops teams могут alerting на этот event).
        try:
            from src.backend.core.audit.facade import emit_audit_safe

            emit_audit_safe(
                event="ai.sandbox.zero_isolation_constructed",
                details={
                    "backend": "in_process",
                    "warning": "Zero process isolation — DEPRECATED",
                },
                severity="warning",
            )
        except Exception as audit_exc:  # never fail caller on audit error
            # D-A9-04 fix (cycle 21): логируем audit failure вместо silent pass.
            # Раньше bare `except Exception: pass` маскировал audit system
            # failures — observability gap. Теперь: logger.warning + metrics.
            _logger.warning(
                "audit.zero_isolation_constructed.failed",
                extra={"error": str(audit_exc)},
            )

    async def run_react(
        self,
        *,
        prompt: str,
        tool_actions: list[str],
        model: str,
        temperature: float,
        durable: bool,
        session_id: str | None,
    ) -> AgentSandboxResult:
        """Run ReAct agent loop (Reasoning + Acting)."""
        from src.backend.services.ai.ai_graph import build_and_run_agent

        result = await build_and_run_agent(
            prompt=prompt,
            tool_actions=tool_actions,
            model=model,
            temperature=temperature,
            durable=durable,
            session_id=session_id,
        )
        success = "error" not in result
        return AgentSandboxResult(success=success, data=result, backend="in_process")

    async def shutdown(self) -> None:
        """Shutdown E2B sandbox (InProcessAgentSandbox)."""
        return


def _sync_run_react(
    prompt: str,
    tool_actions: list[str],
    model: str,
    temperature: float,
    durable: bool,
    session_id: str | None,
) -> dict[str, Any]:
    """Sync entrypoint для ``ProcessPoolExecutor``.

    Выполняется в spawn-воркере без доступа к event loop родителя.
    """
    import asyncio

    from src.backend.services.ai.ai_graph import build_and_run_agent

    return asyncio.run(
        build_and_run_agent(
            prompt=prompt,
            tool_actions=tool_actions,
            model=model,
            temperature=temperature,
            durable=durable,
            session_id=session_id,
        )
    )
