"""Unit-тесты ``services.auth`` — coverage ratchet (Post-Plan A Sprint 3).

core/auth service package facade: re-exports AD/LDAP client + error +
search entry + server config (4 symbols). ~6 stmts, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class identity.
"""

from __future__ import annotations

import pytest

from src.backend.services import auth
from src.backend.services.auth import (
    AdAuthError,
    AdDirectoryClient,
    AdSearchEntry,
    AdServerConfig,
)


@pytest.mark.unit
class TestAuthFacadeAllExports:
    """``__all__`` audit + class identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "AdAuthError",
            "AdDirectoryClient",
            "AdSearchEntry",
            "AdServerConfig",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(auth, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in auth.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 4 символа."""
        assert len(auth.__all__) == 4

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает K1 S6 auth-сервисы плагин-уровня."""
        assert auth.__doc__ is not None
        assert "auth" in auth.__doc__.lower() or "K1" in auth.__doc__


@pytest.mark.unit
class TestAuthFacadeIdentity:
    """Identity checks для re-exports."""

    def test_ad_directory_client_is_class(self) -> None:
        """``AdDirectoryClient`` — class (async AD/LDAP client)."""
        assert isinstance(AdDirectoryClient, type)

    def test_ad_server_config_is_class(self) -> None:
        """``AdServerConfig`` — class (Pydantic/dataclass server config)."""
        assert isinstance(AdServerConfig, type)

    def test_ad_search_entry_is_class(self) -> None:
        """``AdSearchEntry`` — class (search result dataclass)."""
        assert isinstance(AdSearchEntry, type)

    def test_ad_auth_error_is_exception(self) -> None:
        """``AdAuthError`` — Exception subclass."""
        assert isinstance(AdAuthError, type)
        assert issubclass(AdAuthError, Exception)
