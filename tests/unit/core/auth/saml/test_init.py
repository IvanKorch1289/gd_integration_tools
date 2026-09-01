"""Unit-тесты ``core.auth.saml`` — coverage ratchet (S48 W31).

core/auth/saml/__init__.py — Sprint 9 K1 W1 facade: re-exports SAML
классы (SamlBackend, SamlConfig, SamlAuthResult, SamlError, IdpMetadata
из saml_backend + SamlSpHandler, SpInitiatedLoginResult из sp_handler).
11 statements, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class identity.
"""

from __future__ import annotations

import pytest

from src.backend.core.auth import saml as auth_saml
from src.backend.core.auth.saml import (
    IdpMetadata,
    SamlAuthResult,
    SamlBackend,
    SamlConfig,
    SamlError,
    SamlSpHandler,
    SpInitiatedLoginResult,
)


@pytest.mark.unit
class TestSamlFacadeAllExports:
    """``__all__`` audit + class identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "IdpMetadata",
            "SamlAuthResult",
            "SamlBackend",
            "SamlConfig",
            "SamlError",
            "SamlSpHandler",
            "SpInitiatedLoginResult",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(auth_saml, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in auth_saml.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 7 символов."""
        assert len(auth_saml.__all__) == 7

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает Sprint 9 K1 W1 SAML package decomp."""
        assert auth_saml.__doc__ is not None
        assert "Sprint 9" in auth_saml.__doc__


@pytest.mark.unit
class TestSamlFacadeIdentity:
    """Identity checks для SAML classes + Exception."""

    def test_saml_backend_is_class(self) -> None:
        """``SamlBackend`` — class (low-level SAML protocol backend)."""
        assert isinstance(SamlBackend, type)

    def test_saml_config_is_class(self) -> None:
        """``SamlConfig`` — class (Pydantic settings)."""
        assert isinstance(SamlConfig, type)

    def test_saml_auth_result_is_class(self) -> None:
        """``SamlAuthResult`` — class (Pydantic / dataclass result)."""
        assert isinstance(SamlAuthResult, type)

    def test_idp_metadata_is_class(self) -> None:
        """``IdpMetadata`` — class (Pydantic settings)."""
        assert isinstance(IdpMetadata, type)

    def test_saml_error_is_exception(self) -> None:
        """``SamlError`` — exception class (subclass of Exception)."""
        assert issubclass(SamlError, Exception)

    def test_saml_sp_handler_is_class(self) -> None:
        """``SamlSpHandler`` — class (SP-initiated SSO orchestrator)."""
        assert isinstance(SamlSpHandler, type)

    def test_sp_initiated_login_result_is_class(self) -> None:
        """``SpInitiatedLoginResult`` — class (login flow result)."""
        assert isinstance(SpInitiatedLoginResult, type)
