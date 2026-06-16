"""Tests for services/admin/sso.py shim (S125 W4).

Verifies backward-compat imports work + DeprecationWarning emitted.
"""

from __future__ import annotations

import warnings

import pytest


class TestSsoShimReExports:
    """Old symbols must still be importable from services.admin.sso."""

    def test_sso_user_info_reexported(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from src.backend.services.admin.sso import SSOUserInfo

        # Same identity as core.auth.sso_types.SSOUserInfo
        from src.backend.core.auth.sso_types import SSOUserInfo as CoreSSOUserInfo

        assert SSOUserInfo is CoreSSOUserInfo

    def test_saml_sso_client_is_saml_backend_alias(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from src.backend.services.admin.sso import SamlSSOClient

        from src.backend.core.auth import SamlBackend

        assert SamlSSOClient is SamlBackend

    def test_oidc_sso_client_kept_as_stub(self) -> None:
        """OIDC не реализован в S125, остаётся ABC stub."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from src.backend.services.admin.sso import OidcSSOClient

        # ABC — нельзя инстанцировать
        with pytest.raises(TypeError):
            OidcSSOClient(config=None)  # type: ignore[abstract]

    def test_admin_sso_config_legacy_class_preserved(self) -> None:
        """AdminSSOConfig — legacy class с provider field, нет в core."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from src.backend.services.admin.sso import AdminSSOConfig

        cfg = AdminSSOConfig(provider="saml", metadata_url="https://x", enabled=True)
        assert cfg.provider == "saml"
        assert cfg.enabled is True

        # Invalid provider
        with pytest.raises(ValueError, match="saml.*oidc"):
            AdminSSOConfig(provider="ldap")  # type: ignore[arg-type]

    def test_require_sso_auth_legacy_decorator_importable(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from src.backend.services.admin.sso import require_sso_auth_legacy

        # Old API: require_sso_auth_legacy(resource, action) returns decorator
        decorator = require_sso_auth_legacy("admin.feature_flag", "write")
        assert callable(decorator)

    def test_require_sso_auth_new_api_reexported(self) -> None:
        """Shim re-exports new-API require_sso_auth (registry-based)."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from src.backend.core.auth import require_sso_auth as core_req
            from src.backend.services.admin.sso import require_sso_auth as shim_req

        # Same identity (shim re-exports core)
        assert shim_req is core_req


class TestSsoShimDeprecationWarning:
    """Import from shim must emit DeprecationWarning."""

    def test_import_emits_deprecation_warning(self) -> None:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            # Force re-import
            import importlib

            import src.backend.services.admin.sso

            importlib.reload(src.backend.services.admin.sso)

        deprecation_warnings = [
            w for w in caught if issubclass(w.category, DeprecationWarning)
        ]
        assert len(deprecation_warnings) >= 1, (
            "Import from services.admin.sso must emit DeprecationWarning"
        )

    def test_warning_mentions_core_auth_migration(self) -> None:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            import importlib

            import src.backend.services.admin.sso

            importlib.reload(src.backend.services.admin.sso)

        msgs = " ".join(str(w.message) for w in caught)
        assert "core.auth" in msgs or "core/auth" in msgs, (
            f"DeprecationWarning must point to core.auth migration path: {msgs!r}"
        )


class TestSsoShimDoesNotRegressCore:
    """Shim must not break core.auth imports."""

    def test_core_auth_still_importable(self) -> None:
        from src.backend.core.auth import SsoRegistry, require_sso_auth

        # All symbols resolved
        assert SsoRegistry is not None
        assert require_sso_auth is not None
