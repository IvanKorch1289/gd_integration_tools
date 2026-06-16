"""Regression test: S127 W1 — verify HttpClient dead-code removal.

S127 W1 removed the unused ``self.circuit_breaker = get_circuit_breaker()``
from ``HttpClient.__init__``. The instance attribute was created but never
referenced anywhere in the transport/http package, so it was pure dead
code (and the ``core.utils.circuit_breaker`` import that fed it is
deprecated since S38 — removed in Sprint 43 CB consolidation).

This test enforces the cleanup:
1. ``HttpClient`` must not reference ``circuit_breaker`` (static check).
2. The deprecated shim has been removed.
3. The canonical ``core.resilience.breaker`` is the only future path.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[5]
_HTTP_INIT = (
    _REPO_ROOT
    / "src"
    / "backend"
    / "infrastructure"
    / "clients"
    / "transport"
    / "http"
    / "__init__.py"
)
_VENV_PYTHON = _REPO_ROOT / ".venv" / "bin" / "python"


def _http_init_source() -> str:
    return _HTTP_INIT.read_text(encoding="utf-8")


def _http_init_tree() -> ast.Module:
    return ast.parse(_http_init_source())


class TestHttpClientDeadCodeRemoved:
    """``HttpClient`` must not depend on the deprecated ``core.utils.circuit_breaker`` shim."""

    def test_no_circuit_breaker_import(self) -> None:
        """Verify the deprecated import was removed from http/__init__.py."""
        src = _http_init_source()
        assert "from src.backend.core.utils.circuit_breaker" not in src, (
            "HttpClient must NOT import the deprecated "
            "core.utils.circuit_breaker shim (S127 W1 cleanup)."
        )

    def test_no_circuit_breaker_attribute(self) -> None:
        """Verify no ``self.circuit_breaker = ...`` assignment remains."""
        tree = _http_init_tree()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                    and target.attr == "circuit_breaker"
                ):
                    pytest.fail(
                        "HttpClient must NOT assign self.circuit_breaker — "
                        "the instance attribute was dead code (S127 W1)."
                    )

    def test_canonical_circuit_breaker_still_importable(self) -> None:
        """Canonical CB stays available for future migration."""
        from src.backend.core.resilience.breaker import (
            Breaker,
            BreakerRegistry,
            BreakerSpec,
            CircuitBreaker,
            CircuitOpen,
        )

        # All public names must be present (S100+ canonical).
        assert Breaker is not None
        assert BreakerRegistry is not None
        assert BreakerSpec is not None
        assert CircuitBreaker is Breaker  # alias
        assert CircuitOpen is not None


class TestDeprecatedShimRemoved:
    """The deprecated shim was removed in Sprint 43 (CB consolidation)."""

    def test_shim_module_removed(self) -> None:
        """Verify the deprecated shim no longer exists."""
        import importlib

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("src.backend.core.utils.circuit_breaker")


class TestLayerLinterNoRegression:
    """S127 W1 must not introduce NEW layer violations."""

    def test_extensions_layer_linter_clean(self) -> None:
        """After ``--prune-allowlist``, extensions must have 0 NEW violations."""
        # This is a "smoke" test: the linter ran in the commit hook.
        # We re-run a lightweight check that no extension file imports from
        # ``services/`` or ``infrastructure/`` layers that aren't allowlisted.
        import subprocess

        result = subprocess.run(
            [str(_VENV_PYTHON), "tools/check_layers.py", "--root", "extensions"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=_REPO_ROOT,
        )
        # Output should contain "Нарушений: 0 новых" (0 NEW violations).
        assert "0 новых" in result.stdout, (
            f"extensions linter must show 0 NEW violations after W1 prune; "
            f"got: {result.stdout!r}"
        )
