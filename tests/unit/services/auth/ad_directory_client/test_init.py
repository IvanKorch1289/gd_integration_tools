"""Unit-тесты ``services.auth.ad_directory_client`` — coverage ratchet (Post-Plan A Sprint 10).

core/auth/ad_directory_client subpackage (S67 W4 decomp from 457 LOC → 2 files):
re-exports 4 symbols (AdAuthError, AdDirectoryClient, AdSearchEntry, AdServerConfig).
~8 stmts, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class identity.
"""

from __future__ import annotations

import pytest

from src.backend.services.auth import ad_directory_client
from src.backend.services.auth.ad_directory_client import (
    AdAuthError,
    AdDirectoryClient,
    AdSearchEntry,
    AdServerConfig,
)


@pytest.mark.unit
class TestAdDirectoryClientFacadeAllExports:
    """``__all__`` audit + class identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        ["AdAuthError", "AdDirectoryClient", "AdSearchEntry", "AdServerConfig"],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(ad_directory_client, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in ad_directory_client.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 4 символа."""
        assert len(ad_directory_client.__all__) == 4

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает S67 W4 decomp."""
        assert ad_directory_client.__doc__ is not None
        assert "S67 W4" in ad_directory_client.__doc__ or "AD" in ad_directory_client.__doc__


@pytest.mark.unit
class TestAdDirectoryClientFacadeIdentity:
    """Identity checks для 4 re-exports."""

    def test_ad_directory_client_is_class(self) -> None:
        """``AdDirectoryClient`` — class (async AD/LDAP client)."""
        assert isinstance(AdDirectoryClient, type)

    def test_ad_server_config_is_class(self) -> None:
        """``AdServerConfig`` — class (Pydantic server config)."""
        assert isinstance(AdServerConfig, type)

    def test_ad_search_entry_is_class(self) -> None:
        """``AdSearchEntry`` — class (search result dataclass)."""
        assert isinstance(AdSearchEntry, type)

    def test_ad_auth_error_is_exception(self) -> None:
        """``AdAuthError`` — Exception subclass."""
        assert isinstance(AdAuthError, type)
        assert issubclass(AdAuthError, Exception)
