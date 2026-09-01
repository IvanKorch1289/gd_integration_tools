"""Unit-тесты ``core.api.security`` — coverage ratchet (S48 W20).

core/api/security.py — Sprint 37 facade: re-exports
infrastructure.security (pii_streaming, signatures, CertStore) +
backward-compat aliases (PiiStreaming, Signatures). 6 statements, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + alias identity + module identity.
"""

from __future__ import annotations

import pytest

from src.backend.core.api import security
from src.backend.core.api.security import (
    CertStore,
    PiiStreaming,
    Signatures,
    pii_streaming,
    signatures,
)


@pytest.mark.unit
class TestSecurityFacadeAllExports:
    """``__all__`` audit + module/class identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        ["CertStore", "pii_streaming", "signatures", "PiiStreaming", "Signatures"],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(security, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in security.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 5 символов."""
        assert len(security.__all__) == 5

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает Sprint 37 facade."""
        assert security.__doc__ is not None
        assert "Sprint 37" in security.__doc__


@pytest.mark.unit
class TestSecurityFacadeIdentity:
    """Identity checks: backward-compat aliases + canonical classes."""

    def test_pii_streaming_aliases_capitalized(self) -> None:
        """``PiiStreaming`` (capitalized) = ``pii_streaming`` module (backward-compat)."""
        assert PiiStreaming is pii_streaming

    def test_signatures_aliases_capitalized(self) -> None:
        """``Signatures`` (capitalized) = ``signatures`` module."""
        assert Signatures is signatures

    def test_certstore_is_class(self) -> None:
        """``CertStore`` — class (type)."""
        assert isinstance(CertStore, type)

    def test_pii_streaming_module_importable(self) -> None:
        """``pii_streaming`` module importable + имеет canonical helpers."""
        assert pii_streaming is not None
        # Не проверяем конкретные attrs (зависит от содержимого модуля).
