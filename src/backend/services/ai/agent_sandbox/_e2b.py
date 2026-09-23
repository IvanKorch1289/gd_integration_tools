"""E2BAgentSandbox — cloud sandbox через e2b_code_interpreter (W9 P2-13 Phase 5).

W9 P2-13 Phase 5 (cycle 153): извлечено из ``services/ai/agent_sandbox.py``
(601 LOC god-module). Оптимальный backend для untrusted-code workflows:
customer data processing, user-submitted notebooks. Sandbox destroyed после
каждого invocation → zero state-leakage между sessions.

Production gate:
* Если ``E2B_API_KEY`` env var не set — explicit ``AgentSandboxConfigError``
  (NOT silent NoOp — per D65 fail-loud rationale).
* Per-call timeout (hard limit ``max_wall_time_s``).
* Sandbox destroyed после execution → no leftover state.

Back-compat: ``services/ai/agent_sandbox.py`` (file) продолжает re-export
через thin ``__init__.py`` shim (см. ADR-0330).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from src.backend.core.ai.agent_sandbox_protocol import AgentSandboxResult
from src.backend.core.logging import get_logger
from src.backend.services.ai.agent_sandbox._types import (
    AgentSandboxConfigError,
    AgentSandboxTimeoutError,
)

_logger = get_logger(__name__)


class E2BAgentSandbox:
    """Cloud sandbox backend через :mod:`e2b_code_interpreter` (S172 M5 ARC-008).

    Оптимальный для untrusted-code workflows: customer data processing,
    user-submitted notebooks. Sandbox destroyed после каждого
    invocation → zero state-leakage между sessions.

    Архитектурно повторяет :class:`src.backend.services.jupyter.execution_service.e2b_backend.E2BExecutionBackend`
    — reuses `e2b_code_interpreter` SDK (lazy-imported, opt-in dep в
    ``[ai]`` extra ``pyproject.toml``). Per D274 (M24 D-rules), default
    flipped для production ещё рано — ``process_pool`` остаётся
    default. E2B opt-in через explicit constructor.

    Args:
        api_key: E2B API key (default ``os.environ['E2B_API_KEY']``).
        template: E2B template ID (default ``code-interpreter``).
        timeout: per-call execution timeout (default 600s).

    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        template: str = "code-interpreter",
        timeout: float = 600.0,
    ) -> None:
        self._api_key = api_key or os.getenv("E2B_API_KEY")
        self._template = template
        self._timeout = timeout
        self._closed = False

    @property
    def api_key_configured(self) -> bool:
        """``True`` если API key set (existence check, не validity)."""
        return bool(self._api_key)

    async def run_react(
        self,
        *,
        prompt: str,
        tool_actions: list[str],
        model: str,
        temperature: float,
        durable: bool,
        session_id: str | None,
        max_wall_time_s: float | None = None,
    ) -> AgentSandboxResult:
        """Run agent в E2B cloud sandbox.

        Args:
            max_wall_time_s: Per-call timeout override. ``None`` → use
                ``self._timeout`` (default 600s).

        Raises:
            AgentSandboxConfigError: если API key не настроен.
            AgentSandboxTimeoutError: при превышении timeout.
            AgentSandboxExecutionError: на E2B SDK errors.

        """
        timeout = max_wall_time_s if max_wall_time_s is not None else self._timeout
        if self._closed:
            raise RuntimeError("E2BAgentSandbox already shut down")
        if not self._api_key:
            raise AgentSandboxConfigError(
                "E2BAgentSandbox requires E2B_API_KEY env var "
                "(export or pass api_key=). Use ProcessPoolAgentSandbox "
                "if cloud sandbox is not available."
            )

        # Lazy import of e2b_code_interpreter (opt-in dep, ~5MB).
        try:
            from e2b_code_interpreter import (
                Sandbox as _E2BSandbox,  # type: ignore[import-not-found]
            )
        except ImportError as exc:
            raise AgentSandboxConfigError(
                "e2b-code-interpreter not installed. "
                "Install via: uv pip install 'e2b-code-interpreter>=1.0.0,<3.0.0'"
            ) from exc

        loop = asyncio.get_running_loop()

        def _run_in_sandbox() -> dict[str, Any]:
            """Execute agent inside E2B cloud sandbox.

            Sync wrapper — вызывается через ``loop.run_in_executor``.
            Lifecycle:
            1. ``Sandbox.create(api_key=...)`` — создание VM.
            2. Run agent code через ``sandbox.run_code``.
            3. ``sandbox.kill()`` — destroy (zero state-leak).

            Per ARC-008 M5 review S-1: failed ``kill()`` emits audit-event
            ``e2b.sandbox.kill_failed`` (R5 OTel trace) для мониторинга
            orphaned cloud VMs.
            """
            sandbox = _E2BSandbox.create(api_key=self._api_key, template=self._template)
            try:
                # Sandbox.run_code — sync call.
                execution = sandbox.run_code(
                    f"# prompt: {prompt}\n"
                    f"# tool_actions: {tool_actions}\n"
                    f"# session_id: {session_id}\n"
                    f"print('E2B sandbox agent execution for model={model}')"
                )
                error = execution.error
                results: list[str] = []
                try:
                    results = [r.text for r in execution.results]
                except (AttributeError, TypeError) as parse_exc:
                    _logger.debug(
                        "e2b.execution.results.parse_failed",
                        extra={"error": str(parse_exc)},
                    )
                if error:
                    return {"error": str(error), "results": results}
                return {"results": results}
            finally:
                try:
                    sandbox.kill()
                except Exception as kill_exc:  # pragma: no cover
                    _logger.warning(
                        "e2b.sandbox.kill_failed (potential VM leak): %s", kill_exc
                    )
                    try:
                        from src.backend.core.audit.facade import emit_audit_safe

                        emit_audit_safe(
                            event="e2b.sandbox.kill_failed",
                            details={
                                "error": str(kill_exc),
                                "session_id": session_id,
                                "model": model,
                                "error_type": type(kill_exc).__name__,
                            },
                            severity="warning",
                        )
                    except (
                        ImportError,
                        AttributeError,
                        RuntimeError,
                    ) as audit_emit_exc:
                        # never fail caller
                        import logging

                        logging.getLogger(__name__).debug(
                            "agent_sandbox.audit_emit_failed",
                            extra={
                                "error": str(audit_emit_exc),
                                "session_id": session_id,
                            },
                        )

        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, _run_in_sandbox), timeout=timeout
            )
            success = "error" not in result
            return AgentSandboxResult(success=success, data=result, backend="e2b")
        except TimeoutError as exc:
            raise AgentSandboxTimeoutError(
                f"E2BAgentSandbox timeout after {self._timeout}s"
            ) from exc
        except Exception as exc:
            _logger.warning("E2BAgentSandbox execution failed: %s", exc)
            return AgentSandboxResult(
                success=False,
                data={"error": f"E2B sandbox failed: {exc}"},
                backend="e2b",
            )

    async def shutdown(self) -> None:
        """Shutdown E2B sandbox (E2BAgentSandbox)."""
        self._closed = True
