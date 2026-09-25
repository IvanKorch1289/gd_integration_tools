"""Focused tests: W9 P2-13 Phase 5 — services/ai/agent_sandbox god-module split.

Проверяет:
1. Shim (services/ai/agent_sandbox.py file) re-exports все 8 публичных имён.
2. Submodules export classes/functions корректно.
3. Shim < 100 LOC (vs 601 original).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.services.ai.agent_sandbox import (
    AgentSandboxConfigError as ShimConfigError,
)
from src.backend.services.ai.agent_sandbox import AgentSandboxSelector as ShimSelector
from src.backend.services.ai.agent_sandbox import (
    AgentSandboxTimeoutError as ShimTimeoutError,
)
from src.backend.services.ai.agent_sandbox import E2BAgentSandbox as ShimE2B
from src.backend.services.ai.agent_sandbox import InProcessAgentSandbox as ShimInProcess
from src.backend.services.ai.agent_sandbox import (
    ProcessPoolAgentSandbox as ShimProcessPool,
)
from src.backend.services.ai.agent_sandbox import (
    get_process_pool_agent_sandbox as ShimGetProcessPool,
)
from src.backend.services.ai.agent_sandbox import resolve_agent_sandbox as ShimResolve
from src.backend.services.ai.agent_sandbox._e2b import E2BAgentSandbox as CanonicalE2B
from src.backend.services.ai.agent_sandbox._in_process import (
    InProcessAgentSandbox as CanonicalInProcess,
)
from src.backend.services.ai.agent_sandbox._process_pool import (
    ProcessPoolAgentSandbox as CanonicalProcessPool,
)
from src.backend.services.ai.agent_sandbox._selector import (
    AgentSandboxSelector as CanonicalSelector,
)
from src.backend.services.ai.agent_sandbox._selector import (
    get_process_pool_agent_sandbox as CanonicalGetProcessPool,
)
from src.backend.services.ai.agent_sandbox._selector import (
    resolve_agent_sandbox as CanonicalResolve,
)
from src.backend.services.ai.agent_sandbox._types import (
    AgentSandboxConfigError as CanonicalConfigError,
)
from src.backend.services.ai.agent_sandbox._types import (
    AgentSandboxTimeoutError as CanonicalTimeoutError,
)


class TestBackCompatIdentity:
    """Shim re-exports идентичны canonical (id-equal)."""

    @pytest.mark.parametrize(
        "shim,canonical,name",
        [
            (ShimConfigError, CanonicalConfigError, "AgentSandboxConfigError"),
            (ShimTimeoutError, CanonicalTimeoutError, "AgentSandboxTimeoutError"),
            (ShimInProcess, CanonicalInProcess, "InProcessAgentSandbox"),
            (ShimProcessPool, CanonicalProcessPool, "ProcessPoolAgentSandbox"),
            (ShimE2B, CanonicalE2B, "E2BAgentSandbox"),
            (ShimSelector, CanonicalSelector, "AgentSandboxSelector"),
            (ShimResolve, CanonicalResolve, "resolve_agent_sandbox"),
            (
                ShimGetProcessPool,
                CanonicalGetProcessPool,
                "get_process_pool_agent_sandbox",
            ),
        ],
    )
    def test_shim_returns_canonical(self, shim, canonical, name: str) -> None:
        """Shim импортирует тот же class/function (id-equal)."""
        assert shim is canonical, (
            f"{name}: shim {shim!r}@{id(shim)} != canonical {canonical!r}@{id(canonical)}"
        )


class TestSubmoduleExports:
    """Каждый submodule экспортирует ожидаемые имена."""

    def test_types_submodule(self) -> None:
        """_types экспортирует 2 exception classes."""
        from src.backend.services.ai.agent_sandbox import _types

        assert _types.AgentSandboxConfigError is CanonicalConfigError
        assert _types.AgentSandboxTimeoutError is CanonicalTimeoutError

    def test_in_process_submodule(self) -> None:
        """_in_process экспортирует InProcessAgentSandbox + _sync_run_react helper."""
        from src.backend.services.ai.agent_sandbox import _in_process

        assert _in_process.InProcessAgentSandbox is CanonicalInProcess
        assert callable(_in_process._sync_run_react)

    def test_process_pool_submodule(self) -> None:
        """_process_pool экспортирует ProcessPoolAgentSandbox."""
        from src.backend.services.ai.agent_sandbox import _process_pool

        assert _process_pool.ProcessPoolAgentSandbox is CanonicalProcessPool

    def test_e2b_submodule(self) -> None:
        """_e2b экспортирует E2BAgentSandbox."""
        from src.backend.services.ai.agent_sandbox import _e2b

        assert _e2b.E2BAgentSandbox is CanonicalE2B

    def test_selector_submodule(self) -> None:
        """_selector экспортирует AgentSandboxSelector + helpers."""
        from src.backend.services.ai.agent_sandbox import _selector

        assert _selector.AgentSandboxSelector is CanonicalSelector
        assert _selector.resolve_agent_sandbox is CanonicalResolve
        assert _selector.get_process_pool_agent_sandbox is CanonicalGetProcessPool


class TestShimReduction:
    """Shim file dramatically reduced (601 → 66 LOC)."""

    def test_shim_under_100_loc(self) -> None:
        """Shim file < 100 LOC."""
        shim_path = Path("src/backend/services/ai/agent_sandbox.py")
        loc = sum(1 for _ in shim_path.open())
        assert loc < 100, f"shim {loc} LOC (target: <100, было 601)"


class TestSubmoduleSplitCompliance:
    """V15 forbidden pattern compliance — submodules < 500 LOC."""

    def test_all_submodules_under_500_loc(self) -> None:
        """Каждый submodule < 500 LOC (V15 forbidden pattern)."""
        sandbox_pkg = Path("src/backend/services/ai/agent_sandbox")
        for py_file in sorted(sandbox_pkg.glob("_*.py")):
            loc = sum(1 for _ in py_file.open())
            assert loc < 500, (
                f"{py_file.name} = {loc} LOC (V15 forbidden: >500 = god-module)"
            )


class TestExceptionInstantiation:
    """Custom exceptions можно raise + message передаётся."""

    def test_config_error_message(self) -> None:
        """AgentSandboxConfigError принимает message."""
        exc = CanonicalConfigError("missing E2B_API_KEY")
        assert "missing E2B_API_KEY" in str(exc)
        assert isinstance(exc, Exception)

    def test_timeout_error_message(self) -> None:
        """AgentSandboxTimeoutError принимает message."""
        exc = CanonicalTimeoutError("timeout after 600s")
        assert "timeout after 600s" in str(exc)
        assert isinstance(exc, Exception)
