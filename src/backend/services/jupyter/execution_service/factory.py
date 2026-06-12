"""S74 W2 — ExecutionBackendFactory: единая точка выбора backend.

FINAL_REPORT_V2 направление #1 #3: интегрировать NbClientExecutionBackend
через фабрику. До S74 backends создавались ad-hoc в caller'ах
(``NotebookExecutionService(settings)``, ``NbClientExecutionBackend()``).
Нет single source of truth → сложно enforce security policy, test
isolation, и runtime substitution (для mock'ов).

**Backend matrix** (S74 W2):
* ``"hub"`` — JupyterHub distributed (default для prod)
* ``"papermill"`` — local parameterized (S74 W1)
* ``"nbclient"`` — local bare-execute (S60 W1)
* ``"e2b"`` — cloud sandbox (Wave 1.7, lazy-import, S74 W2 stub)

**Selection**:
* ``ExecutionBackendFactory.create("hub", settings=settings)`` — explicit
* ``ExecutionBackendFactory.from_config(backend_kind=None)`` —
  auto-detect from settings (env: ``JUPYTER_BACKEND``)

**Security policy** (S74 W2 stub):
* ``"hub"`` — production default (JupyterHub auth, isolated kernels)
* ``"papermill"`` — opt-in local (developer machines, CI)
* ``"e2b"`` — для untrusted code execution (sandboxed cloud)

Usage::

    # Explicit
    factory = ExecutionBackendFactory()
    backend = factory.create("hub", settings=jupyter_hub_settings)

    # Auto-detect
    backend = factory.from_config()  # reads JUPYTER_BACKEND env

    # Mock для tests
    backend = factory.create("hub", settings=test_settings, override=mock_backend)
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Any

from src.backend.core.config.services.jupyter_hub import JupyterHubSettings
from src.backend.infrastructure.logging.factory import get_logger

_logger = get_logger("services.jupyter.factory")

__all__ = (
    "BackendKind",
    "ExecutionBackendFactory",
)


class BackendKind(str, Enum):
    """S74 W2 — enum для type-safe backend selection."""

    HUB = "hub"
    PAPERMILL = "papermill"
    NBCLIENT = "nbclient"
    E2B = "e2b"


class ExecutionBackendFactory:
    """S74 W2 — single source of truth для notebook execution backends.

    Singleton (singleton pattern через instance, не module-level) —
    multiple instances OK, но ``default_factory()`` возвращает
    shared default.
    """

    def __init__(self) -> None:
        self._backends: dict[str, Any] = {}

    def create(
        self,
        kind: str | BackendKind,
        *,
        settings: JupyterHubSettings | None = None,
        override: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Create notebook execution backend.

        Args:
            kind: backend type (BackendKind enum или str).
            settings: JupyterHubSettings (required для HUB kind).
            override: optional backend instance для test injection
                (skip creation, use provided instance).
            **kwargs: backend-specific params (kernel_name, timeout, etc.).

        Returns:
            Backend instance (NotebookExecutionService /
            PapermillExecutionBackend / NbClientExecutionBackend /
            E2BExecutionBackend).

        Raises:
            ValueError: unknown kind.
            ImportError: required package not installed.
        """
        if isinstance(kind, str):
            kind = BackendKind(kind.lower())

        # Test injection bypasses factory
        if override is not None:
            return override

        if kind == BackendKind.HUB:
            from src.backend.services.jupyter.execution_service import (
                NotebookExecutionService,
            )

            if settings is None:
                raise ValueError(
                    "HUB backend требует JupyterHubSettings (settings=...)"
                )
            return NotebookExecutionService(settings)
        elif kind == BackendKind.PAPERMILL:
            from src.backend.services.jupyter.execution_service import (
                PapermillExecutionBackend,
            )

            return PapermillExecutionBackend(**kwargs)
        elif kind == BackendKind.NBCLIENT:
            from src.backend.services.jupyter.execution_service import (
                NbClientExecutionBackend,
            )

            return NbClientExecutionBackend(**kwargs)
        elif kind == BackendKind.E2B:
            # S74 W2 stub: e2b ExecutionBackend not yet implemented.
            # e2b_sandbox exists (Wave 1.7, general code sandbox),
            # but notebook-specific ExecutionBackend is S74 W3+
            # (или deferred — needs separate epic).
            raise NotImplementedError(
                "E2B notebook ExecutionBackend — S74 W3+ (deferred). "
                "Current: e2b_sandbox для general code, не notebook-specific."
            )
        else:
            raise ValueError(f"Unknown backend kind: {kind!r}")

    def from_config(
        self,
        *,
        settings: JupyterHubSettings | None = None,
        **kwargs: Any,
    ) -> Any:
        """Auto-detect backend from environment (JUPYTER_BACKEND).

        Default: ``"hub"`` для production, ``"nbclient"`` для tests.

        Args:
            settings: JupyterHubSettings (passed если kind="hub").
            **kwargs: backend-specific params.

        Returns:
            Backend instance.
        """
        kind_str = os.getenv("JUPYTER_BACKEND", "hub")
        _logger.debug("Auto-detect backend: JUPYTER_BACKEND=%s", kind_str)
        return self.create(kind_str, settings=settings, **kwargs)


_default_factory: ExecutionBackendFactory | None = None


def get_default_factory() -> ExecutionBackendFactory:
    """Get shared default factory instance (S74 W2 singleton)."""
    global _default_factory
    if _default_factory is None:
        _default_factory = ExecutionBackendFactory()
    return _default_factory
