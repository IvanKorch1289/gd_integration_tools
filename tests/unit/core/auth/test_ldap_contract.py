"""Tests for ``src.backend.core.auth.ldap_contract``.

Контракты для LDAP/AD клиента:
- ``AdServerConfig`` — dataclass с __post_init__ auto-SSL
- ``AdDirectoryClientProtocol`` — Protocol
- ``AdDirectoryClientFactory`` — Protocol

Тесты:
- Defaults полей
- ``__post_init__`` auto-SSL для ldaps://
- ``__post_init__`` НЕ трогает use_ssl для ldap://
- Protocol structural typing (duck-typed реализации подходят)
"""

from __future__ import annotations

import pytest

from src.backend.core.auth.ldap_contract import (
    AdDirectoryClientFactory,
    AdDirectoryClientProtocol,
    AdServerConfig,
)


# ── AdServerConfig ───────────────────────────────────────────────────


class TestAdServerConfigDefaults:
    """Defaults для optional полей."""

    def test_minimal_construction(self) -> None:
        """Только 4 обязательных поля; остальные с дефолтами."""
        cfg = AdServerConfig(
            server_uri="ldap://localhost:389",
            bind_dn="CN=svc,DC=corp,DC=local",
            bind_password="secret",
            search_base="OU=Users,DC=corp,DC=local",
        )
        assert cfg.server_uri == "ldap://localhost:389"
        assert cfg.bind_dn == "CN=svc,DC=corp,DC=local"
        assert cfg.bind_password == "secret"
        assert cfg.search_base == "OU=Users,DC=corp,DC=local"
        assert cfg.use_ssl is False
        assert cfg.timeout_seconds == 10.0
        assert cfg.user_id_attribute == "userPrincipalName"
        assert cfg.group_attribute == "memberOf"

    def test_use_ssl_explicit(self) -> None:
        cfg = AdServerConfig(
            server_uri="ldap://localhost:389",
            bind_dn="x",
            bind_password="y",
            search_base="z",
            use_ssl=True,
        )
        assert cfg.use_ssl is True

    def test_timeout_custom(self) -> None:
        cfg = AdServerConfig(
            server_uri="ldap://localhost",
            bind_dn="x",
            bind_password="y",
            search_base="z",
            timeout_seconds=30.0,
        )
        assert cfg.timeout_seconds == 30.0

    def test_custom_user_id_attribute(self) -> None:
        cfg = AdServerConfig(
            server_uri="ldap://localhost",
            bind_dn="x",
            bind_password="y",
            search_base="z",
            user_id_attribute="uid",
        )
        assert cfg.user_id_attribute == "uid"

    def test_custom_group_attribute(self) -> None:
        cfg = AdServerConfig(
            server_uri="ldap://localhost",
            bind_dn="x",
            bind_password="y",
            search_base="z",
            group_attribute="member",
        )
        assert cfg.group_attribute == "member"


class TestAdServerConfigPostInit:
    """``__post_init__`` auto-enables SSL для ``ldaps://``."""

    def test_ldaps_uri_enables_ssl(self) -> None:
        """``ldaps://...`` → ``use_ssl=True`` автоматически."""
        cfg = AdServerConfig(
            server_uri="ldaps://secure.example.com:636",
            bind_dn="x",
            bind_password="y",
            search_base="z",
        )
        assert cfg.use_ssl is True

    def test_ldap_uri_keeps_ssl_false(self) -> None:
        """``ldap://...`` → ``use_ssl`` остаётся ``False`` (default)."""
        cfg = AdServerConfig(
            server_uri="ldap://insecure.example.com:389",
            bind_dn="x",
            bind_password="y",
            search_base="z",
        )
        assert cfg.use_ssl is False

    def test_ldap_uri_with_explicit_ssl_true_keeps(self) -> None:
        """``ldap://...`` с ``use_ssl=True`` — explicit остаётся (хотя странно)."""
        cfg = AdServerConfig(
            server_uri="ldap://localhost",
            bind_dn="x",
            bind_password="y",
            search_base="z",
            use_ssl=True,  # starttls через ldap://
        )
        assert cfg.use_ssl is True

    def test_ldaps_uri_with_explicit_ssl_false_overridden(self) -> None:
        """``ldaps://...`` с ``use_ssl=False`` — auto-init переопределяет на True.

        Это by design: ldaps:// — это всегда TLS, нельзя отключить.
        """
        cfg = AdServerConfig(
            server_uri="ldaps://secure.example.com:636",
            bind_dn="x",
            bind_password="y",
            search_base="z",
            use_ssl=False,  # попытка отключить — игнорируется
        )
        assert cfg.use_ssl is True


