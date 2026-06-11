"""Tests для S58 W6 — User service + LDAP integration.

Coverage:
* ``LdapSettings`` Pydantic config (load defaults, is_configured);
* ``get_ad_client`` factory (feature flag, no-config, configured);
* ``UserService.login_with_method`` dispatch (password/ldap/invalid);
* ``UserService.login`` deprecation warning;
* ``UserService._extract_username`` priority logic (sAMAccountName, UPN, CN, DN);
* Endpoints: POST /auth/login (password, ldap, invalid, 401, 503);
* Endpoints: GET /auth/methods (returns expected shape);
* ADR-0085 verified.

Strategy: mock AdDirectoryClient (no real LDAP server).
"""

from __future__ import annotations

import warnings
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.backend.services.auth.ad_directory_client import AdAuthError, AdSearchEntry

# === LdapSettings ===


def test_ldap_settings_defaults_not_configured() -> None:
    """Default settings (empty env) → is_configured() = False."""
    from src.backend.core.config.services.ldap import LdapSettings

    s = LdapSettings()  # type: ignore[call-arg]
    # Не все обязательные поля заполнены
    assert s.is_configured() is False
    assert s.user_id_attribute == "userPrincipalName"
    assert s.group_attribute == "memberOf"
    assert s.timeout_seconds == 10.0


def test_ldap_settings_is_configured_when_all_set() -> None:
    """Когда все 4 обязательных поля заданы → is_configured() = True."""
    from src.backend.core.config.services.ldap import LdapSettings

    s = LdapSettings(  # type: ignore[call-arg]
        server_uri="ldaps://ad.example.com:636",
        bind_dn="CN=svc,DC=example,DC=com",
        bind_password="secret",
        search_base="DC=example,DC=com",
    )
    assert s.is_configured() is True


# === get_ad_client factory ===


def test_get_ad_client_respects_feature_flag_false() -> None:
    """feature_flag_enabled=False → get_ad_client returns None."""
    from src.backend.core.auth import ldap_client_factory

    ldap_client_factory.reset_ad_client()
    result = ldap_client_factory.get_ad_client(feature_flag_enabled=False)
    assert result is None


def test_get_ad_client_returns_none_when_not_configured() -> None:
    """Без ldap env vars (default empty) → get_ad_client returns None."""
    from src.backend.core.auth import ldap_client_factory

    ldap_client_factory.reset_ad_client()
    # default LdapSettings has empty fields → is_configured() == False
    result = ldap_client_factory.get_ad_client()
    assert result is None


def test_get_ad_client_caches_instance() -> None:
    """Первый успешный вызов кэширует, второй возвращает тот же instance."""
    from src.backend.core.auth import ldap_client_factory
    from src.backend.core.config.services import ldap as ldap_module

    ldap_client_factory.reset_ad_client()

    # Mock ldap_settings.is_configured() = True + mock AdDirectoryClient
    mock_settings = MagicMock()
    mock_settings.is_configured.return_value = True
    mock_settings.server_uri = "ldaps://ad:636"
    mock_settings.bind_dn = "CN=svc"
    mock_settings.bind_password = "pwd"
    mock_settings.search_base = "DC=x"
    mock_settings.use_ssl = True
    mock_settings.timeout_seconds = 10.0
    mock_settings.user_id_attribute = "userPrincipalName"
    mock_settings.group_attribute = "memberOf"

    mock_client = MagicMock()
    with (
        patch.object(ldap_module, "ldap_settings", mock_settings),
        patch(
            "src.backend.core.auth.ldap_client_factory.AdDirectoryClient",
            return_value=mock_client,
        ),
    ):
        first = ldap_client_factory.get_ad_client()
        second = ldap_client_factory.get_ad_client()
        assert first is mock_client
        assert second is mock_client  # Cached
        assert first is second


# === _extract_username priority ===


def test_extract_username_prefers_samaccountname() -> None:
    """Priority 1: sAMAccountName (если задан)."""
    from extensions.core_entities.users.services.users import _extract_username

    ad_user = AdSearchEntry(
        dn="CN=alice,OU=Users,DC=example,DC=com",
        attributes={
            "sAMAccountName": "alice",
            "userPrincipalName": "alice@example.com",
            "cn": "Alice Doe",
        },
    )
    assert _extract_username(ad_user) == "alice"


def test_extract_username_strips_upn_domain() -> None:
    """Priority 2: userPrincipalName → strip @domain."""
    from extensions.core_entities.users.services.users import _extract_username

    ad_user = AdSearchEntry(
        dn="CN=alice,DC=x", attributes={"userPrincipalName": "alice@example.com"}
    )
    assert _extract_username(ad_user) == "alice"


