"""AgentSandboxSelector — runtime sandbox selector (W9 P2-13 Phase 5).

W9 P2-13 Phase 5 (cycle 153): извлечено из ``services/ai/agent_sandbox.py``
(601 LOC god-module).

S172 M5 (ARC-008): runtime sandbox selector. Returns :class:`AgentSandbox`
instance по ``default_agent_sandbox`` config string. Caller может override
(например, ``AgentSandboxSelector.from_string("e2b")``).

Back-compat: ``services/ai/agent_sandbox.py`` (file) продолжает re-export
через thin ``__init__.py`` shim (см. ADR-0330).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from src.backend.services.ai.agent_sandbox._process_pool import (
        ProcessPoolAgentSandbox,
    )

from src.backend.services.ai.agent_sandbox._types import AgentSandboxConfigError

_logger = get_logger(__name__)


class AgentSandboxSelector:
    """S172 M5 (ARC-008) — runtime sandbox selector.

    Returns :class:`AgentSandbox` instance по ``default_agent_sandbox``
    config string. Caller может override (например,
    :func:`AgentSandboxSelector.from_string("e2b")`).

    Args:
        default_kind: ``"in_process"`` / ``"process_pool"`` / ``"e2b"``.
        e2b_api_key: explicit API key для ``"e2b"`` backend (optional).

    """

    def __init__(
        self, *, default_kind: str = "process_pool", e2b_api_key: str | None = None
    ) -> None:
        self._default_kind = default_kind
        self._e2b_api_key = e2b_api_key

    def select(self, kind: str | None = None) -> Any:
        """Возвращает singleton sandbox instance по kind."""
        from src.backend.services.ai.agent_sandbox._e2b import E2BAgentSandbox
        from src.backend.services.ai.agent_sandbox._in_process import (
            InProcessAgentSandbox,
        )

        chosen = kind or self._default_kind
        if chosen == "in_process":
            return InProcessAgentSandbox()
        if chosen == "process_pool":
            return get_process_pool_agent_sandbox()
        if chosen == "e2b":
            # ARC-008 M5 S-2: warning если нет API key.
            if not self._e2b_api_key and not os.getenv("E2B_API_KEY"):
                _logger.warning(
                    "AgentSandboxSelector: e2b backend selected but "
                    "neither ctor e2b_api_key nor E2B_API_KEY env var set. "
                    "run_react() will raise AgentSandboxConfigError."
                )
            return E2BAgentSandbox(api_key=self._e2b_api_key)
        raise AgentSandboxConfigError(
            f"Unknown sandbox kind: {chosen!r}. "
            f"Expected one of: in_process, process_pool, e2b."
        )


def resolve_agent_sandbox(
    *,
    default_kind: str | None = None,
    e2b_api_key: str | None = None,
    use_settings_default: bool = True,
) -> Any:
    """Convenience wrapper — singleton :class:`AgentSandboxSelector`.

    M5.2 review wiring: ``AIWorkspaceSettings.default_agent_sandbox``
    читается через :func:`_get_default_kind_from_settings` (lazy-import).
    Caller может override через ``default_kind`` kwarg или
    ``use_settings_default=False``.

    Args:
        default_kind: Override для ``AIWorkspaceSettings.default_agent_sandbox``.
            ``None`` → читать из settings (M5.2 wiring).
        e2b_api_key: explicit API key для ``"e2b"`` backend.
        use_settings_default: ``False`` → fallback на hardcoded
            ``"process_pool"`` (для тестов / для callers без DI).

    Returns:
        Singleton AgentSandbox instance (если ``process_pool``) или новый
        instance (если ``in_process`` / ``e2b``).

    """
    if default_kind is None and use_settings_default:
        try:
            from src.backend.core.config.ai import ai_workspace_settings

            default_kind = str(ai_workspace_settings.default_agent_sandbox)
        except (ImportError, AttributeError) as ai_settings_exc:
            # D-A1-04 fix (cycle 38): narrow exceptions + observability.
            # Bare `except Exception` маскировал ImportError (ai_settings
            # module not ready) и AttributeError (неправильный settings).
            # Fallback "process_pool" — default-OFF-safe.
            from src.backend.core.logging import get_logger

            get_logger(__name__).debug(
                "agent_sandbox.default_kind_resolve_failed",
                extra={"error": str(ai_settings_exc)},
            )
            default_kind = "process_pool"

    return AgentSandboxSelector(
        default_kind=default_kind or "process_pool", e2b_api_key=e2b_api_key
    ).select()


_process_pool_sandbox: "ProcessPoolAgentSandbox | None" = None


def get_process_pool_agent_sandbox() -> "ProcessPoolAgentSandbox":
    """Singleton process-pool sandbox (lazy)."""
    global _process_pool_sandbox
    if _process_pool_sandbox is None:
        from src.backend.services.ai.agent_sandbox._process_pool import (
            ProcessPoolAgentSandbox,
        )

        _process_pool_sandbox = ProcessPoolAgentSandbox(max_workers=1)
    return _process_pool_sandbox