# ── AdDirectoryClientProtocol ────────────────────────────────────────


class TestAdDirectoryClientProtocol:
    """Protocol structural typing — duck-typed реализации подходят."""

    def test_duck_typed_implementation_satisfies_protocol(self) -> None:
        """Любой класс с методом ``is_available() -> bool`` — подходит."""

        class FakeClient:
            def is_available(self) -> bool:
                return True

        client: AdDirectoryClientProtocol = FakeClient()
        assert client.is_available() is True

    def test_returns_false(self) -> None:
        class FakeClient:
            def is_available(self) -> bool:
                return False

        client: AdDirectoryClientProtocol = FakeClient()
        assert client.is_available() is False

    def test_runtime_checkable_via_typing(self) -> None:
        """Объект без ``is_available`` НЕ соответствует protocol.

        Python Protocol — structural typing; runtime check через
        ``isinstance`` работает только для ``@runtime_checkable``.
        Здесь проверяем через ``hasattr`` как equivalent.
        """

        class NoMethod:
            pass

        assert not hasattr(NoMethod(), "is_available")


# ── AdDirectoryClientFactory ─────────────────────────────────────────


class TestAdDirectoryClientFactory:
    """Factory Protocol — создаёт AdDirectoryClientProtocol из AdServerConfig."""

    def test_factory_creates_client(self) -> None:
        """Fake-factory создаёт fake-client с правильным interface."""

        class FakeClient:
            def __init__(self, config: AdServerConfig) -> None:
                self._config = config

            def is_available(self) -> bool:
                return bool(self._config.server_uri)

        class FakeFactory:
            def __call__(
                self,
                *,
                config: AdServerConfig,
                connection_factory: object | None = None,
            ) -> AdDirectoryClientProtocol:
                return FakeClient(config)

        factory: AdDirectoryClientFactory = FakeFactory()
        cfg = AdServerConfig(
            server_uri="ldap://x",
            bind_dn="a",
            bind_password="b",
            search_base="c",
        )
        client = factory(config=cfg)
        assert client.is_available() is True

    def test_factory_with_connection_factory(self) -> None:
        """``connection_factory`` parameter опциональный (для тестов с mock)."""
        captured_connection = None

        class FakeClient:
            def is_available(self) -> bool:
                return True

        class FakeConnFactory:
            def __call__(self) -> object:
                return "mock-connection"

        class FakeFactory:
            def __call__(
                self,
                *,
                config: AdServerConfig,
                connection_factory: object | None = None,
            ) -> AdDirectoryClientProtocol:
                nonlocal captured_connection
                if connection_factory is not None:
                    captured_connection = connection_factory()
                return FakeClient()

        factory: AdDirectoryClientFactory = FakeFactory()
        cfg = AdServerConfig(
            server_uri="ldap://x",
            bind_dn="a",
            bind_password="b",
            search_base="c",
        )
        fake_conn_factory = FakeConnFactory()
        factory(config=cfg, connection_factory=fake_conn_factory)
        assert captured_connection == "mock-connection"


class TestLdapContractExports:
    """``__all__`` exports."""

    def test_exports(self) -> None:
        from src.backend.core.auth import ldap_contract

        assert "AdServerConfig" in ldap_contract.__all__
        assert "AdDirectoryClientProtocol" in ldap_contract.__all__
        assert "AdDirectoryClientFactory" in ldap_contract.__all__