def test_extract_username_falls_back_to_cn() -> None:
    """Priority 3: cn attribute."""
    from extensions.core_entities.users.services.users import _extract_username

    ad_user = AdSearchEntry(dn="CN=alice,DC=x", attributes={"cn": "Alice Doe"})
    assert _extract_username(ad_user) == "Alice Doe"


def test_extract_username_falls_back_to_dn() -> None:
    """Priority 4: first CN из DN."""
    from extensions.core_entities.users.services.users import _extract_username

    ad_user = AdSearchEntry(dn="CN=bob,OU=Users,DC=example,DC=com", attributes={})
    assert _extract_username(ad_user) == "bob"


# === UserService.login_with_method dispatch ===


@pytest.mark.asyncio
async def test_login_with_method_dispatches_to_password() -> None:
    """method=password → calls _login_password."""
    from extensions.core_entities.users.services.users import UserService

    service = UserService.__new__(UserService)  # bypass __init__
    service.repo = MagicMock()
    service._login_password = AsyncMock(return_value="user_password_result")

    result = await service.login_with_method(
        method="password", username="alice", password="pwd"
    )
    assert result == "user_password_result"
    service._login_password.assert_awaited_once_with(username="alice", password="pwd")


@pytest.mark.asyncio
async def test_login_with_method_dispatches_to_ldap() -> None:
    """method=ldap → calls _login_ldap."""
    from extensions.core_entities.users.services.users import UserService

    service = UserService.__new__(UserService)
    service.repo = MagicMock()
    service._login_ldap = AsyncMock(return_value="user_ldap_result")

    with patch(
        "src.backend.core.auth.ldap_client_factory.get_ad_client", return_value=None
    ):
        result = await service.login_with_method(
            method="ldap", username="alice@example.com", password="pwd"
        )
    assert result == "user_ldap_result"
    service._login_ldap.assert_awaited_once_with(
        username="alice@example.com", password="pwd"
    )


@pytest.mark.asyncio
async def test_login_with_method_unknown_raises() -> None:
    """method="oauth" → ValueError."""
    from extensions.core_entities.users.services.users import UserService

    service = UserService.__new__(UserService)
    with pytest.raises(ValueError, match="Unknown auth method"):
        await service.login_with_method(
            method="oauth", username="alice", password="pwd"
        )


# === _login_password (legacy) ===


@pytest.mark.asyncio
async def test_login_password_returns_user_on_valid_credentials() -> None:
    """_login_password → User если пароль верный."""
    from extensions.core_entities.users.services.users import UserService

    service = UserService.__new__(UserService)
    mock_user = MagicMock()
    mock_user.verify_password = MagicMock(return_value=True)
    service.repo = MagicMock()
    service.repo.get_by_username = AsyncMock(return_value=mock_user)

    result = await service._login_password(username="alice", password="correct")
    assert result is mock_user


@pytest.mark.asyncio
async def test_login_password_returns_none_on_invalid() -> None:
    """_login_password → None если user не найден или пароль неверный."""
    from extensions.core_entities.users.services.users import UserService

    service = UserService.__new__(UserService)
    service.repo = MagicMock()
    service.repo.get_by_username = AsyncMock(return_value=None)

    result = await service._login_password(username="alice", password="wrong")
    assert result is None


# === login (legacy) deprecation warning ===


@pytest.mark.asyncio
async def test_login_emits_deprecation_warning() -> None:
    """UserService.login() → DeprecationWarning при вызове."""
    from extensions.core_entities.users.services.users import UserService

    service = UserService.__new__(UserService)
    service._login_password = AsyncMock(return_value=MagicMock())

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        await service.login(data={"username": "alice", "password": "pwd"})

    deprecation_warnings = [
        warning for warning in w if issubclass(warning.category, DeprecationWarning)
    ]
    assert len(deprecation_warnings) >= 1
    assert "login_with_method" in str(deprecation_warnings[0].message)


