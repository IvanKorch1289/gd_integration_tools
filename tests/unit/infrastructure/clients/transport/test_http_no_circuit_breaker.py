"""Regression test: HttpClient circuit breaker wiring.

History:
* S127 W1 removed the unused ``self.circuit_breaker = get_circuit_breaker()``
  from ``HttpClient.__init__``. The instance attribute was pure dead code
  (and ``core.utils.circuit_breaker`` import that fed it was deprecated).
* S140-W5 (``924a48d``) re-added the assignment as part of CB consolidation
  (S43), making ``self.circuit_breaker`` actively used in
  ``request_mixin.py:117`` (``async with self.circuit_breaker.guard()``).
* S163 W31: test updated — verify CB IS correctly wired (positive test),
  not absent. Matches current canonical pattern.

Tests enforce:
1. ``HttpClient`` must use the canonical ``core.resilience.breaker`` import
   (NOT the deprecated ``core.utils.circuit_breaker`` shim).
2. ``self.circuit_breaker = get_breaker_registry().get_or_create(...)``
   IS present (since S140-W5 brought back as active code).
3. The canonical ``core.resilience.breaker`` symbols are importable.
4. The deprecated shim was removed.
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

    def test_circuit_breaker_attribute_wired(self) -> None:
        """S163 W31: verify ``self.circuit_breaker`` IS wired (S140-W5+).

        S140-W5 (``924a48d``) restored ``self.circuit_breaker = ...`` as
        actively-used CB (see ``request_mixin.py:117`` where it's used via
        ``async with self.circuit_breaker.guard():``). The test now verifies
        CB IS wired correctly (positive assertion), not that it's absent.

        Если кто-то в будущем случайно удалит assignment, ``RequestMixin``
        сломается at runtime (AttributeError на .guard()). Этот test — guard
        против такого регресса.
        """
        src = _http_init_source()
        assert (
            "self.circuit_breaker = get_breaker_registry()" in src
        ), (
            "HttpClient must wire self.circuit_breaker через canonical "
            "core.resilience.breaker (S140-W5+ pattern). If вы reverted к "
            "dead-code, RequestMixin сломается."
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