# === Endpoints: POST /auth/login ===


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient для endpoint tests."""
    from fastapi import FastAPI

    from src.backend.entrypoints.api.v1.routers import get_v1_routers

    app = FastAPI()
    app.include_router(get_v1_routers(), prefix="/api/v1")
    return TestClient(app)


def test_login_password_success(client: TestClient) -> None:
    """POST /auth/login method=password + valid creds → 200 + JWT."""
    mock_user = MagicMock()
    mock_user.username = "alice"
    mock_user.is_superuser = False

    async def fake_login(*args: Any, **kwargs: Any) -> Any:
        return mock_user

    with (
        patch(
            "src.backend.entrypoints.api.v1.endpoints.auth_login._get_user_service",
            AsyncMock(return_value=MagicMock(login_with_method=fake_login)),
        ),
        patch(
            "src.backend.entrypoints.api.v1.endpoints.auth_login._get_jwt_backend",
            AsyncMock(return_value=lambda subject, claims: ("mock-token-xyz", 3600)),
        ),
    ):
        r = client.post(
            "/api/v1/auth/login",
            json={"method": "password", "username": "alice", "password": "correct"},
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["username"] == "alice"
    assert data["auth_method"] == "password"
    assert data["access_token"] == "mock-token-xyz"
    assert data["token_type"] == "bearer"
    assert data["is_superuser"] is False


def test_login_invalid_credentials_returns_401(client: TestClient) -> None:
    """POST /auth/login + invalid creds → 401."""

    async def fake_login(*args: Any, **kwargs: Any) -> Any:
        return None

    with patch(
        "src.backend.entrypoints.api.v1.endpoints.auth_login._get_user_service",
        AsyncMock(return_value=MagicMock(login_with_method=fake_login)),
    ):
        r = client.post(
            "/api/v1/auth/login",
            json={"method": "password", "username": "alice", "password": "wrong"},
        )
    assert r.status_code == 401
    assert "Invalid credentials" in r.json()["detail"]


def test_login_ldap_unavailable_returns_503(client: TestClient) -> None:
    """POST /auth/login method=ldap, LDAP not configured → 503."""

    async def fake_login(*args: Any, **kwargs: Any) -> Any:
        raise AdAuthError("LDAP auth is not enabled or not configured")

    with patch(
        "src.backend.entrypoints.api.v1.endpoints.auth_login._get_user_service",
        AsyncMock(return_value=MagicMock(login_with_method=fake_login)),
    ):
        r = client.post(
            "/api/v1/auth/login",
            json={"method": "ldap", "username": "alice@example.com", "password": "pwd"},
        )
    assert r.status_code == 503
    assert "LDAP" in r.json()["detail"]


def test_login_unknown_method_returns_400(client: TestClient) -> None:
    """POST /auth/login с валидным method но service raise'ит ValueError → 400."""

    async def fake_login(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("Unknown auth method: 'password-mock-error'")

    with patch(
        "src.backend.entrypoints.api.v1.endpoints.auth_login._get_user_service",
        AsyncMock(return_value=MagicMock(login_with_method=fake_login)),
    ):
        r = client.post(
            "/api/v1/auth/login",
            json={"method": "password", "username": "alice", "password": "pwd"},
        )
    assert r.status_code == 400


def test_login_invalid_method_literal_returns_422(client: TestClient) -> None:
    """POST /auth/login method=oauth (не в Literal) → 422 (Pydantic validation)."""
    r = client.post(
        "/api/v1/auth/login",
        json={"method": "oauth", "username": "alice", "password": "pwd"},
    )
    assert r.status_code == 422  # Pydantic Literal validation


# === Endpoints: GET /auth/methods ===


def test_auth_methods_default_only_password(client: TestClient) -> None:
    """GET /auth/methods without LDAP config → methods=["password"], ldap_enabled=False."""
    from src.backend.core.auth import ldap_client_factory

    ldap_client_factory.reset_ad_client()
    r = client.get("/api/v1/auth/methods")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["methods"] == ["password"]
    assert data["ldap_enabled"] is False
    assert data["password_enabled"] is True
    assert data["default_method"] == "password"
    assert "password" in data["deprecations"]


def test_auth_methods_with_ldap_enabled(client: TestClient) -> None:
    """GET /auth/methods с LDAP enabled → methods=["ldap", "password"], default=ldap."""
    from src.backend.core.auth import ldap_client_factory
    from src.backend.core.config.services import ldap as ldap_module

    ldap_client_factory.reset_ad_client()
    mock_settings = MagicMock()
    mock_settings.is_configured.return_value = True
    mock_client = MagicMock()
    mock_client.is_available.return_value = True

    with (
        patch.object(ldap_module, "ldap_settings", mock_settings),
        patch(
            "src.backend.core.auth.ldap_client_factory.AdDirectoryClient",
            return_value=mock_client,
        ),
    ):
        r = client.get("/api/v1/auth/methods")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "ldap" in data["methods"]
    assert data["ldap_enabled"] is True
    assert data["default_method"] == "ldap"
    assert data["methods"] == ["ldap", "password"]


# === ADR-0085 verification ===


def test_adr_0085_file_exists() -> None:
    """ADR-0085 существует и содержит ключевые секции."""
    from pathlib import Path

    adr_path = Path("docs/adr/0085-user-auth-ldap-integration.md")
    assert adr_path.exists()
    content = adr_path.read_text(encoding="utf-8")
    assert "Status:** Accepted" in content
    assert "Auto-provisioning" in content or "auto-provision" in content
    assert "DeprecationWarning" in content or "deprecated" in content
    assert "feature_flags.saml_ad_login_enabled" in content
